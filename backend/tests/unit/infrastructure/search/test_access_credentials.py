"""Public DB-only configuration cannot manufacture an ES capability."""

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from ai_workshop.config import Settings
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch


def public_settings(**changes):
    return Settings(
        _env_file=None,
        secret_key="x" * 32,
        **{
            "elasticsearch_url": "https://localhost:9200",
            "elasticsearch_ca_certs": Path("public-ca.pem"),
            "elasticsearch_access_epoch_id": uuid4(),
            "elasticsearch_access_epoch": 1,
            **changes,
        },
    )


def test_public_settings_can_load_without_key_but_cannot_create_es_client():
    settings = public_settings()
    assert settings.elasticsearch_api_key is None
    with pytest.raises(ValueError, match="elasticsearch_capability_required"):
        create_elasticsearch(settings)


@pytest.mark.parametrize(
    "changes",
    [
        {"elasticsearch_url": "http://localhost:9200"},
        {"elasticsearch_ca_certs": None},
        {"elasticsearch_access_epoch": True},
        {"elasticsearch_access_epoch": 0},
        {"elasticsearch_access_epoch_id": None},
        {"elasticsearch_role": "writer"},
        {"elasticsearch_api_key": SecretStr("temporary")},
        {"elasticsearch_url": "https://user:password@localhost:9200"},
    ],
)
def test_partial_or_insecure_secure_settings_refuse(changes):
    with pytest.raises(ValidationError):
        public_settings(**changes)


async def test_factory_captures_one_key_with_explicit_ca_and_no_fallback(monkeypatch):
    import ssl

    import ai_workshop.infrastructure.search.elasticsearch as factory

    captured = []
    loaded_ca = []
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    monkeypatch.setattr(
        factory.ssl, "create_default_context", lambda *, cafile: loaded_ca.append(cafile) or context
    )
    monkeypatch.setattr(factory, "AsyncElasticsearch", lambda **kw: captured.append(kw) or kw)
    secret = uuid4().hex
    settings = public_settings(elasticsearch_role="reader", elasticsearch_api_key=SecretStr(secret))
    create_elasticsearch(settings)
    settings.elasticsearch_api_key = SecretStr(uuid4().hex)
    assert captured[0]["api_key"] == secret
    assert loaded_ca == ["public-ca.pem"]
    assert captured[0]["ssl_context"].verify_mode == ssl.CERT_REQUIRED
    assert captured[0]["ssl_context"].check_hostname is True
    assert captured[0]["hosts"] == "https://localhost:9200"
    assert secret not in repr(settings)
