from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator

from ai_workshop.shared.errors import AppError

_PUBLIC_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _normalize_public_text(value: str) -> str:
    normalized = unicodedata.normalize(
        "NFC",
        value.strip().replace("\r\n", "\n").replace("\r", "\n"),
    )
    if not normalized:
        raise ValueError("public text must not be blank")
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("public text must be UTF-8 encodable") from None
    return normalized


def _normalize_public_slug(value: str) -> str:
    normalized = _normalize_public_text(value)
    if _PUBLIC_SLUG.fullmatch(normalized) is None:
        raise ValueError("public slug is invalid")
    return normalized


def _invalid_package() -> AppError:
    return AppError(
        "publishing_package_invalid",
        "The public study package is invalid.",
        422,
    )


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PublicPersona(_FrozenModel):
    slug: str
    label: str

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        return _normalize_public_slug(value)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        return _normalize_public_text(value)


class StudyContent(_FrozenModel):
    slug: str
    title: str
    summary: str
    topic_keys: tuple[str, ...]
    body: str
    verification: str
    limitations: str
    persona: PublicPersona | None = None

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        return _normalize_public_slug(value)

    @field_validator("title", "summary", "body", "verification", "limitations")
    @classmethod
    def normalize_text(cls, value: str, _info: ValidationInfo) -> str:
        return _normalize_public_text(value)

    @field_validator("topic_keys")
    @classmethod
    def normalize_topics(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_normalize_public_slug(value) for value in values)
        if not normalized:
            raise ValueError("public topics must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("public topics must be unique")
        return normalized


class StudySnapshot(_FrozenModel):
    schema_version: Literal[1] = 1
    revision: int = Field(strict=True, gt=0)
    content: StudyContent = Field(repr=False)

    @field_validator("schema_version", mode="before")
    @classmethod
    def require_supported_schema(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("public package schema version is invalid")
        return value


def canonical_bytes(snapshot: StudySnapshot) -> bytes:
    return json.dumps(
        snapshot.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def snapshot_digest(snapshot: StudySnapshot) -> str:
    return hashlib.sha256(canonical_bytes(snapshot)).hexdigest()


def decode_snapshot(payload: bytes, *, expected_digest: str) -> StudySnapshot:
    if hashlib.sha256(payload).hexdigest() != expected_digest:
        raise _invalid_package()

    snapshot: StudySnapshot | None
    reencoded: bytes | None
    try:
        decoded = json.loads(payload)
        snapshot = StudySnapshot.model_validate(decoded)
        reencoded = canonical_bytes(snapshot)
    except (
        UnicodeDecodeError,
        UnicodeEncodeError,
        json.JSONDecodeError,
        ValidationError,
        TypeError,
        ValueError,
    ):
        snapshot = None
        reencoded = None

    if snapshot is None or reencoded != payload:
        raise _invalid_package()
    return snapshot
