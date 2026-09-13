import pytest

from ai_workshop.platform.assets.folder_names import folder_name_key


def test_folder_name_key_strips_only_the_frozen_whitespace_set() -> None:
    assert folder_name_key("\t 연구 \u3000") == "연구"
    assert folder_name_key("A") != folder_name_key("a")
    assert folder_name_key("\u200b연구\u200b") == "\u200b연구\u200b"


@pytest.mark.parametrize(
    "whitespace",
    tuple(
        "\u0009\u000a\u000b\u000c\u000d\u001c\u001d\u001e\u001f"
        "\u0020\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004"
        "\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f"
        "\u205f\u3000"
    ),
)
def test_folder_name_key_strips_each_supported_boundary_character(whitespace: str) -> None:
    assert folder_name_key(f"{whitespace}자료{whitespace}") == "자료"


def test_folder_name_key_does_not_normalize_unicode() -> None:
    combining = "e\u0301"

    assert folder_name_key(combining) == combining
    assert folder_name_key(combining) != "é"
