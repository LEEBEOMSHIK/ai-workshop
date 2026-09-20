"""Selection contract fixtures; these mocked scores do not measure model quality."""

from dataclasses import replace

import pytest

from ai_workshop.labs.rag.highlighting.context import select_context
from tests.unit.labs.rag.highlighting.test_context import BUDGET, EMPTY, ContextEmbedding
from tests.unit.labs.rag.highlighting.test_evidence_selector import _policy, _source


@pytest.mark.parametrize(("query", "body", "score", "selected"), [
    ("달빛 보증은 얼마나 가나요?", "보증 기간은 구매 후 18개월입니다.", 0.95, True),
    ("보상액을 알려줘", "장비당 최대 보상 금액은 20만원입니다.", 0.95, True),
    ("어디서 신청하면 돼?", "신청서를 담당 부서에 제출합니다.", 0.95, True),
    ("어떤 조건에서 적용돼?", "등록을 마친 장비에만 적용합니다.", 0.95, True),
    ("제외되는 경우는?", "침수로 인한 손상은 보상하지 않습니다.", 0.95, True),
    ("누구에게 문의하지?", "합성 담당자는 가상인물 별하입니다.", 0.95, True),
    ("지원 여부가 궁금해", "이 장비는 지원 대상이 아닙니다.", 0.95, True),
    ("두 장비의 기간을 비교해줘", "달빛은 18개월, 별빛은 6개월입니다.", 0.95, True),
    ("무게는?", "제품 이름은 달빛입니다.", 0.1, False),
    ("목성 대기압 측정값", "제품 이름은 달빛입니다.", 0.1, False),
])
def test_context_selection_question_matrix(query, body, score, selected):
    source = _source(1, body)
    unrelated = _source(2, "unrelated synthetic source")

    class Scores(ContextEmbedding):
        def encode_documents(self, texts):
            return [[score, (1 - score**2)**0.5] if body in text else [0, 1]
                    for text in texts]

    result = select_context(query=query, sources=(source, unrelated), extractive=EMPTY,
        policy=_policy(min_keyword_coverage=1.0, min_semantic_score=0.9), budget=BUDGET,
        embedding=Scores(), include_diagnostics=True)
    ids = {unit.id for group in result.groups for unit in group.units}
    assert (source.chunk.evidence_units[0].id in ids) is selected
    assert unrelated.chunk.evidence_units[0].id not in ids
    if selected:
        assert result.groups[0].units[0].text == body


def test_missing_table_labels_are_not_invented_from_metadata():
    source = _source(1, "20")
    source = replace(source, chunk=replace(source.chunk, section_path=()))
    result = select_context(query="amount", sources=(source,), extractive=EMPTY,
        policy=_policy(), budget=BUDGET, embedding=ContextEmbedding(), include_diagnostics=True)
    assert result.groups == ()
