# RAG 실행 관측 완료 판정·조회 수명주기 수정

2026-10-04 사용자 요청에 따라 기존 RAG 기능 마감을 재개했다. ISSUE-00013의 실제 종료 증빙·별칭 해제는 여전히 차단되어 있어 독립 가능한 실패 저장·모니터링 경계를 진행했다. 기존 main 작업 공간과 본래 `.env`·DB·계정·자료를 유지했다.

## 결함과 수정

- `finish_execution`은 필수 8단계가 completed/failed/skipped인지 검사한 뒤, running 실행의 최종 상태를 저장할 때 `outcome.complete`를 다시 대입했다. 단계가 누락·진행 중·미기록·잘못된 형태여도 관측 완료가 참으로 표시될 수 있었다. 이 재대입을 제거했다. 실행 실패와 관측 누락은 별개이며 실패/skipped 단계가 정확히 기록되면 관측은 완료다.
- 본래 SQL 검증 중 `SqlAlchemyMonitoringRepository.find`가 첫 결과에서 조기 반환하면서 내부 async generator의 조회 세션 정리가 지연되는 문제를 발견했다. 외부 트랜잭션 롤백 후 SAVEPOINT 정리가 시도되어 시험의 재조회가 실패했다. 별도 단위 테스트로 반환 시 정리되지 않는 것을 재현하고 `aclosing`으로 반환 전에 세션을 닫도록 수정했다. 조회 필터·권한·DTO 계약은 유지했다.

두 결함은 기존 문맥 품질 문제와 원인이 다르므로 새 문제로 분리해 기록해야 한다. **관리자 DB 등록·문서 버전 연결은 로그인 만료로 대기 중**이며 자동 번호를 임의로 만들지 않았다. JSON 최초 이관 자료도 수정하지 않았다.

## 검증 근거

- 수정 전 관측 판정 단위: 누락·running·unrecorded·malformed 4실패/3통과. 독립 실행도 executions 4실패/38통과로 원인을 재현했다.
- 조회 수명주기 단위: 결과 없음 통과, 결과 있음 1실패로 조기 반환 정리 누락을 재현했다.
- 수정 후 executions 44통과. 평가 실패 측정값·인용 검증을 포함한 최종 관련 단위 **65통과**(1.94초).
- 본래 PostgreSQL opt-in 통합 **4통과**(3.05초). 독립 executions **44통과**(2.03초), 본래 SQL **4통과**(3.29초).
- 최종 Ruff 통과, executions 소스 10파일 Mypy 통과. `AsyncGenerator` 타입 표기에는 Python3.13 기본 인자를 적용했다.

통합 테스트는 원래 `.env` loader로 local 환경과 `127.0.0.1:15432/ai_workshop_local_clean`을 확인하고 이미 적용된 schema0061을 요구한다. COMMIT event를 거부하며 실제 기존 owner/domain을 읽고 새 합성 conversation/turn/execution만 외부 트랜잭션 안에서 만든다. recorder의 내부 transaction은 SAVEPOINT로 결합한다. 테스트의 종료 순서 2가지(recorder 먼저 / 대화 종료 트리거 먼저)와 retrieval 단계 존재/누락 2가지를 검사한다. 실패 상태·이유·단계 시간·선택 측정값의 전체 JSON 보존과 실제 monitoring 저장소/summary/stages 재조회를 확인한다. 마지막에 롤백한 뒤 세 테이블의 시험 UUID 잔존이 각각 **0건**임을 확인한다. 별도 DB·계정·색인·파일 원본·모델 호출은 만들지 않는다.

재현 명령(저장소 루트 PowerShell):

```powershell
backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/unit/labs/rag/executions backend/tests/unit/labs/rag/evaluation/test_generative_failure_metrics.py backend/tests/unit/labs/rag/generation/test_citation_validation.py -q
@'
import os
import pytest
for key in list(os.environ):
    if key.upper().startswith('AI_WORKSHOP_'):
        del os.environ[key]
os.environ['AI_WORKSHOP_VERIFY_ORIGINAL_FINALIZATION'] = '1'
raise SystemExit(pytest.main(['-c', 'backend/pyproject.toml', 'backend/tests/integration/labs/rag/executions/test_original_finalization.py', '-q', '--tb=short']))
'@ | backend/.venv/Scripts/python.exe -
```

## 본래 API 반영

실행 중 API는 자동 재로딩 없이 구 코드를 사용했다. 본래 DB의 running 대화·생성형 평가가 각각0건임을 읽기 확인하고 API34204/launcher4856의 경로·명령을 다시 대조한 뒤 해당 API만 재시작했다. 원래 `.env`·Python·18000포트를 사용하며 새 API53672/Python launcher48244/숨김 PowerShell launcher52172다. 직접 health/readiness, 프론트 경유 health, 로그인 페이지가 모두200이었다. 프론트5173·Docker·worker·beat·migration·계정·자료·gate·receipt·활성 구성은 변경하지 않았다.

로그와 숨김 실행 스크립트는 `.local-data/dev-logs/original-rag-api-finalization-20261004.*`에 보관한다. 이는 코드 반영과 서버 준비 확인이며 실제 모델 실패·브라우저 이력 전체 검증 완료를 뜻하지 않는다.

## 남은 작업

1. 기존 마스터 로그인 후 새 문제 등록, 이 문서의 정확한 DB 버전 연결 및 사건별 발견·수정·검증·잔여 기록.
2. 실제 질문의 신규 모델 실패·timeout·인용 검증 상태가 최신/누적 모니터링과 비교 화면의 새로고침 후에도 일관되는지 확인. 이번 결과는 SQL 저장·재조회 검증이며 모델·브라우저 E2E를 대신하지 않는다.
3. ISSUE-00013의 실제 종료 proof·receipt·gate 해제·새 정상 parity와 기존 실제 첨부·모바일·Git/실행 인계의 남은 경계.

따라서 기존 RAG는 아직 기능 마감 중이며 **품질 개선만 남은 상태가 아니다**. SDK·저장소 비교·로컬 LLM 파인튜닝은 기존 기능 마감 뒤의 추가 작업으로 유지한다.
