import json

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import ApiAuthenticationError, ApiKeyAuthenticator


def test_authenticator_maps_secret_to_non_secret_client_id():
    auth = ApiKeyAuthenticator(True, {"partner-a": "secret-a"})
    assert auth.authenticate("secret-a").client_id == "partner-a"


@pytest.mark.parametrize("key", [None, "", "wrong", "secret-a "])
def test_authenticator_rejects_missing_or_wrong_key(key):
    auth = ApiKeyAuthenticator(True, {"partner-a": "secret-a"})
    with pytest.raises(ApiAuthenticationError) as info:
        auth.authenticate(key)
    assert info.value.code == "invalid_api_key"
    assert "secret-a" not in info.value.message


def test_disabled_authentication_uses_anonymous_identity():
    assert ApiKeyAuthenticator(False, {}).authenticate(None).client_id == "anonymous"


def test_live_mode_requires_inbound_authentication():
    with pytest.raises(ValidationError, match="API_AUTH_ENABLED"):
        Settings(_env_file=None, jev_mode="live", typesafe_api_key="provider-key")


def test_enabled_authentication_requires_keys():
    with pytest.raises(ValidationError, match="CLIENT_API_KEYS"):
        Settings(_env_file=None, api_auth_enabled=True, client_api_keys=None)


def test_client_key_format_and_duplicates_are_validated():
    with pytest.raises(ValidationError, match="client-id:secret"):
        Settings(_env_file=None, api_auth_enabled=True, client_api_keys="malformed")
    with pytest.raises(ValidationError, match="duplicate client ID"):
        Settings(_env_file=None, api_auth_enabled=True, client_api_keys="a:one,a:two")
    with pytest.raises(ValidationError, match="duplicate client secret"):
        Settings(_env_file=None, api_auth_enabled=True, client_api_keys="a:same,b:same")


def test_api_routes_require_key_when_enabled_but_health_stays_public(client):
    client.app.state.authenticator = ApiKeyAuthenticator(True, {"partner-a": "secret-a"})

    assert client.get("/health").status_code == 200

    missing = client.get("/api/v1/policy")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "invalid_api_key"
    assert missing.headers["www-authenticate"] == "ApiKey"

    assert client.get("/api/v1/policy", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/v1/analytics/summary").status_code == 401
    assert client.get("/api/v1/policy", headers={"X-API-Key": "secret-a"}).status_code == 200


def test_openapi_describes_api_key_security(client):
    schema = client.get("/openapi.json").json()
    schemes = schema["components"]["securitySchemes"]
    assert any(value.get("name") == "X-API-Key" for value in schemes.values())
    assert schema["paths"]["/api/v1/triage"]["post"]["security"]


def test_disabled_authentication_ignores_unused_client_key_text():
    settings = Settings(
        _env_file=None,
        jev_mode="mock",
        api_auth_enabled=False,
        client_api_keys="not-in-client-id-secret-format",
    )
    assert settings.api_auth_enabled is False
