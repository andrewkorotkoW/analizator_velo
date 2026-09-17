import io
import os

import pytest

from conftest import login, register_and_login

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_CSV_PATH = os.path.join(FIXTURES_DIR, "sample_workouts.csv")

NOT_ENOUGH_TEXT = "Недостаточно данных для рекомендаций — загрузите больше тренировок (минимум 4)."


def read_sample_bytes() -> bytes:
    with open(SAMPLE_CSV_PATH, "rb") as f:
        return f.read()


def upload_csv(client, csv_bytes, filename="workouts.csv"):
    return client.post(
        "/api/workouts/upload",
        data={"file": (io.BytesIO(csv_bytes), filename)},
        content_type="multipart/form-data",
    )


def test_recommendations_requires_login(client):
    resp = client.get("/api/recommendations")
    assert resp.status_code == 401


def test_recommendations_response_shape(client):
    register_and_login(client, "user@example.com")

    resp = client.get("/api/recommendations")

    assert resp.status_code == 200
    data = resp.get_json()
    assert set(data.keys()) == {"recommendations", "weekly", "hr_zones"}
    assert isinstance(data["recommendations"], list)
    assert isinstance(data["weekly"], dict)
    assert isinstance(data["hr_zones"], dict)


def test_recommendations_for_user_without_any_data_returns_not_enough_message(client):
    register_and_login(client, "user@example.com")

    resp = client.get("/api/recommendations")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["recommendations"] == [NOT_ENOUGH_TEXT]


def test_recommendations_with_single_workout_returns_not_enough_message(client):
    register_and_login(client, "solo@example.com")
    one_row_csv = b"date,distance_km,duration_min,avg_speed_kmh,avg_hr\n2026-01-01,10.0,30,20.0,140\n"
    upload_resp = upload_csv(client, one_row_csv)
    assert upload_resp.status_code == 201
    assert upload_resp.get_json()["saved"] == 1

    resp = client.get("/api/recommendations")

    assert resp.status_code == 200
    assert resp.get_json()["recommendations"] == [NOT_ENOUGH_TEXT]


def test_recommendations_with_full_fixture_history_returns_multiple_items(client):
    register_and_login(client, "full@example.com")
    upload_resp = upload_csv(client, read_sample_bytes())
    assert upload_resp.status_code == 201
    assert upload_resp.get_json()["saved"] == 10

    resp = client.get("/api/recommendations")

    assert resp.status_code == 200
    data = resp.get_json()
    assert 2 <= len(data["recommendations"]) <= 4
    assert all(isinstance(item, str) for item in data["recommendations"])


def test_recommendations_are_isolated_per_user(client):
    register_and_login(client, "a@example.com")
    upload_csv(client, read_sample_bytes())
    client.get("/logout")

    register_and_login(client, "b@example.com")
    resp_b = client.get("/api/recommendations")
    assert resp_b.get_json()["recommendations"] == [NOT_ENOUGH_TEXT]

    client.get("/logout")
    login(client, "a@example.com")
    resp_a = client.get("/api/recommendations")
    assert resp_a.get_json()["recommendations"] != [NOT_ENOUGH_TEXT]


def test_recommendations_use_profile_max_hr_for_hr_zones(client):
    register_and_login(client, "user@example.com", max_hr=200)
    csv_with_hr = (
        "date,distance_km,duration_min,avg_speed_kmh,avg_hr\n"
        "2026-01-01,10,30,20,150\n"
        "2026-01-02,10,30,20,150\n"
        "2026-01-03,10,30,20,150\n"
        "2026-01-04,10,30,20,150\n"
    ).encode("utf-8")
    upload_csv(client, csv_with_hr)

    resp = client.get("/api/recommendations")
    data = resp.get_json()

    # max_hr=200 -> ratio 150/200=0.75 -> зона Z3 (0.70-0.80)
    assert data["hr_zones"]["Z3"]["count"] == 4


def test_recommendations_weekly_field_has_expected_keys(client):
    register_and_login(client, "user@example.com")
    upload_csv(client, read_sample_bytes())

    resp = client.get("/api/recommendations")
    weekly = resp.get_json()["weekly"]

    assert set(weekly.keys()) == {
        "week_start",
        "week_end",
        "distance_km",
        "duration_hours",
        "count",
        "previous_avg_distance_km",
        "change_pct",
    }
