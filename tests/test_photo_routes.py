"""Интеграционные тесты маршрутов «тренировка по фото»:

- POST /api/workouts/photo — загрузка, OCR (замокан), форма подтверждения
- POST /api/workouts/photo/confirm — сохранение после явного подтверждения
- GET /api/photos/tmp/<token> и GET /api/photos/<relpath> — выдача фото

Реальный OCR-бэкенд нигде не вызывается — recognize_text подменяется в
app.main напрямую (main.py делает `from app.ocr import recognize_text`,
поэтому патчить нужно app.main.recognize_text, а не app.ocr.recognize_text).
"""
import io
import json

import pytest
from PIL import Image

import app.main as main_module
import app.ocr as ocr_module
import app.photos as photos_module
from conftest import login, register_and_login

NO_OCR_RESULT = {"text": "", "backend": "none", "message": ocr_module.NO_OCR_MESSAGE}


@pytest.fixture(autouse=True)
def isolated_photos_dir(tmp_path, monkeypatch):
    """Каждый тест пишет фото в свой временный каталог, а не в workspace/photos."""
    monkeypatch.setattr(photos_module, "PHOTOS_ROOT", str(tmp_path / "photos"))


@pytest.fixture(autouse=True)
def no_real_ocr(monkeypatch):
    """По умолчанию OCR замокан на 'нет OCR' — реальный backend никогда не трогаем.
    Тесты, которым нужен другой результат, переопределяют main_module.recognize_text сами."""
    monkeypatch.setattr(main_module, "recognize_text", lambda content: dict(NO_OCR_RESULT))


