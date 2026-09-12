import hashlib

import pytest
from pydantic import ValidationError

from ai_workshop.platform.publishing.package import (
    PublicPersona,
    StudyContent,
    StudySnapshot,
    canonical_bytes,
    decode_snapshot,
    snapshot_digest,
)
from ai_workshop.shared.errors import AppError


def synthetic_content(**changes: object) -> StudyContent:
    values: dict[str, object] = {
        "slug": "example-study",
        "title": "합성 연구",
        "summary": "공개 계약을 검증하는 합성 요약",
        "topic_keys": ("rag",),
        "body": "공개 계약을 검증하는 합성 본문",
        "verification": "게시와 철회 순서를 확인함",
        "limitations": "실제 자료와 외부 서비스를 사용하지 않음",
    }
    values.update(changes)
    return StudyContent.model_validate(values)


def synthetic_snapshot(**changes: object) -> StudySnapshot:
    values: dict[str, object] = {"revision": 1, "content": synthetic_content()}
    values.update(changes)
    return StudySnapshot.model_validate(values)


def raw_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_canonical_package_normalizes_public_text_and_has_literal_encoding() -> None:
    snapshot = StudySnapshot(
        revision=1,
        content=StudyContent(
            slug="  example-study  ",
            title="  \u1100\u1161 연구  ",
            summary=" 요약 ",
            topic_keys=(" rag ", "retrieval"),
            body=" 첫째\r\n둘째 ",
            verification=" 검증\r완료 ",
            limitations=" 합성 자료만 사용 ",
        ),
    )
    expected = (
        '{"content":{"body":"첫째\\n둘째","limitations":"합성 자료만 사용",'
        '"persona":null,"slug":"example-study","summary":"요약","title":"가 연구",'
        '"topic_keys":["rag","retrieval"],"verification":"검증\\n완료"},'
        '"revision":1,"schema_version":1}'
    ).encode()

    assert snapshot.content.title == "가 연구"
    assert canonical_bytes(snapshot) == expected
    assert snapshot_digest(snapshot) == (
        "d119f82e2fe497d16a9109990a1cddc654b038a330dc1244c32ff514a5384d97"
    )


