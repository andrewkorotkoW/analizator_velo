import os
import tempfile

# Устанавливаем ANAL_VELO_DB_PATH ДО того, как что-либо в тестовой сессии
# впервые импортирует app.storage / app.main. app.main создаёт модуль-уровневый
# `app = create_app()` при импорте, что вызывает init_db() и коснётся файла
# по умолчанию (data.db в корне репозитория), если не перенаправить путь заранее.
_SESSION_TMP_DIR = tempfile.mkdtemp(prefix="anal_velo_test_")
os.environ.setdefault(
    "ANAL_VELO_DB_PATH", os.path.join(_SESSION_TMP_DIR, "session_default.db")
)

import pytest

import app.storage as storage
from app.main import create_app

DEFAULT_PASSWORD = "Passw0rd!123"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Свежее Flask-приложение с изолированной БД на каждый тест."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(storage, "DB_PATH", str(db_path))
    monkeypatch.setattr(storage, "TRACKS_DIR", str(tmp_path / "tracks"))
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as test_client:
        yield test_client


def register(client, email, password=DEFAULT_PASSWORD, password2=None, **profile):
    """POST /register. profile может содержать name/age/max_hr/weight."""
    data = {
        "email": email,
        "password": password,
        "password2": password2 if password2 is not None else password,
    }
    for key, value in profile.items():
        if value is not None:
            data[key] = str(value)
    return client.post("/register", data=data)


def login(client, email, password=DEFAULT_PASSWORD):
    return client.post("/login", data={"email": email, "password": password})


def register_and_login(client, email, password=DEFAULT_PASSWORD, **profile):
    """Регистрирует нового пользователя (register уже авто-логинит) и возвращает email."""
    resp = register(client, email, password=password, **profile)
    assert resp.status_code == 302, resp.get_data(as_text=True)
    return email
