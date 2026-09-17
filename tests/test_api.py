import io
import os
import zipfile

import pytest
from werkzeug.datastructures import MultiDict

from conftest import login, register, register_and_login

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_CSV_PATH = os.path.join(FIXTURES_DIR, "sample_workouts.csv")
SAMPLE_GPX_PATH = os.path.join(FIXTURES_DIR, "sample_track.gpx")


def read_sample_csv_bytes() -> bytes:
    with open(SAMPLE_CSV_PATH, "rb") as f:
        return f.read()


def read_sample_gpx_bytes() -> bytes:
    with open(SAMPLE_GPX_PATH, "rb") as f:
        return f.read()


def upload(client, filename, content, extra_files=None):
    if extra_files:
        # Несколько файлов под одним полем "file" — нужен MultiDict, иначе
        # werkzeug/Flask воспринимают data как обычный dict с одним значением на ключ.
        data = MultiDict()
        data.add("file", (io.BytesIO(content), filename))
        for fname, fcontent in extra_files:
            data.add("file", (io.BytesIO(fcontent), fname))
        return client.post("/api/workouts/upload", data=data, content_type="multipart/form-data")
    files = {"file": (io.BytesIO(content), filename)}
    return client.post("/api/workouts/upload", data=files, content_type="multipart/form-data")


