from conftest import register_and_login


def test_dashboard_route_redirects_to_login_when_not_authenticated(client):
    resp = client.get("/")

    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_dashboard_route_returns_200_html_when_logged_in(client):
    register_and_login(client, "user@example.com")

    resp = client.get("/")

    assert resp.status_code == 200
    assert "text/html" in resp.content_type


def test_dashboard_html_contains_upload_form_with_required_fields(client):
    register_and_login(client, "user@example.com")

    resp = client.get("/")
    body = resp.get_data(as_text=True)

    assert '<form id="uploadForm">' in body
    assert 'name="file"' in body
    assert 'type="file"' in body
    assert 'accept=".csv,.gpx,.fit,.zip"' in body


def test_dashboard_html_contains_submit_button(client):
    register_and_login(client, "user@example.com")

    resp = client.get("/")
    body = resp.get_data(as_text=True)

    assert '<button type="submit" id="submitBtn">' in body
    assert "Загрузить" in body


def test_dashboard_html_contains_chart_and_recommendation_placeholders(client):
    register_and_login(client, "user@example.com")

    resp = client.get("/")
    body = resp.get_data(as_text=True)

    assert 'id="progressChart"' in body
    assert 'id="recommendationBox"' in body
    assert 'id="emptyState"' in body


def test_dashboard_html_shows_current_users_email_in_nav(client):
    register_and_login(client, "user@example.com")

    resp = client.get("/")
    body = resp.get_data(as_text=True)

    assert "user@example.com" in body
