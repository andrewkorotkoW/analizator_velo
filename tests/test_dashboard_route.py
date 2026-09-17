import pytest

import app.storage as storage
from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "dashboard_route_test.db"
    monkeypatch.setattr(storage, "DB_PATH", str(db_path))
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as test_client:
        yield test_client


def test_dashboard_route_returns_200_html(client):
    resp = client.get("/")

    assert resp.status_code == 200
    assert "text/html" in resp.content_type


def test_dashboard_html_contains_upload_form_with_required_fields(client):
    resp = client.get("/")
    body = resp.get_data(as_text=True)

    assert '<form id="uploadForm">' in body
    assert 'name="user_email"' in body
    assert 'type="email"' in body
    assert 'name="file"' in body
    assert 'type="file"' in body
    assert 'accept=".csv"' in body


def test_dashboard_html_contains_submit_button(client):
    resp = client.get("/")
    body = resp.get_data(as_text=True)

    assert '<button type="submit" id="submitBtn">' in body
    assert "Загрузить" in body


def test_dashboard_html_contains_chart_and_recommendation_placeholders(client):
    resp = client.get("/")
    body = resp.get_data(as_text=True)

    assert 'id="progressChart"' in body
    assert 'id="recommendationBox"' in body
    assert 'id="emptyState"' in body


def test_dashboard_route_does_not_depend_on_query_params(client):
    resp = client.get("/", query_string={"user_email": "someone@example.com"})

    assert resp.status_code == 200
    assert '<form id="uploadForm">' in resp.get_data(as_text=True)