def make_zip(members: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


# =====================================================================
# upload — CSV / GPX
# =====================================================================


def test_upload_valid_csv_then_visible_via_get(client):
    register_and_login(client, "user@example.com")

    resp = upload(client, "sample_workouts.csv", read_sample_csv_bytes())

    assert resp.status_code == 201
    data = resp.get_json()
    assert data["saved"] == 10
    assert data["duplicates"] == 0
    assert data["errors"] == []

    get_resp = client.get("/api/workouts")
    assert get_resp.status_code == 200
    workouts = get_resp.get_json()
    assert len(workouts) == 10
    assert workouts[0]["date"] == "2026-08-01"
    assert workouts[0]["distance_km"] == pytest.approx(32.5)
    assert workouts[0]["source"] == "csv"


def test_upload_valid_gpx_then_visible_via_get(client):
    register_and_login(client, "user@example.com")

    resp = upload(client, "track.gpx", read_sample_gpx_bytes())

    assert resp.status_code == 201
    data = resp.get_json()
    assert data["saved"] == 1
    assert data["errors"] == []

    get_resp = client.get("/api/workouts")
    workouts = get_resp.get_json()
    assert len(workouts) == 1
    assert workouts[0]["source"] == "gpx"
    assert workouts[0]["date"] == "2026-08-01"


def test_upload_without_file_returns_400_not_500(client):
    register_and_login(client, "user@example.com")

    resp = client.post("/api/workouts/upload", data={}, content_type="multipart/form-data")

    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_upload_with_empty_filename_treated_as_missing_file(client):
    register_and_login(client, "user@example.com")

    resp = upload(client, "", b"")

    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_upload_invalid_csv_returns_400_with_errors_list(client):
    register_and_login(client, "user@example.com")
    bad_csv = b"distance_km,duration_min\n1.0,2.0\n"  # нет колонки date

    resp = upload(client, "bad.csv", bad_csv)

    assert resp.status_code == 400
    data = resp.get_json()
    assert "errors" in data
    assert data["errors"][0]["filename"] == "bad.csv"


def test_upload_empty_file_returns_400_not_500(client):
    register_and_login(client, "user@example.com")

    resp = upload(client, "empty.csv", b"")

    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_upload_requires_login(client):
    resp = upload(client, "sample_workouts.csv", read_sample_csv_bytes())
    assert resp.status_code == 401


# =====================================================================
# upload — несколько файлов / zip
# =====================================================================


def test_upload_multiple_files_in_one_request_sums_saved(client):
    register_and_login(client, "user@example.com")
    csv_a = b"date,distance_km,duration_min\n2026-01-01,10,30\n"
    csv_b = b"date,distance_km,duration_min\n2026-01-02,20,40\n"

    resp = upload(client, "a.csv", csv_a, extra_files=[("b.csv", csv_b)])

    assert resp.status_code == 201
    data = resp.get_json()
    assert data["saved"] == 2
    assert data["errors"] == []


def test_upload_multiple_files_partial_failure_still_saves_the_good_ones(client):
    register_and_login(client, "user@example.com")
    good_csv = b"date,distance_km,duration_min\n2026-01-01,10,30\n"
    bad_csv = b"distance_km,duration_min\n1.0,2.0\n"  # без date

    resp = upload(client, "good.csv", good_csv, extra_files=[("bad.csv", bad_csv)])

    assert resp.status_code == 201
    data = resp.get_json()
    assert data["saved"] == 1
    assert len(data["errors"]) == 1
    assert data["errors"][0]["filename"] == "bad.csv"


def test_upload_zip_with_multiple_csv_members_saves_all(client):
    register_and_login(client, "user@example.com")
    zip_bytes = make_zip(
        {
            "a.csv": "date,distance_km,duration_min\n2026-01-01,10,30\n",
            "b.csv": "date,distance_km,duration_min\n2026-01-02,20,40\n",
        }
    )

    resp = upload(client, "bundle.zip", zip_bytes)

    assert resp.status_code == 201
    data = resp.get_json()
    assert data["saved"] == 2
    assert data["errors"] == []


def test_upload_zip_with_one_bad_member_reports_error_but_saves_good_ones(client):
    register_and_login(client, "user@example.com")
    zip_bytes = make_zip(
        {
            "good.csv": "date,distance_km,duration_min\n2026-01-01,10,30\n",
            "bad.csv": "distance_km,duration_min\n1.0,2.0\n",
        }
    )

    resp = upload(client, "bundle.zip", zip_bytes)

    assert resp.status_code == 201
    data = resp.get_json()
    assert data["saved"] == 1
    assert any(e["filename"] == "bad.csv" for e in data["errors"])


def test_upload_corrupted_zip_returns_400_with_error(client):
    register_and_login(client, "user@example.com")

    resp = upload(client, "bundle.zip", b"not a real zip file")

    assert resp.status_code == 400
    data = resp.get_json()
    assert "errors" in data
    assert data["errors"][0]["filename"] == "bundle.zip"


def test_upload_zip_with_only_bad_members_returns_400(client):
    register_and_login(client, "user@example.com")
    zip_bytes = make_zip({"bad.csv": "distance_km,duration_min\n1.0,2.0\n"})

    resp = upload(client, "bundle.zip", zip_bytes)

    assert resp.status_code == 400
    data = resp.get_json()
    assert "errors" in data


# =====================================================================
# дедупликация через API
# =====================================================================


def test_reuploading_same_csv_reports_all_as_duplicates(client):
    register_and_login(client, "user@example.com")
    upload(client, "sample_workouts.csv", read_sample_csv_bytes())

    resp = upload(client, "sample_workouts.csv", read_sample_csv_bytes())

    assert resp.status_code == 201
    data = resp.get_json()
    assert data["saved"] == 0
    assert data["duplicates"] == 10

    get_resp = client.get("/api/workouts")
    assert len(get_resp.get_json()) == 10


# =====================================================================
# GET /api/workouts
# =====================================================================


def test_get_workouts_requires_login(client):
    resp = client.get("/api/workouts")
    assert resp.status_code == 401


def test_get_workouts_for_fresh_user_returns_empty_list(client):
    register_and_login(client, "user@example.com")
    resp = client.get("/api/workouts")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_uploads_for_different_users_are_isolated_via_api(client):
    register_and_login(client, "a@example.com")
    upload(client, "sample_workouts.csv", read_sample_csv_bytes())
    client.get("/logout")

    register_and_login(client, "b@example.com")
    b_resp = client.get("/api/workouts")
    assert b_resp.get_json() == []

    client.get("/logout")
    login(client, "a@example.com")
    a_resp = client.get("/api/workouts")
    assert len(a_resp.get_json()) == 10


# =====================================================================
# DELETE /api/workouts/<id>
# =====================================================================


def test_delete_own_workout_returns_200_and_removes_it(client):
    register_and_login(client, "user@example.com")
    upload(client, "sample_workouts.csv", read_sample_csv_bytes())
    workout_id = client.get("/api/workouts").get_json()[0]["id"]

    resp = client.delete(f"/api/workouts/{workout_id}")

    assert resp.status_code == 200
    assert resp.get_json() == {"deleted": True}
    assert len(client.get("/api/workouts").get_json()) == 9


def test_delete_unknown_workout_returns_404(client):
    register_and_login(client, "user@example.com")
    resp = client.delete("/api/workouts/999999")
    assert resp.status_code == 404


def test_delete_requires_login(client):
    resp = client.delete("/api/workouts/1")
    assert resp.status_code == 401


def test_cannot_delete_another_users_workout(client):
    register_and_login(client, "a@example.com")
    upload(client, "sample_workouts.csv", read_sample_csv_bytes())
    workout_id = client.get("/api/workouts").get_json()[0]["id"]
    client.get("/logout")

    register_and_login(client, "b@example.com")
    resp = client.delete(f"/api/workouts/{workout_id}")

    assert resp.status_code == 404

    client.get("/logout")
    login(client, "a@example.com")
    assert len(client.get("/api/workouts").get_json()) == 10
