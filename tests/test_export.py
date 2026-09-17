import csv
import io
import os
import zipfile

import app.storage as storage
from app.models import Workout
from app.parser import parse_csv

from conftest import register_and_login
from test_api import SAMPLE_CSV_PATH, read_sample_csv_bytes, upload


def read_sample_csv_rows():
    with open(SAMPLE_CSV_PATH, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _user_id(email):
    return storage.get_user_by_email(email).id


def _insert_workout(email, **kwargs):
    """Вставляет тренировку напрямую через storage, минуя парсер/загрузку."""
    defaults = dict(
        user_email=email,
        date="2026-08-01",
        distance_km=10.0,
        duration_min=30.0,
        source="csv",
    )
    defaults.update(kwargs)
    workout = Workout(**defaults)
    storage.save_workouts(email, [workout], user_id=_user_id(email))


# =====================================================================
# /api/export.csv
# =====================================================================


def test_export_csv_requires_login(client):
    resp = client.get("/api/export.csv")
    assert resp.status_code == 401


def test_export_csv_for_fresh_user_is_header_only(client):
    register_and_login(client, "user@example.com")
    resp = client.get("/api/export.csv")
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.get_data(as_text=True))))
    assert rows == [
        [
            "date",
            "distance_km",
            "duration_min",
            "avg_speed_kmh",
            "avg_hr",
            "elevation_gain_m",
            "source",
        ]
    ]


def test_export_csv_contains_all_of_current_users_workouts(client):
    register_and_login(client, "user@example.com")
    upload(client, "sample_workouts.csv", read_sample_csv_bytes())

    resp = client.get("/api/export.csv")
    assert resp.status_code == 200

    rows = list(csv.DictReader(io.StringIO(resp.get_data(as_text=True))))
    assert len(rows) == 10
    dates = {row["date"] for row in rows}
    assert dates == {row["date"] for row in read_sample_csv_rows()}
    assert all(row["source"] == "csv" for row in rows)


def test_export_csv_content_disposition_is_attachment(client):
    register_and_login(client, "user@example.com")
    resp = client.get("/api/export.csv")
    assert "attachment" in resp.headers.get("Content-Disposition", "")
    assert resp.mimetype == "text/csv"


def test_export_csv_is_isolated_between_users(client):
    register_and_login(client, "a@example.com")
    upload(client, "sample_workouts.csv", read_sample_csv_bytes())
    client.get("/logout")

    register_and_login(client, "b@example.com")
    _insert_workout("b@example.com", date="2026-09-01", distance_km=5.0, duration_min=15.0)

    resp = client.get("/api/export.csv")
    rows = list(csv.DictReader(io.StringIO(resp.get_data(as_text=True))))
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-09-01"

    client.get("/logout")
    login_resp = client.post(
        "/login", data={"email": "a@example.com", "password": "Passw0rd!123"}
    )
    assert login_resp.status_code == 302
    a_resp = client.get("/api/export.csv")
    a_rows = list(csv.DictReader(io.StringIO(a_resp.get_data(as_text=True))))
    assert len(a_rows) == 10
    assert all(row["date"] != "2026-09-01" for row in a_rows)


def test_export_csv_round_trips_through_parse_csv(client):
    register_and_login(client, "user@example.com")
    upload(client, "sample_workouts.csv", read_sample_csv_bytes())

    exported_text = client.get("/api/export.csv").get_data(as_text=True)

    reparsed = parse_csv(exported_text, "reimport@example.com")

    assert len(reparsed) == 10
    original_by_date = {row["date"]: row for row in read_sample_csv_rows()}
    for workout in reparsed:
        original = original_by_date[workout.date]
        assert workout.distance_km == float(original["distance_km"])
        assert workout.duration_min == float(original["duration_min"])
        assert workout.avg_speed_kmh == float(original["avg_speed_kmh"])
        assert workout.avg_hr == float(original["avg_hr"])
        assert workout.source == "csv"


# =====================================================================
# /api/export.zip
# =====================================================================


def test_export_zip_requires_login(client):
    resp = client.get("/api/export.zip")
    assert resp.status_code == 401


def test_export_zip_for_fresh_user_is_valid_empty_archive(client):
    register_and_login(client, "user@example.com")
    resp = client.get("/api/export.zip")
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"

    archive = zipfile.ZipFile(io.BytesIO(resp.data))
    assert archive.namelist() == []
    assert archive.testzip() is None


def test_export_zip_contains_only_gpx_sourced_tracks(client):
    register_and_login(client, "user@example.com")
    email = "user@example.com"
    user_id = _user_id(email)

    gpx_content = b"<gpx>fake track content</gpx>"
    gpx_path = storage.save_gpx_track(user_id, gpx_content)

    _insert_workout(email, date="2026-08-01", source="csv", gpx_path=None)
    _insert_workout(email, date="2026-08-02", source="fit", gpx_path=None)
    _insert_workout(email, date="2026-08-03", source="photo", photo_path="p.jpg", gpx_path=None)
    _insert_workout(email, date="2026-08-04", source="gpx", gpx_path=gpx_path)

    resp = client.get("/api/export.zip")
    archive = zipfile.ZipFile(io.BytesIO(resp.data))
    names = archive.namelist()

    assert len(names) == 1
    assert names[0].startswith("2026-08-04_")
    assert archive.read(names[0]) == gpx_content


def test_export_zip_skips_gpx_workout_with_missing_file_on_disk(client):
    register_and_login(client, "user@example.com")
    email = "user@example.com"

    missing_path = os.path.join(storage.TRACKS_DIR, "does-not-exist.gpx")
    _insert_workout(email, date="2026-08-05", source="gpx", gpx_path=missing_path)

    resp = client.get("/api/export.zip")
    archive = zipfile.ZipFile(io.BytesIO(resp.data))
    assert archive.namelist() == []


def test_export_zip_is_isolated_between_users(client):
    register_and_login(client, "a@example.com")
    a_gpx_path = storage.save_gpx_track(_user_id("a@example.com"), b"track A")
    _insert_workout("a@example.com", date="2026-08-01", source="gpx", gpx_path=a_gpx_path)
    client.get("/logout")

    register_and_login(client, "b@example.com")
    resp = client.get("/api/export.zip")
    archive = zipfile.ZipFile(io.BytesIO(resp.data))
    assert archive.namelist() == []
