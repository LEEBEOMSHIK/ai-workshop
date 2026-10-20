# RAG 기능 마감 확인 — 품질 개선과 분리

2026-10-11. 사용자 요청에 따라 RAG의 기능 정상화를 품질 튜닝보다 우선했다.
이번 결과는 **제한된 기능 검증 완료이며 RAG 기능 마감은 미완료**다.
새 제품 오류가 재현되지 않아 제품 코드나 테스트를 추가·수정하지 않았다.

## 사용자 흐름별 마감 기준과 현재 증거

| 흐름·완료 기준 | 이번에 확인된 정상 | 재현된 오류 | 미검증 | 승인 또는 외부 증거로 차단 |
| --- | --- | --- | --- | --- |
| 문서/첨부 업로드 → 저장 → 파싱·임베딩·색인 READY → 검색 | 대화/첨부 서비스 단위 계약. 과거 저장 완료 기록은 현재 E2E 성공과 구분 | 새 제품 오류 없음 | 현재 원본 업로드·worker 처리·개인 검색 | 현재 DB alias open1/frozen1/receipt0. 과거 기록상 개인 첨부 queued이며 실제 READY 미완료. 이번에는 첨부 예약 상태를 직접 조회하지 않음 |
| 허용된 공간·폴더·문서 범위만 검색·원문 열기 | 범위/선택 문서/생성 정책/history 및 인용 단위83 통과 | 새 제품 오류 없음 | 현재 ES 검색·원문, 다른 연결에서 권한 철회하는 committed 경합 | 실제 본래 환경 데이터/권한을 변경하는 시나리오는 현 승인 범위 밖 |
| 첫 질문·후속 질문 → 생성/검증된 인용 → 대화 저장·재조회 | 대화 서비스와 Codex executor/runtime/HTTP 단위153 통과 | 새 제품 오류 없음 | 현재 브라우저·DB 첫 질문/멀티턴, 실제 provider, 인용 클릭·저장 복원 | 현재 질문·모델 실행은 유료 호출/업무 DB 쓰기 승인 범위 밖. DLL 영구 재발 방지는 미완료 |
| 취소·시간 제한·실패 → 실행 정리 → 안전한 상태/재조회 → 다음 질문 | Windows process/stream54 통과. 이 묶음은 실제 합성 자식 종료 사례와 fake 실패 사례를 포함. 독립 lifecycle/executor19 통과 | 새 제품 오류 없음 | 실제 Codex 모델 중지, 브라우저 취소→terminal 저장→다음 질문, 과거 미종료 작업의 정식 복구 | 현재 DB cancelled/terminated=false1. 현재 새 프로세스가 없다는 사실이나 합성 테스트를 과거 종료 증거로 대체할 수 없음 |

상태가 `verified`인 문제도 그 문제의 과거 검증 범위만 뜻한다. 위 전체 사용자 흐름을
현재 본래 환경에서 재현한 것으로 해석하지 않는다. `새 제품 오류 없음`은 실행한 범위에서
재현되지 않았다는 의미이며 시스템 전체에 결함이 없다는 선언이 아니다.

## 현재 DB 읽기 전용 확인

기존 프로젝트 `.env`로 구성한 local/loopback DB에 연결했다. 비밀값·본문·질문·답변·
계정 식별자는 출력하지 않았다. 단일 트랜잭션 `SET TRANSACTION READ ONLY`,
statement timeout 5초, commit 거부 listener를 사용했고 rollback 완료를 확인했다.
SELECT와 트랜잭션 로컬 설정만 실행했으며 업무 데이터 변경은 없었다.

- schema: `0063_rag_numeric_proof`.
- 열린 별칭 작업1, frozen gate1, recovery receipt0.
- turn: completed/종료확인17, failed/종료확인4, cancelled/종료확인1,
  cancelled/종료미확인1. 이는 상태 집계이며 실제 프로세스 종료를 새로 입증한 것은 아니다.
- ISSUE-00001 verified/r10, 00002 implemented/r6, 00003 implemented/r4,
  00005 open/r69, 00013 open/r33, 00018 implemented/r3, 00029 open/r8.
- 이번 조회는 상태/개수만 확인했다. 개별 remaining·프로세스 identity·역사 source map·
  receipt 내용·전체 자료 SHA 보존을 새로 검증한 것은 아니다.

## 작업 선정과 독립 역할

가장 큰 차단은 별칭 복구 뒤의 실제 첨부 색인이다. 기존 native observer/backend/factory
미완성과 역사 실행 근거 차단은 [기존 기록](2026-10-08-rag-control-native.md)에 남아 있고,
새 테스트가 이를 해결하지 않는다. 별칭 gate 해제·보안 전환·서비스 기동은 이번 승인에 없다.

그 다음 승인 안에서 확인 가능한 취소/시간 제한/실패 복구 코드를 먼저 진단했다.
대화/HTTP 수명주기, Codex executor, 프로세스 실행/stream의 호출 경계를 읽고 기존 테스트를
실행했다. 특히 답변 이벤트 이후에도 취소·timeout·비정상 종료이면 답변을 버리는지,
반복 취소에도 cleanup/gate/slot 종결을 기다리는지 확인했다. 재현 가능한 제품 결함을
발견하지 못해 테스트 수 증가나 임의 구현으로 성공을 꾸미지 않았다.

