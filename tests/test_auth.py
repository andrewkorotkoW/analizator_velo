import io

from conftest import login, register, register_and_login

CSV_ONE_ROW = b"date,distance_km,duration_min\n2026-01-01,10,30\n"


def upload_csv(client, content=CSV_ONE_ROW, filename="w.csv"):
    return client.post(
        "/api/workouts/upload",
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )


# =====================================================================
# Доступ без входа
# =====================================================================


def test_dashboard_without_login_redirects_to_login(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_profile_without_login_redirects_to_login(client):
    resp = client.get("/profile")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_get_workouts_without_login_returns_401_json(client):
    resp = client.get("/api/workouts")
    assert resp.status_code == 401
    assert "error" in resp.get_json()


def test_upload_without_login_returns_401_json(client):
    resp = upload_csv(client)
    assert resp.status_code == 401
    assert "error" in resp.get_json()


def test_delete_workout_without_login_returns_401_json(client):
    resp = client.delete("/api/workouts/1")
    assert resp.status_code == 401
    assert "error" in resp.get_json()


def test_recommendations_without_login_returns_401_json(client):
    resp = client.get("/api/recommendations")
    assert resp.status_code == 401
    assert "error" in resp.get_json()


def test_login_and_register_pages_accessible_without_login(client):
    assert client.get("/login").status_code == 200
    assert client.get("/register").status_code == 200


# =====================================================================
# Регистрация
# =====================================================================


def test_register_success_autologs_in_and_redirects_to_dashboard(client):
    resp = register(client, "new@example.com")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")

    dashboard_resp = client.get("/")
    assert dashboard_resp.status_code == 200


def test_register_with_mismatched_passwords_shows_error_not_500(client):
    resp = register(client, "new@example.com", password="Abc12345", password2="different")
    assert resp.status_code == 200
    assert "Пароли не совпадают" in resp.get_data(as_text=True)


def test_register_missing_email_or_password_shows_error_not_500(client):
    resp = client.post("/register", data={"email": "", "password": "", "password2": ""})
    assert resp.status_code == 200
    assert "Укажите email и пароль" in resp.get_data(as_text=True)


def test_register_duplicate_email_shows_error_not_500(client):
    register(client, "dup@example.com")
    client.get("/logout")

    resp = register(client, "dup@example.com")
    assert resp.status_code == 200
    assert "уже зарегистрирован" in resp.get_data(as_text=True)


def test_register_with_profile_fields_persists_them(client):
    register(client, "profiled@example.com", name="Anna", age="30", max_hr="195", weight="61.5")

    resp = client.get("/profile")
    body = resp.get_data(as_text=True)
    assert "Anna" in body


# =====================================================================
# Вход
# =====================================================================


def test_login_success_redirects_to_dashboard(client):
    register(client, "user@example.com")
    client.get("/logout")

    resp = login(client, "user@example.com")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_login_wrong_password_shows_error_not_500(client):
    register(client, "user@example.com")
    client.get("/logout")

    resp = login(client, "user@example.com", password="totally-wrong")
    assert resp.status_code == 200
    assert "Неверный email или пароль" in resp.get_data(as_text=True)


def test_login_unknown_email_shows_error_not_500(client):
    resp = login(client, "nobody@example.com", password="whatever123")
    assert resp.status_code == 200
    assert "Неверный email или пароль" in resp.get_data(as_text=True)


def test_login_does_not_grant_access_before_successful_auth(client):
    register(client, "user@example.com")
    client.get("/logout")
    login(client, "user@example.com", password="wrong-one")

    resp = client.get("/api/workouts")
    assert resp.status_code == 401


def test_logout_clears_session(client):
    register_and_login(client, "user@example.com")
    client.get("/logout")

    resp = client.get("/api/workouts")
    assert resp.status_code == 401


# =====================================================================
# Изоляция между пользователями
# =====================================================================


def test_other_users_workouts_are_not_visible_on_read(client):
    register_and_login(client, "a@example.com")
    upload_csv(client)
    client.get("/logout")

    register_and_login(client, "b@example.com")
    resp = client.get("/api/workouts")
    assert resp.get_json() == []


def test_other_users_workout_cannot_be_deleted(client):
    register_and_login(client, "a@example.com")
    upload_csv(client)
    workout_id = client.get("/api/workouts").get_json()[0]["id"]
    client.get("/logout")

    register_and_login(client, "b@example.com")
    resp = client.delete(f"/api/workouts/{workout_id}")
    assert resp.status_code == 404

    client.get("/logout")
    login(client, "a@example.com")
    assert len(client.get("/api/workouts").get_json()) == 1


def test_profile_page_shows_only_own_email(client):
    register_and_login(client, "a@example.com")
    resp = client.get("/profile")
    assert "a@example.com" in resp.get_data(as_text=True)
    client.get("/logout")

    register_and_login(client, "b@example.com")
    resp = client.get("/profile")
    body = resp.get_data(as_text=True)
    assert "b@example.com" in body
    assert "a@example.com" not in body


# =====================================================================
# DELETE /api/workouts/<id>
# =====================================================================


def test_delete_own_workout_succeeds(client):
    register_and_login(client, "user@example.com")
    upload_csv(client)
    workout_id = client.get("/api/workouts").get_json()[0]["id"]

    resp = client.delete(f"/api/workouts/{workout_id}")
    assert resp.status_code == 200
    assert resp.get_json()["deleted"] is True


def test_delete_nonexistent_workout_returns_404(client):
    register_and_login(client, "user@example.com")
    resp = client.delete("/api/workouts/424242")
    assert resp.status_code == 404