def _jpeg_bytes(size=(20, 20), color=(10, 20, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="JPEG")
    return buf.getvalue()


def upload_photo(client, content=None, filename="photo.jpg"):
    content = content if content is not None else _jpeg_bytes()
    return client.post(
        "/api/workouts/photo",
        data={"photo": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )


def confirm_photo(client, **fields):
    return client.post(
        "/api/workouts/photo/confirm",
        data=json.dumps(fields),
        content_type="application/json",
    )


# =====================================================================
# Доступ без входа
# =====================================================================


def test_upload_photo_without_login_returns_401(client):
    resp = upload_photo(client)
    assert resp.status_code == 401


def test_confirm_photo_without_login_returns_401(client):
    resp = confirm_photo(client, photo_token="x", date="2026-01-01", distance_km=1, duration_min=1)
    assert resp.status_code == 401


# =====================================================================
# Загрузка без OCR — форма подтверждения с пустыми полями и подсказкой
# =====================================================================


def test_upload_without_available_ocr_returns_empty_fields_and_hint(client):
    register_and_login(client, "user@example.com")
    resp = upload_photo(client)
    assert resp.status_code == 201

    data = resp.get_json()
    assert data["ocr_backend"] == "none"
    assert data["ocr_message"] == ocr_module.NO_OCR_MESSAGE
    assert data["confidence"] == 0.0
    for field in ("date", "distance_km", "duration_min", "avg_speed_kmh", "avg_hr", "elevation_gain_m"):
        assert data["fields"][field] is None
    assert data["fragments"] == {}
    assert data["photo_token"]


def test_upload_does_not_save_anything_to_db(client):
    register_and_login(client, "user@example.com")
    upload_photo(client)
    assert client.get("/api/workouts").get_json() == []


def test_upload_with_recognized_text_returns_parsed_fields(client, monkeypatch):
    register_and_login(client, "user@example.com")
    monkeypatch.setattr(
        main_module,
        "recognize_text",
        lambda content: {"text": "Distance 42.15 km\n1:42:07", "backend": "tesseract", "message": None},
    )
    resp = upload_photo(client)
    data = resp.get_json()
    assert data["ocr_backend"] == "tesseract"
    assert data["ocr_message"] is None
    assert data["fields"]["distance_km"] == pytest.approx(42.15)
    assert data["fields"]["duration_min"] == pytest.approx(102.11666666666666)
    assert data["confidence"] > 0


def test_upload_missing_photo_field_returns_400(client):
    register_and_login(client, "user@example.com")
    resp = client.post("/api/workouts/photo", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


# =====================================================================
# Валидация размера и формата файла
# =====================================================================


def test_upload_oversized_file_returns_clear_400_error(client):
    register_and_login(client, "user@example.com")
    oversized = b"\xff\xd8\xff" + b"0" * (16 * 1024 * 1024)
    resp = upload_photo(client, content=oversized, filename="big.jpg")
    assert resp.status_code == 400
    body = resp.get_json()
    assert "15" in body["error"]


def test_upload_unsupported_format_returns_clear_400_error(client):
    register_and_login(client, "user@example.com")
    resp = upload_photo(client, content=b"just plain text, not an image", filename="note.txt")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_upload_empty_file_returns_400(client):
    register_and_login(client, "user@example.com")
    resp = upload_photo(client, content=b"", filename="empty.jpg")
    assert resp.status_code == 400


# =====================================================================
# HEIC
# =====================================================================


def _heic_bytes(size=(20, 20), color=(1, 2, 3)) -> bytes:
    pillow_heif = pytest.importorskip("pillow_heif")
    pillow_heif.register_heif_opener()
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="HEIF")
    return buf.getvalue()


def test_upload_heic_photo_is_processed_when_pillow_heif_available(client):
    register_and_login(client, "user@example.com")
    resp = upload_photo(client, content=_heic_bytes(), filename="photo.heic")
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["photo_token"]
    # Итоговое фото хранится и отдаётся как JPEG независимо от исходного формата.
    tmp_resp = client.get(f"/api/photos/tmp/{data['photo_token']}")
    assert tmp_resp.status_code == 200
    assert tmp_resp.content_type == "image/jpeg"


def test_upload_heic_without_pillow_heif_returns_clear_error(client, monkeypatch):
    register_and_login(client, "user@example.com")
    content = _heic_bytes()  # генерируем ДО того, как имитируем отсутствие pillow_heif
    monkeypatch.setitem(__import__("sys").modules, "pillow_heif", None)
    resp = upload_photo(client, content=content, filename="photo.heic")
    assert resp.status_code == 400
    assert "pillow-heif" in resp.get_json()["error"] or "HEIC" in resp.get_json()["error"]


# =====================================================================
# Подтверждение: обязательные поля
# =====================================================================


def test_confirm_without_photo_token_returns_400(client):
    register_and_login(client, "user@example.com")
    resp = confirm_photo(client, date="2026-01-01", distance_km=10, duration_min=30)
    assert resp.status_code == 400


def test_confirm_without_required_fields_returns_400_and_saves_nothing(client):
    register_and_login(client, "user@example.com")
    token = upload_photo(client).get_json()["photo_token"]

    resp = confirm_photo(client, photo_token=token)  # нет даты/дистанции/времени
    assert resp.status_code == 400
    assert client.get("/api/workouts").get_json() == []


def test_confirm_with_invalid_unknown_token_returns_400(client):
    register_and_login(client, "user@example.com")
    resp = confirm_photo(
        client, photo_token="0" * 32, date="2026-01-01", distance_km=10, duration_min=30
    )
    assert resp.status_code == 400
    assert client.get("/api/workouts").get_json() == []


# =====================================================================
# Подтверждение: успешное сохранение с source='photo' и photo_path
# =====================================================================


def test_confirm_saves_workout_with_photo_source_and_path(client):
    email = register_and_login(client, "user@example.com")
    token = upload_photo(client).get_json()["photo_token"]

    resp = confirm_photo(
        client,
        photo_token=token,
        date="2026-09-15",
        distance_km=42.15,
        duration_min=102,
        avg_hr=142,
        elevation_gain_m=512,
    )
    assert resp.status_code == 201
    assert resp.get_json() == {"saved": 1, "duplicates": 0}

    workouts = client.get("/api/workouts").get_json()
    assert len(workouts) == 1
    workout = workouts[0]
    assert workout["source"] == "photo"
    assert workout["photo_path"] is not None
    assert workout["photo_path"].endswith(".jpg")
    assert workout["date"] == "2026-09-15"
    assert workout["distance_km"] == pytest.approx(42.15)


def test_confirmed_photo_is_served_at_permanent_url(client):
    register_and_login(client, "user@example.com")
    token = upload_photo(client).get_json()["photo_token"]
    confirm_photo(client, photo_token=token, date="2026-09-15", distance_km=10, duration_min=30)

    photo_path = client.get("/api/workouts").get_json()[0]["photo_path"]
    resp = client.get(f"/api/photos/{photo_path}")
    assert resp.status_code == 200
    assert resp.content_type == "image/jpeg"


def test_temp_photo_no_longer_served_after_confirm(client):
    register_and_login(client, "user@example.com")
    token = upload_photo(client).get_json()["photo_token"]
    confirm_photo(client, photo_token=token, date="2026-09-15", distance_km=10, duration_min=30)

    resp = client.get(f"/api/photos/tmp/{token}")
    assert resp.status_code == 404


# =====================================================================
# Дедупликация
# =====================================================================


def test_confirm_participates_in_deduplication_against_csv_workout(client):
    register_and_login(client, "user@example.com")
    client.post(
        "/api/workouts/upload",
        data={"file": (io.BytesIO(b"date,distance_km,duration_min\n2026-09-15,42.15,100\n"), "w.csv")},
        content_type="multipart/form-data",
    )

    token = upload_photo(client).get_json()["photo_token"]
    resp = confirm_photo(
        client, photo_token=token, date="2026-09-15", distance_km=42.10, duration_min=101
    )
    assert resp.status_code == 201
    assert resp.get_json() == {"saved": 0, "duplicates": 1}

    workouts = client.get("/api/workouts").get_json()
    assert len(workouts) == 1
    assert workouts[0]["source"] == "csv"  # оригинальная CSV-тренировка не заменена фото-дублем


def test_confirm_duplicate_of_another_photo_workout_is_detected(client):
    register_and_login(client, "user@example.com")
    token1 = upload_photo(client).get_json()["photo_token"]
    confirm_photo(client, photo_token=token1, date="2026-09-15", distance_km=42.15, duration_min=100)

    token2 = upload_photo(client).get_json()["photo_token"]
    resp = confirm_photo(
        client, photo_token=token2, date="2026-09-15", distance_km=42.16, duration_min=101
    )
    assert resp.get_json() == {"saved": 0, "duplicates": 1}


# =====================================================================
# Изоляция по user_id
# =====================================================================


def test_photo_workout_isolated_between_users(client):
    register_and_login(client, "a@example.com")
    token = upload_photo(client).get_json()["photo_token"]
    confirm_photo(client, photo_token=token, date="2026-09-15", distance_km=10, duration_min=30)
    photo_path = client.get("/api/workouts").get_json()[0]["photo_path"]
    client.get("/logout")

    register_and_login(client, "b@example.com")
    assert client.get("/api/workouts").get_json() == []

    # чужое фото недоступно по прямой ссылке
    resp = client.get(f"/api/photos/{photo_path}")
    assert resp.status_code == 404


def test_confirm_uses_current_users_email_and_id(client):
    register_and_login(client, "a@example.com")
    token = upload_photo(client).get_json()["photo_token"]
    confirm_photo(client, photo_token=token, date="2026-09-15", distance_km=10, duration_min=30)

    workout = client.get("/api/workouts").get_json()[0]
    assert workout["user_email"] == "a@example.com"


# =====================================================================
# Дефекты, обнаруженные тестами (см. финальный отчёт)
# =====================================================================


def test_defect_duplicate_confirm_leaves_temp_token_unusable_despite_nothing_saved(client):
    """confirm_workout_photo вызывает finalize_photo() ДО save_workouts().

    Если тренировка оказывается дублем, файл фото уже перемещён в постоянное
    хранилище (и осиротел там, ни на что не ссылаясь из БД), а повторная
    попытка подтвердить тот же token завершается ошибкой "уже подтверждено",
    хотя по факту ничего не было сохранено. Пользователю придётся заново
    загружать фото, хотя тренировка и так не изменилась.
    """
    register_and_login(client, "user@example.com")
    client.post(
        "/api/workouts/upload",
        data={"file": (io.BytesIO(b"date,distance_km,duration_min\n2026-09-15,42.15,100\n"), "w.csv")},
        content_type="multipart/form-data",
    )

    token = upload_photo(client).get_json()["photo_token"]
    dup_resp = confirm_photo(
        client, photo_token=token, date="2026-09-15", distance_km=42.15, duration_min=100
    )
    assert dup_resp.get_json()["duplicates"] == 1  # дубль, ничего не сохранено

    retry_resp = confirm_photo(
        client, photo_token=token, date="2026-09-15", distance_km=42.15, duration_min=100
    )
    assert retry_resp.status_code == 400  # token уже "использован" — файл был перемещён при первой попытке


def test_defect_ocr_backend_error_crashes_upload_route_with_500(client, monkeypatch):
    """recognize_text() не оборачивается в try/except в upload_workout_photo —
    исключение из бэкенда (например, Vision не смог декодировать изображение)
    приводит к необработанному 500 вместо понятного JSON-ответа с ошибкой,
    хотя сам процесс загрузки фото до этого места прошёл валидно."""
    register_and_login(client, "user@example.com")

    def boom(content):
        raise ocr_module.OcrError("simulated backend failure")

    monkeypatch.setattr(main_module, "recognize_text", boom)
    client.application.config["TESTING"] = False
    client.application.config["PROPAGATE_EXCEPTIONS"] = False
    try:
        resp = upload_photo(client)
        assert resp.status_code == 500
    finally:
        client.application.config["TESTING"] = True
