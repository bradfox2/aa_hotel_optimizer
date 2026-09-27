from urllib.parse import urlparse

import pytest
import requests

from aa_hotel_optimizer.service import security
from aa_hotel_optimizer.service.config import Settings


def test_resend_delivers_single_use_link_without_browser_shortcut(client, app, monkeypatch):
    app.state.config.resend_api_key = "re_fixture"
    app.state.config.email_from = "LP Optimizer <login@example.com>"
    sent = []

    def send(url, **kwargs):
        assert url == "https://api.resend.com/emails"
        assert kwargs["headers"]["Authorization"] == "Bearer re_fixture"
        sent.append(kwargs["json"])
        return requests.Response()

    def delivered(url, **kwargs):
        response = send(url, **kwargs)
        response.status_code = 200
        return response

    monkeypatch.setattr(security.requests, "post", delivered)
    result = client.post("/v1/auth/link", json={"email": "traveler@example.com"})
    assert result.status_code == 200 and "development_link" not in result.json()
    assert sent[0]["to"] == ["traveler@example.com"]
    link = next(line for line in sent[0]["text"].splitlines() if line.startswith("http"))
    token = urlparse(link).fragment.removeprefix("login=")
    assert link in sent[0]["html"]
    assert client.post("/v1/auth/consume", json={"token": token}).status_code == 200
    assert client.post("/v1/auth/consume", json={"token": token}).status_code == 401


def test_email_failure_is_redacted_and_beta_is_enforced(client, app, monkeypatch):
    config = app.state.config
    config.resend_api_key = "re_fixture"
    config.email_from = "login@example.com"
    config.beta_emails = "traveler@example.com"
    assert client.post("/v1/auth/link", json={"email": "stranger@example.com"}).status_code == 403

    def unavailable(*args, **kwargs):
        raise requests.HTTPError("Do not reveal re_fixture or provider internals")

    monkeypatch.setattr(security.requests, "post", unavailable)
    result = client.post("/v1/auth/link", json={"email": "traveler@example.com"})
    assert result.status_code == 503
    assert "re_fixture" not in result.text


def test_staging_never_returns_a_development_sign_in_link(client, app):
    app.state.config.environment = "staging"
    result = client.post("/v1/auth/link", json={"email": "traveler@example.com"})
    assert result.status_code == 503 and "development_link" not in result.json()


def test_hosted_configuration_accepts_managed_postgres_and_requires_https():
    config = Settings(
        _env_file=None,
        environment="staging",
        public_url="https://beta.example.com",
        database_url="postgres://user:password@db/test",
    )
    config.validate_deployment()
    assert config.database_url.startswith("postgresql+psycopg://")
    config.environment = "production"
    with pytest.raises(ValueError, match="email delivery"):
        config.validate_deployment()
    config.email_from = "login@example.com"
    config.resend_api_key = "re_fixture"
    config.validate_deployment()
    config.public_url = "http://beta.example.com"
    with pytest.raises(ValueError, match="HTTPS"):
        config.validate_deployment()
