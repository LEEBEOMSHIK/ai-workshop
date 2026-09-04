from collections.abc import Mapping

from pydantic import SecretStr


class SecretReferenceError(ValueError):
    pass


class EndpointReferenceResolver:
    def __init__(self, allowlist: Mapping[str, str]) -> None:
        self._allowlist = dict(allowlist)

    def resolve(self, reference: str) -> str:
        try:
            return self._allowlist[reference]
        except KeyError as exc:
            raise SecretReferenceError(
                "The endpoint reference is not configured."
            ) from exc


class SecretReferenceResolver:
    def __init__(self, allowlist: Mapping[str, SecretStr]) -> None:
        self._allowlist = dict(allowlist)

    def resolve(self, reference: str) -> SecretStr:
        try:
            return self._allowlist[reference]
        except KeyError as exc:
            raise SecretReferenceError(
                "The secret reference is not configured."
            ) from exc

