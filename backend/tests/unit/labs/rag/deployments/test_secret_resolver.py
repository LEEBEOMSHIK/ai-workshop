import pytest
from pydantic import SecretStr, ValidationError

from ai_workshop.config import Settings
from ai_workshop.labs.rag.deployments.secrets import (
    EndpointReferenceResolver,
    SecretReferenceError,
    SecretReferenceResolver,
)


def test_secret_resolver_rejects_unknown_reference_without_echoing_it() -> None:
    resolver = SecretReferenceResolver(
        {"openai-primary": SecretStr("synthetic-secret-value")}
    )

    with pytest.raises(SecretReferenceError, match="not configured") as caught:
        resolver.resolve("request-controlled-name")

    assert "request-controlled-name" not in str(caught.value)


def test_endpoint_resolver_rejects_unknown_reference_without_echoing_it() -> None:
    resolver = EndpointReferenceResolver(
        {"openai-responses": "https://example.invalid"}
    )

    with pytest.raises(SecretReferenceError, match="not configured") as caught:
        resolver.resolve("request-controlled-name")

    assert "request-controlled-name" not in str(caught.value)


def test_settings_parse_provider_reference_json_maps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_WORKSHOP_SECRET_KEY", "x" * 32)
    monkeypatch.setenv(
        "AI_WORKSHOP_PROVIDER_ENDPOINT_REFS",
        '{"openai-responses":"https://example.invalid"}',
    )
    monkeypatch.setenv(
        "AI_WORKSHOP_PROVIDER_SECRET_REFS",
        '{"openai-primary":"synthetic-secret-value"}',
    )

    settings = Settings(_env_file=None)

    assert settings.provider_endpoint_refs == {
        "openai-responses": "https://example.invalid"
    }
    assert settings.provider_secret_refs["openai-primary"].get_secret_value() == (
        "synthetic-secret-value"
    )


@pytest.mark.parametrize(
    ("environment_name", "encoded_map", "canary"),
    [
        (
            "AI_WORKSHOP_PROVIDER_SECRET_REFS",
            '{"openai-primary":["SECRET-MALFORMED-CANARY"]}',
            "SECRET-MALFORMED-CANARY",
        ),
        (
            "AI_WORKSHOP_PROVIDER_ENDPOINT_REFS",
            '{"openai-responses":{"url":"URL-MALFORMED-CANARY"}}',
            "URL-MALFORMED-CANARY",
        ),
        (
            "AI_WORKSHOP_PROVIDER_SECRET_REFS",
            '{"secret-SECRET-UNSAFE-CANARY":"synthetic-value"}',
            "SECRET-UNSAFE-CANARY",
        ),
        (
            "AI_WORKSHOP_PROVIDER_ENDPOINT_REFS",
            '{"URL-UNSAFE-CANARY":"https://example.invalid"}',
            "URL-UNSAFE-CANARY",
        ),
    ],
)
def test_invalid_provider_reference_maps_never_echo_canaries(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    encoded_map: str,
    canary: str,
) -> None:
    monkeypatch.setenv("AI_WORKSHOP_SECRET_KEY", "x" * 32)
    monkeypatch.setenv(environment_name, encoded_map)

    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None)

    message = str(caught.value)
    assert canary not in message
    assert "input_value" not in message
    assert "provider_" in message


@pytest.mark.parametrize(
    ("environment_name", "encoded_map"),
    [
        ("AI_WORKSHOP_PROVIDER_SECRET_REFS", '{"openai-primary":""}'),
        ("AI_WORKSHOP_PROVIDER_SECRET_REFS", '{"openai-primary":"   "}'),
        ("AI_WORKSHOP_PROVIDER_ENDPOINT_REFS", '{"openai-responses":""}'),
        ("AI_WORKSHOP_PROVIDER_ENDPOINT_REFS", '{"openai-responses":"   "}'),
    ],
)
def test_provider_reference_maps_reject_empty_values_with_safe_errors(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    encoded_map: str,
) -> None:
    monkeypatch.setenv("AI_WORKSHOP_SECRET_KEY", "x" * 32)
    monkeypatch.setenv(environment_name, encoded_map)

    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None)

    message = str(caught.value)
    assert "input_value" not in message
    assert "non-empty" in message
