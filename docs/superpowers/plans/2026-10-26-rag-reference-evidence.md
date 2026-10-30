# RAG reference evidence implementation plan

**Goal:** 답변 품질을 낮추지 않는 것을 수용 조건으로, 손실 없는 v6 입력 축소와 UUID 복원을 구현한다.
**Architecture:** 기존 v5 pack → 요청 한정 reference codec → v6 direct/SDK 입력 → strict schema2 검증 + UUID 복원. 과거 프로파일은 유지한다.
**Tech Stack:** Python, Pydantic, 기존 HTTP/OpenAI Agents SDK, 기존 비공개 실행 기록.
**Spec:** [ADR-0044](../../decisions/0044-rag-reference-evidence-input.md)

## 제약

기존230개 작업 파일과 본래 DB/계정/.env를 보존한다. 새 모델 호출0회로 먼저 구현·검증한다. 기본값·기존 프로파일·모델·검색·선택·예산·품질 기준은 변경하지 않는다. commit/push·설치·캐시 제거를 수행하지 않는다. 현재 체크아웃의 누적 작업을 이어가며 별도 환경으로 바꾸지 않는다.

## 1. Codec — AI 구현 담당

파일: 새 generation/reference_evidence.py, 새 tests/unit/labs/rag/generation/test_reference_evidence.py.

- [x] 실패 테스트를 먼저 실행: 전체 v5 구조와 unpack(pack)의 equality, 빈/다중 출처/순서/Unicode/중복 ID, 잘못된 참조·UUID 혼용·본문 무변경.
- [x] `pack_reference_evidence(evidence) -> ReferenceEvidencePack`, `unpack_reference_evidence(pack) -> CompactEvidence`, `resolve_evidence_refs(refs, mapping) -> tuple[UUID, ...]` 구현. payload와 immutable request map을 분리한다.
- [x] 전용 pytest·Ruff·범위 타입 통과. 실제 모델/DB 쓰기 없음.

## 2. 실행 연결 — 메인

파일: generation/prompts.py와 새 prompts/answer-v6.txt, models/context_evidence.py, generation/domain.py/readiness.py/openai_compatible.py, orchestration/openai_agents.py. 새 전용 integration unit test를 먼저 작성한다.

- [x] v6 local/schema2/budget gate·기존 v5 byte 보존·direct/SDK의 alias 출력→정확한 UUID·bad alias 거절·빈 claims 테스트를 실패 확인한다.
- [x] 입력·내용 지침 보존·schema2 출력 복원을 연결한다. 공유 runtime map을 만들지 않는다.
- [x] 실제 raw trace와 canonical final citation을 구분하고 저장/권한 경계를 확인한다.

실행 기록 구현 담당은 executions/agent_trace.py와 전용 단위 테스트만 맡아 `CitationReferenceMap(format=rag-answer-v6,evidence_ids=최대200개고유UUID)` 및 model span의 선택적 field/start_span 인자를 구현한다. 최초 publish 전에 설정하고 metadata_only·실패·취소·저장 왕복·running/terminal 변경 거절을 검증한다. 메인이 model_transport.py에서 specialist 요청의 정확한 순서 목록을 전달한다. 이 공개 상세 계약 추가로 OpenAPI/TypeScript 검사도 실행한다.

## 3. 독립 검증·수용 준비

- [x] 별도 담당이 독립 codec/SDK/direct/요청 동시성·부정 입력 테스트 및 코드 리뷰를 수행한다.
- [x] 관련 generation/orchestration/executions/evaluation 단위 범위와 범위 strict Mypy/Ruff를 실행한다. 공개 API schema 변경 시만 OpenAPI/TypeScript를 검증한다. DB 통합은 기존 opt-in rollback 방식만 허용한다.
- [x] 기존 공개 합성 입력으로 원문·위치·인용 전체 왕복과 v5 byte 보존, v6 byte 차이를 측정한다. actual token/품질/지연으로 확대하지 않는다.
- [x] WORKBOARD·실측 가능 후보와 품질 퇴행 거절 기준을 정리한다. 실제 호출은 별도 남은 승인 범위 확인 후 수행한다.

검증은 기존 Conda·정상 Windows asyncio를 사용한다. 필요한 pytest 임시 경로는 `.local-data/project-agent-work/rag-reference-packing-20261026/` 아래에 둔다.

## 실행 결과

구현 검증 후 사용자 추가4회 승인으로 동일 질문2반복 실측을 마쳤다. 두 답변·인용과28근거를 유지하면서 입력24.3%·첫 입력 처리25.3% 감소를 관찰했다. 기존 품질0/2와 반복 전체 지연 증가는 남아 비기본 후보로 유지한다. 본래 API·저장 기록·자료 보존·실제 화면을 확인했다. [정확한 결과·잔여 작업](../../worklogs/2026-10-26-rag-reference-packing.md)을 따른다.