def test_persona_fields_are_normalized_without_becoming_approval_proof() -> None:
    content = synthetic_content(
        persona=PublicPersona(slug=" public-reviewer ", label="  검토\r\n담당  ")
    )

    assert content.persona == PublicPersona(slug="public-reviewer", label="검토\n담당")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("slug", "../../private"),
        ("slug", "Example-Study"),
        ("slug", "example--study"),
        ("title", " \r\n "),
        ("summary", ""),
        ("body", "\t"),
        ("verification", "\r"),
        ("limitations", "   "),
    ],
)
def test_study_content_rejects_unsafe_or_blank_public_fields(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        synthetic_content(**{field: value})


@pytest.mark.parametrize(
    "topic_keys",
    [(), ("rag", " rag "), ("rag", "../private"), ("rag", "")],
)
def test_topics_must_be_nonempty_unique_safe_slugs(topic_keys: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        synthetic_content(topic_keys=topic_keys)


@pytest.mark.parametrize(
    "persona",
    [
        {"slug": "../owner", "label": "검토자"},
        {"slug": "reviewer", "label": "  "},
        {"slug": "reviewer", "label": "검토자", "user_id": "private-user"},
    ],
)
def test_persona_rejects_unsafe_blank_or_private_fields(persona: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        synthetic_content(persona=persona)


@pytest.mark.parametrize("revision", [True, False, 0, -1, 1.0, "1"])
def test_revision_is_a_strict_positive_integer(revision: object) -> None:
    with pytest.raises(ValidationError):
        synthetic_snapshot(revision=revision)


@pytest.mark.parametrize("schema_version", [True, False, 0, 2, "1"])
def test_schema_version_only_accepts_the_strict_supported_integer(schema_version: object) -> None:
    with pytest.raises(ValidationError):
        synthetic_snapshot(schema_version=schema_version)


def test_models_are_frozen_and_reject_unknown_fields() -> None:
    snapshot = synthetic_snapshot()

    with pytest.raises(ValidationError):
        snapshot.content.title = "변경된 제목"
    with pytest.raises(ValidationError):
        StudyContent.model_validate(
            {
                **snapshot.content.model_dump(),
                "source_path": "C:/private/source.md",
            }
        )


def test_snapshot_repr_does_not_echo_submitted_content() -> None:
    marker = "private-submitted-value"
    snapshot = synthetic_snapshot(content=synthetic_content(body=marker))

    assert marker not in repr(snapshot)


def test_decode_accepts_only_the_exact_canonical_approved_bytes() -> None:
    snapshot = synthetic_snapshot()
    payload = canonical_bytes(snapshot)

    decoded = decode_snapshot(payload, expected_digest=snapshot_digest(snapshot))

    assert decoded == snapshot
    assert decoded is not snapshot


def test_decode_rejects_content_changed_after_digest_approval() -> None:
    snapshot = synthetic_snapshot()
    payload = canonical_bytes(snapshot).replace("합성 본문".encode(), "변조 본문".encode())

    with pytest.raises(AppError) as failure:
        decode_snapshot(payload, expected_digest=snapshot_digest(snapshot))

    assert failure.value.code == "publishing_package_invalid"
    assert failure.value.status_code == 422


@pytest.mark.parametrize("variant", ["whitespace", "duplicate", "private", "schema"])
def test_decode_rejects_noncanonical_or_non_allowlisted_json(variant: str) -> None:
    canonical = canonical_bytes(synthetic_snapshot())
    if variant == "whitespace":
        payload = b" " + canonical
    elif variant == "duplicate":
        payload = canonical.replace(
            b'{"content":{',
            b'{"content":{"slug":"example-study",',
            1,
        )
    elif variant == "private":
        payload = canonical.replace(
            b'{"content":{',
            b'{"content":{"private_path":"C:/private/source.md",',
            1,
        )
    else:
        payload = canonical.replace(b'"schema_version":1', b'"schema_version":2', 1)

    with pytest.raises(AppError) as failure:
        decode_snapshot(payload, expected_digest=raw_digest(payload))

    assert failure.value.code == "publishing_package_invalid"
    assert failure.value.status_code == 422


def test_decode_malformed_error_never_echoes_submitted_bytes() -> None:
    marker = "private-submitted-value"
    payload = b'{"body":"private-submitted-value"\xff}'

    with pytest.raises(AppError) as failure:
        decode_snapshot(payload, expected_digest=raw_digest(payload))

    assert failure.value.code == "publishing_package_invalid"
    assert marker not in str(failure.value)
    assert marker not in repr(failure.value)


@pytest.mark.parametrize("surrogate", [chr(0xD800), chr(0xDFFF)])
def test_public_text_rejects_lone_surrogates_before_snapshot_hashing(surrogate: str) -> None:
    with pytest.raises(ValidationError):
        synthetic_content(title=f"합성 연구 {surrogate}")


@pytest.mark.parametrize("escaped_surrogate", [br"\ud800", br"\udfff"])
def test_decode_lone_surrogate_returns_safe_error_without_echo(
    escaped_surrogate: bytes,
) -> None:
    marker = "private-submitted-value"
    canonical = canonical_bytes(synthetic_snapshot())
    payload = canonical.replace(
        "합성 연구".encode(),
        marker.encode() + escaped_surrogate,
        1,
    )

    try:
        with pytest.raises(AppError) as failure:
            decode_snapshot(payload, expected_digest=raw_digest(payload))
    except UnicodeEncodeError:
        pytest.fail("decode_snapshot leaked a UnicodeEncodeError for a lone surrogate")

    assert failure.value.code == "publishing_package_invalid"
    assert failure.value.status_code == 422
    assert marker not in str(failure.value)
    assert marker not in repr(failure.value)


def test_valid_non_bmp_public_text_round_trips() -> None:
    snapshot = synthetic_snapshot(content=synthetic_content(title="합성 연구 🧪"))
    payload = canonical_bytes(snapshot)

    decoded = decode_snapshot(payload, expected_digest=raw_digest(payload))

    assert decoded.content.title == "합성 연구 🧪"