낮은 위험의 검증 작업이다. 메인이 RAG 범위 선정·AI 런타임 진단·통합을 맡고 별도
독립 검증/리뷰 담당이 lifecycle/executor/process/stream를 읽고 관련 검사를 재실행했다.
UI·DB·배포·보안 구현 역할은 변경이 없어 제외했다. 독립 검토도 재현 가능한 수정 사항 없음.
기존 작업 상태에서 다른 저장소 작업 대화는 notLoaded였고 파일 보존을 별도로 점검한다.

## 실제 실행 명령과 결과

기존 backend 디렉터리의 `.venv/Scripts/python.exe -B -m pytest`를 사용했다.
각 명령 뒤에 `-q --tb=short`를 붙였다. 외부 모델·네트워크에 의존하는 테스트는 없다.

1. `tests/unit/labs/rag/conversations tests/unit/labs/rag/generation/test_codex_execution.py tests/unit/labs/rag/generation/test_codex_runtime.py tests/unit/labs/rag/generation/test_codex_http_lifecycle.py`
   — **153 passed**, 17.40초.
2. `tests/unit/labs/rag/generation/test_windows_process.py tests/unit/labs/rag/generation/test_codex_stream.py`
   — **54 passed**, 14.64초. 테스트용 Python만 사용하고 실제 Codex CLI/모델은 호출하지 않았다.
3. `tests/unit/labs/rag/retrieval/test_scope.py tests/unit/labs/rag/retrieval/test_document_selection.py tests/unit/labs/rag/search/test_generation_policy_gate.py tests/unit/labs/rag/search/test_selected_scope_history.py tests/unit/labs/rag/generation/test_citation_validation.py`
   — **83 passed**, 3.41초.
4. 독립 담당 lifecycle/executor 두 파일 — **19 passed**, 1.29초. 위 결과와 겹치므로
   메인 총290에 더하지 않는다.

제품/테스트 변경이 없어 타입·린트를 새로 실행하지 않았다. 전체 저장소, 브라우저,
본래 DB 저장·commit 경합, 실제 모델, 신규 파싱/임베딩/색인 검증은 미실행이다.
마감 시 초기 변경465파일의 SHA를 다시 비교해 WORKBOARD 외464파일이 그대로임을 확인했다.
WORKBOARD 쓰기 직전 원본 대조와 최근5개/UTF-8/로컬 링크·scoped diff 검사는 통과했다.

## 다음 작업과 필요한 조건

1. **별칭 복구·첨부 READY 우선:** 기존 계획의 전체 native 연결과 역사 종료 근거를
   확보·검토해야 한다. 당시 source map/종료 증거 없이 현재 파일이나 새 receipt를
   만들어 대신하지 않는다. 운영 적용은 exact 대상·변경·보존·검증·복구 순서가 준비된
   뒤에 별도 승인할 항목이며 포괄적인 보안 완화 승인을 요청하지 않는다.
2. **종료미확인 취소1건:** 정확한 실행을 식별하고 종료 근거를 확보한 뒤 기존 정식
   복구 경로로 처리해야 한다. SQL 상태 강제 변경이나 취소 재전송만으로 완료 처리하지 않는다.
3. **본래 환경 수용 확인:** 기존 계정/자료를 보존하며 업로드/질문/취소/복원/다음 질문,
   committed 권한 경합을 검증하려면 한정된 DB 쓰기와 필요한 실행 상태 변경 승인이 필요하다.
   실제 provider 시험은 별도 유료 호출 승인이 필요하며 정확한 호출 상한·토큰 한도와
   현재 적용 가격을 확인하기 전 비용 숫자를 추정해 약속하지 않는다.

지금 즉시 승인만 받으면 해결된다는 의미는 아니다. 선행 실행 근거·구현이 부족한
별칭 복구와 새 승인으로 가능한 본래 환경 검증을 구분한다. 구체적인 승인 패키지가
준비되지 않은 상태에서 migration/DB/ES/Docker·보안·권한 변경을 요청하거나 실행하지 않았다.

검색 정확도·랭킹·근거 예산 확대·유보 답변 감소·속도·프로파일 승격은 별도 품질 과제다.
기능 마감 후 Agents SDK → 벡터 저장소 비교 → 로컬 LLM 파인튜닝 → Kubernetes 순서를
유지한다. 학습 문서·학습 완료 상태·예약과 커밋·푸시는 변경하지 않았다.

## 최근 완료 목록에서 이동한 기존 기록

5. 접근 전환 완료 반환 경계 보완(2026-10-08): 실제 repository/fakeclosure의10실패 사례로 저장/최종조회후 ownership 누락을 재현했다. 공통 owned_readback과 mark후검사로 현재lostexecutor 성공/proof발급만 차단하고 durableverified·읽기재접수유지. indexing477·Ruff/Mypy·독립46 통과, exactDBv1/ISSUE13openr20 기록, 실제 native 복구·색인은 대기. [기록](2026-10-08-rag-access-epoch-finalization.md).
