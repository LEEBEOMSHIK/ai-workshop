from ai_workshop.labs.rag.chunking.sentences import SentenceSpan, split_sentences


def _texts(spans: tuple[SentenceSpan, ...]) -> tuple[str, ...]:
    return tuple(span.text for span in spans)


def test_split_sentences_preserves_korean_punctuation_boundaries() -> None:
    text = "첫 문장입니다. 두 번째 문장인가요? 세 번째 문장입니다!"

    assert _texts(split_sentences(text)) == (
        "첫 문장입니다.",
        "두 번째 문장인가요?",
        "세 번째 문장입니다!",
    )


def test_split_sentences_keeps_numbered_clauses_together() -> None:
    text = "1. 투자 대상은 채권이다. 2. 위험 한도는 준수한다."

    assert _texts(split_sentences(text)) == (
        "1. 투자 대상은 채권이다.",
        "2. 위험 한도는 준수한다.",
    )


def test_split_sentences_splits_punctuationless_adjacent_numbered_clauses() -> None:
    assert _texts(split_sentences("1. 투자 대상 2. 위험 한도")) == (
        "1. 투자 대상",
        "2. 위험 한도",
    )


def test_split_sentences_recognizes_numbered_markers_at_valid_clause_starts() -> None:
    assert _texts(split_sentences("도입 문장입니다. 1. 첫 항목 2. 둘째 항목")) == (
        "도입 문장입니다.",
        "1. 첫 항목",
        "2. 둘째 항목",
    )


def test_split_sentences_treats_numeric_sentence_endings_as_sentence_boundaries() -> None:
    assert _texts(split_sentences("기준 연도는 2025. 다음 기준은 2026.")) == (
        "기준 연도는 2025.",
        "다음 기준은 2026.",
    )


def test_split_sentences_does_not_treat_embedded_numeric_values_as_clause_markers() -> None:
    assert _texts(split_sentences("1. 기준 연도는 2025. 다음 문장입니다.")) == (
        "1. 기준 연도는 2025.",
        "다음 문장입니다.",
    )


def test_split_sentences_keeps_list_items_and_table_cells_as_single_units() -> None:
    assert _texts(split_sentences("- 손실 한도: 5%")) == ("- 손실 한도: 5%",)
    assert _texts(split_sentences("자산군 | 한도 | 10%")) == (
        "자산군 | 한도 | 10%",
    )
