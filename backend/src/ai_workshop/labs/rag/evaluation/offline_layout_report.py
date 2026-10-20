"""Static local report of original inputs and unexecuted layout candidates."""

import html
from pathlib import Path
from typing import cast

from pydantic import JsonValue

from ai_workshop.labs.rag.evaluation.offline_input_diagnosis import (
    Capture,
    content,
    encode,
    fragments,
    object_value,
    parse_object,
)
from ai_workshop.labs.rag.evaluation.offline_layout_candidate import (
    prepare_layout_candidate,
    verify_layout_candidate,
)


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def write_layout_report(sources: tuple[Capture, ...], output: Path) -> None:
    candidates = tuple(prepare_layout_candidate(source) for source in sources)
    if not sources or len({s.attempt_id for s in sources}) != len(sources):
        raise ValueError("Distinct source attempts are required.")
    sections: list[str] = []
    for source, candidate in zip(sources, candidates, strict=True):
        verify_layout_candidate(source, candidate)
        body = parse_object(candidate.request_json)
        payload = parse_object(content(body, 1))
        by_id = {str(f["evidence_id"]): f for f in fragments(payload)}
        layout = object_value(payload["layout_hints"]) if candidate.grid_count else {"grids": []}
        section = (f'<article><h2>{_escape(payload["question"])}</h2>'
                   f'<p>상태: 미실행 · 관측 격자 {candidate.grid_count}개 · '
                   f'입력 {source.body_bytes:,} → {candidate.body_bytes:,}bytes</p>')
        for raw_grid in cast(list[JsonValue], layout["grids"]):
            grid = object_value(raw_grid)
            section += ('<table><caption>좌표로 관측한 배열 — 의미 역할·표 전체 미확정'
                        '</caption><tbody>')
            for row in cast(list[list[str]], grid["rows"]):
                section += '<tr>' + ''.join(
                    f'<td>{_escape(by_id[i]["text"])}<small>{_escape(i)}</small></td>' for i in row
                ) + '</tr>'
            section += '</tbody></table>'
        if not candidate.grid_count:
            section += '<p>지원하는 격자 없음: 입력을 바이트 그대로 유지했습니다.</p>'
        for label, value in (("보존한 system 지침", content(body, 0)),
                             ("D의 최종 user 입력", content(body, 1)),
                             ("A 대비 차이", candidate.diff),
                             ("출처 입력 SHA", source.sha256)):
            section += f'<details><summary>{label}</summary><pre>{_escape(value)}</pre></details>'
        sections.append(section + '</article>')
    page = (
        '<!doctype html><html lang="ko"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        'style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
        '<title>원문 배열 D 비교 후보</title><style>'
        'body{font:17px/1.6 system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:16px;'
        'color:#172033;background:#f6f8fb}article{background:white;padding:24px;margin:24px 0;'
        'border:1px solid #ccd5df}table{border-collapse:collapse;width:100%;table-layout:fixed}'
        'td{border:1px solid #ccd5df;padding:12px;overflow-wrap:anywhere}small{display:block;'
        'overflow-wrap:anywhere;color:#5a6879}pre{white-space:pre-wrap;overflow-wrap:anywhere;'
        'font-size:14px}summary{cursor:pointer;padding:10px}caption{text-align:left}</style>'
        '<h1>원문 배열 D 비교 후보 — 미실행</h1>'
        '<p>원문·인용 ID·선택 범위·지침을 보존하고 좌표에서 관측되는 행·열 배열만 추가했습니다. '
        '첫 행을 헤더로 지정하거나 상품·규칙·조건 관계를 확정하지 않습니다. '
        '다른 열·주석·조건을 생략하지 않으며 모델 답변을 생성하지 않았습니다.</p>'
        '<p>현재 원문 접근 권한을 재조회한 자료가 아닙니다. '
        '실제 전송 전 별도로 확인해야 합니다.</p>'
        + ''.join(sections) + '</html>'
    )
    output.mkdir(parents=True, exist_ok=False)
    (output / 'index.html').write_text(page, encoding='utf-8')
    (output / 'candidates.json').write_text(encode({
        "version": "offline-layout-candidate-v1", "execution_status": "not_run", "model_calls": 0,
        "items": [{"source": s.model_dump(mode="json"), "candidate": c.model_dump(mode="json")}
                  for s, c in zip(sources, candidates, strict=True)],
    }), encoding='utf-8')
