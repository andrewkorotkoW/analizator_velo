import io
import os

import pytest

import app.storage as storage
from app.main import create_app

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_CSV_PATH = os.path.join(FIXTURES_DIR, "sample_workouts.csv")


def read_sample_bytes() -> bytes:
    with open(SAMPLE_CSV_PATH, "rb") as f:
        return f.read()


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Свежее Flask-приложение с изолированной БД на каждый тест."""
    db_path = tmp_path / "api_test.db"
    monkeypatch.setattr(storage, "DB_PATH", str(db_path))
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as test_client:
        yield test_client


def test_upload_valid_csv_then_visible_via_get(client):
    resp = client.post(
        "/api/workouts/upload",
        data={
            "user_email": "user@example.com",
            "file": (io.BytesIO(read_sample_bytes()), "sample_workouts.csv"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 201
    assert resp.get_json() == {"saved": 10}

    get_resp = client.get("/api/workouts", query_string={"user_email": "user@example.com"})
    assert get_resp.status_code == 200
    data = get_resp.get_json()
    assert isinstance(data, list)
    assert len(data) == 10
    assert data[0]["date"] == "2026-08-01"
    assert data[0]["distance_km"] == pytest.approx(32.5)
    assert data[0]["user_email"] == "user@example.com"


def test_upload_without_file_returns_400_not_500(client):
    resp = client.post(
        "/api/workouts/upload",
        data={"user_email": "user@example.com"},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_upload_without_user_email_returns_400_not_500(client):
    resp = client.post(
        "/api/workouts/upload",
        data={"file": (io.BytesIO(read_sample_bytes()), "sample_workouts.csv")},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_upload_with_empty_filename_treated_as_missing_file(client):
    resp = client.post(
        "/api/workouts/upload",
        data={
            "user_email": "user@example.com",
            "file": (io.BytesIO(b""), ""),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_upload_invalid_csv_returns_400_not_500(client):
    bad_csv = b"distance_km,duration_min\n1.0,2.0\n"  # нет колонки date
    resp = client.post(
        "/api/workouts/upload",
        data={
            "user_email": "user@example.com",
            "file": (io.BytesIO(bad_csv), "bad.csv"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_upload_csv_with_bad_numeric_value_returns_400_not_500(client):
    bad_csv = b"date,distance_km,duration_min\n2026-01-01,not-a-number,30\n"
    resp = client.post(
        "/api/workouts/upload",
        data={
            "user_email": "user@example.com",
            "file": (io.BytesIO(bad_csv), "bad.csv"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_upload_empty_file_returns_400_not_500(client):
    resp = client.post(
        "/api/workouts/upload",
        data={
            "user_email": "user@example.com",
            "file": (io.BytesIO(b""), "empty.csv"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_get_workouts_for_unknown_user_returns_empty_list_not_error(client):
    resp = client.get("/api/workouts", query_string={"user_email": "nobody@example.com"})

    assert resp.status_code == 200
    assert resp.get_json() == []


def test_get_workouts_without_user_email_returns_400_not_500(client):
    resp = client.get("/api/workouts")

    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_uploads_for_different_users_are_isolated_via_api(client):
    client.post(
        "/api/workouts/upload",
        data={
            "user_email": "a@example.com",
            "file": (io.BytesIO(read_sample_bytes()), "sample_workouts.csv"),
        },
        content_type="multipart/form-data",
    )

    b_resp = client.get("/api/workouts", query_string={"user_email": "b@example.com"})
    assert b_resp.status_code == 200
    assert b_resp.get_json() == []

    a_resp = client.get("/api/workouts", query_string={"user_email": "a@example.com"})
    assert len(a_resp.get_json()) == 10
