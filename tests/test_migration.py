import io

import app.storage as storage
from app.models import Workout
from conftest import login, register

CSV_ONE_ROW = b"date,distance_km,duration_min\n2026-01-01,10,30\n"


def upload_csv(client, content=CSV_ONE_ROW, filename="w.csv"):
    return client.post(
        "/api/workouts/upload",
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )


def seed_legacy_workout(email, date="2025-05-01", distance_km=42.0):
    """Создаёт «историческую» тренировку без user_id — как до появления аутентификации."""
    workout = Workout(
        user_email=email,
        date=date,
        distance_km=distance_km,
        duration_min=90.0,
        avg_speed_kmh=28.0,
        avg_hr=145.0,
        source="csv",
    )
    storage.save_workouts(email, [workout], user_id=None)


def test_registering_with_email_that_has_legacy_workouts_makes_them_visible(client):
    seed_legacy_workout("legacy@example.com")

    resp = register(client, "legacy@example.com")
    assert resp.status_code == 302

    workouts = client.get("/api/workouts").get_json()
    assert len(workouts) == 1
    assert workouts[0]["distance_km"] == 42.0


def test_login_hint_offered_when_legacy_email_has_no_account_yet(client):
    seed_legacy_workout("legacy@example.com")

    resp = login(client, "legacy@example.com", password="whatever123")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "зарегистрируйтесь" in body.lower()


def test_login_with_existing_account_also_migrates_legacy_workouts(client):
    # Пользователь уже зарегистрирован, но исторические тренировки появились позже
    # (например, повторная загрузка с тем же email до входа в систему где-то ещё).
    register(client, "user@example.com")
    client.get("/logout")

    seed_legacy_workout("user@example.com")

    resp = login(client, "user@example.com")
    assert resp.status_code == 302

    workouts = client.get("/api/workouts").get_json()
    assert len(workouts) == 1


def test_legacy_workouts_are_only_migrated_to_the_matching_email_account(client):
    seed_legacy_workout("owner@example.com")

    register(client, "other@example.com")

    workouts = client.get("/api/workouts").get_json()
    assert workouts == []


def test_migration_does_not_duplicate_already_migrated_workouts_on_repeated_login(client):
    seed_legacy_workout("legacy@example.com")
    register(client, "legacy@example.com")
    client.get("/logout")

    login(client, "legacy@example.com")
    login(client, "legacy@example.com")

    workouts = client.get("/api/workouts").get_json()
    assert len(workouts) == 1


def test_legacy_workouts_combine_with_newly_uploaded_ones_after_registration(client):
    seed_legacy_workout("legacy@example.com", date="2025-05-01", distance_km=42.0)

    register(client, "legacy@example.com")
    upload_csv(client)

    workouts = client.get("/api/workouts").get_json()
    assert len(workouts) == 2
