from ai_workshop.labs.rag.chunking.sentences import split_sentences


def test_split_sentences_preserves_korean_punctuation_boundaries() -> None:
    text = "첫 문장입니다. 두 번째 문장인가요? 세 번째 문장입니다!"

    assert split_sentences(text) == (
        "첫 문장입니다.",
        "두 번째 문장인가요?",
        "세 번째 문장입니다!",
    )


def test_split_sentences_keeps_numbered_clauses_together() -> None:
    text = "1. 투자 대상은 채권이다. 2. 위험 한도는 준수한다."

    assert split_sentences(text) == (
        "1. 투자 대상은 채권이다.",
        "2. 위험 한도는 준수한다.",
    )


def test_split_sentences_keeps_list_items_and_table_cells_as_single_units() -> None:
    assert split_sentences("- 손실 한도: 5%") == ("- 손실 한도: 5%",)
    assert split_sentences("자산군 | 한도 | 10%") == ("자산군 | 한도 | 10%",)
