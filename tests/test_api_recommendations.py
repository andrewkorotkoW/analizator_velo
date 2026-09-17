import io
import os

import pytest

import app.storage as storage
from app.main import create_app

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_CSV_PATH = os.path.join(FIXTURES_DIR, "sample_workouts.csv")

NOT_ENOUGH_TEXT = "Недостаточно данных для рекомендаций — загрузите больше тренировок (минимум 4)."
GROWING_TEXT = (
    "Прогресс растёт: средняя дистанция за последние тренировки увеличилась — "
    "можно постепенно увеличивать нагрузку."
)


def read_sample_bytes() -> bytes:
    with open(SAMPLE_CSV_PATH, "rb") as f:
        return f.read()


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Свежее Flask-приложение с изолированной БД на каждый тест."""
    db_path = tmp_path / "api_recommendations_test.db"
    monkeypatch.setattr(storage, "DB_PATH", str(db_path))
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as test_client:
        yield test_client


def upload_csv(client, user_email, csv_bytes, filename="workouts.csv"):
    return client.post(
        "/api/workouts/upload",
        data={
            "user_email": user_email,
            "file": (io.BytesIO(csv_bytes), filename),
        },
        content_type="multipart/form-data",
    )


def test_recommendations_for_user_without_any_data_returns_not_enough_message(client):
    resp = client.get(
        "/api/recommendations", query_string={"user_email": "nobody@example.com"}
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert set(data.keys()) == {"recommendation"}
    assert data["recommendation"] == NOT_ENOUGH_TEXT


def test_recommendations_missing_user_email_returns_400(client):
    resp = client.get("/api/recommendations")

    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_recommendations_with_single_workout_returns_not_enough_message(client):
    one_row_csv = b"date,distance_km,duration_min,avg_speed_kmh,avg_hr\n2026-01-01,10.0,30,20.0,140\n"
    upload_resp = upload_csv(client, "solo@example.com", one_row_csv)
    assert upload_resp.status_code == 201
    assert upload_resp.get_json() == {"saved": 1}

    resp = client.get(
        "/api/recommendations", query_string={"user_email": "solo@example.com"}
    )

    assert resp.status_code == 200
    assert resp.get_json() == {"recommendation": NOT_ENOUGH_TEXT}


def test_recommendations_with_full_fixture_history_returns_growth_recommendation(client):
    upload_resp = upload_csv(client, "full@example.com", read_sample_bytes())
    assert upload_resp.status_code == 201
    assert upload_resp.get_json() == {"saved": 10}

    resp = client.get(
        "/api/recommendations", query_string={"user_email": "full@example.com"}
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, dict)
    assert set(data.keys()) == {"recommendation"}
    assert isinstance(data["recommendation"], str)
    assert data["recommendation"] == GROWING_TEXT


def test_recommendations_are_isolated_per_user(client):
    upload_csv(client, "a@example.com", read_sample_bytes())

    resp_a = client.get("/api/recommendations", query_string={"user_email": "a@example.com"})
    resp_b = client.get("/api/recommendations", query_string={"user_email": "b@example.com"})

    assert resp_a.get_json()["recommendation"] == GROWING_TEXT
    assert resp_b.get_json()["recommendation"] == NOT_ENOUGH_TEXT
