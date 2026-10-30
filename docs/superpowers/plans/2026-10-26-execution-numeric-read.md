# 실행 목록 숫자 근거 조회 비용 개선

2026-10-26 · ISSUE-00042 · 사용자 “계속 다음 작업 진행해”의 후속 범위.

## 목표와 경계

앞선 원문 조회 개선 뒤 남은 숫자 검증 비용을 줄인다. 저장 답변·인용·판정·권한 거절 결과는 동일해야 한다. 현재 checkout의 누적 미커밋 변경이 본래 환경 기준이므로 새 checkout으로 누락시키지 않고 파일별 시작 해시와 수정 전 소스를 보존한다. 새 계정/DB/모델 호출/설치/migration/commit/push/캐시 삭제는 없다.

새 읽기 전용 진단에서 전체508건(대화25/평가483), 평가SQL640·대화295를 확인했다. `FrozenValue.digest`는 규칙960회65.0ms, 결과480회1729.1ms였다. 프로파일링한 시간은 최종 성능 비교로 사용하지 않는다. 규칙 digest만 줄이는 수정은 이득이 작아 제외하며 결과 직렬화는 별도 합성 실험에서 동등성과 효과를 확인한 경우에만 범위를 추가한다.

CPU 조사 결론: 공개 합성32/512/2048근거에서 `model_dump_json → json.loads → canonical json.dumps` 대안은 동일 바이트지만 기존보다1.37/1.51/1.41배 느렸다. 이 대안과 효과가 작은 규칙 캐시를 기각하고 CPU 제품 수정은 제외한다. 숫자 원문 조회만 구현한다.

## 선택한 설계

`generation/numeric_validation_repository.py::SqlAlchemyNumericValidationRepository.verify_binding(binding, payload, *, expected) -> None`의 source 조회만 변경한다. 공개 계약·DB 스키마·생성 검증 기준은 유지하므로 새 ADR은 필요하지 않다.

- receipt의 `populate_existing`, payload digest/재구성, audit actor/execution/profile/config/status/evidence 순서 검증을 그대로 둔다.
- claim별 근거를 최대64개씩 조회한다. 원래 JOIN과 ready/active/current workspace 조건을 유지하고 반환 ID 집합 전체를 대조한다. 중복 index build 행은 존재성으로 처리한다.
- proof별 피연산자를 최대64개씩 확인한다. 비본문 위치 scalar만 받아 각 operand의 문서/버전/projection/evidence/element/chunk/page와 token→문자 offset·끝 범위 조건을 정확히 비교한다. 같은 evidence의 서로 다른 operand를 하나로 축약하지 않는다. nullable page의 기존 NULL 동등을 유지한다.
- claim/proof 단위 순서, evidence 단계와 operand 단계의 fresh 조회, 각 verify 호출의 새 조회와 외부 batch.revalidate/visible_run을 보존한다. 한 batch 안에서는 조회시점이 하나로 합쳐지며 membership 오류와 SQL 실패의 발견 순서는 달라질 수 있다. 오류를 성공으로 바꾸거나 숨기지 않는다.
- 원래 없던 index build active/current version 조건은 추가하지 않는다. 요청 간 ACL·receipt·위치 캐시는 사용하지 않는다.

호출 전체 union은 더 적은 SQL이 가능하지만 뒤 claim 검사를 앞당기므로 이번 최소안에서 제외한다. 효과는 전후 전체 결과 해시와 비프로파일링 시간을 비교해 판단한다.

## 작업과 인터페이스

- [x] 메인: 시작2247파일/.env 해시, 수정 전 제품 복사본, 모델0 읽기 전용 CPU 진단 확보. 제한 실행에서 멈춘 계측은 정확 신원 확인 후 종료하고 별도 증거를 남김.
- [x] 백엔드/DB: 제품은 `numeric_validation_repository.py`만. 새 `backend/tests/unit/labs/rag/generation/test_numeric_source_batch.py`에 실제 payload/receipt 기반 비용 RED를 만들고 확인 후 최소 구현. 기존 `test_numeric_validation_repository.py`의 SQL fake는 필요한 계약에 한해 갱신.
- [x] 독립 QA: numeric repository/batch/restore/proof, evaluation/executions/conversations 영향 회귀, 별도 권한/위치 변조·취소 시험, strict Mypy와 Ruff. 구현자의 성공을 독립 결과로 대체하지 않음.
- [x] 메인: 동일 도구·같은 기존 데이터로 비프로파일링 전후2쌍, 전체508건/첫25건/통계/정렬 해시와 SQL 수를 비교. hash 생성은 timer 밖. 과거13~15초와 직접 개선율 계산하지 않음.
- [x] 메인: 유휴 상태와 API/launcher 신원을 확인한 뒤 본래 동일 실행기로 적용. 기존25표/행 해시·.env 보존, health/ready/API, 로그인 목록/필터/저장 상세 검증.
- [x] 메인: ISSUE42 날짜별 진행 이력, worklog와 WORKBOARD를 검증 근거·남은 지연에 맞춰 마감. 모델 품질 통과로 확대하지 않음.

## 검증 명령

승인 Conda를 `docs/runbooks/local-development.md`대로 활성화하고 테스트 프로세스에만 합성 secret과 `PYTHONPATH`를 사용한다. task root는 `.local-data/project-agent-work/execution-numeric-read-20261026/`다.

첫 RED/GREEN: backend에서 `python -B -m pytest tests/unit/labs/rag/generation/test_numeric_source_batch.py -q --basetemp=<taskroot>/impl-pytest`. 독립 범위는 numeric·execution·평가 복원 테스트로 선택하고 고유 사례를 집계한다. unit 검사에서 DB·네트워크·모델에 연결하지 않는다. 운영DB를 읽는 전후 probe는 별도 READ ONLY 연결로 실행한다. 전체 pytest는 실사용 DB를 수정할 수 있어 실행하지 않는다.

## Review Focus

1. 동일 evidence에 정상/잘못된 두 operand, 서로 교차한 위치, NULL page, token offset/문자 끝 범위, nullable chunk/projection을 모두 거절/허용 계약대로 확인.
2. 중복 ready index build, 근거 누락/extra, actor·membership·workspace·active/ready 철회, claim밖 operand와 각 호출 사이 변경을 확인.
3. 1/64/65/129 경계, 빈 claims/operands의 source SQL0, 뒤 chunk 실패시 중단, SQL오류/CancelledError 전파 확인.
4. receipt/audit/payload 변조와 기존 schema1/2 경로, 외부 fresh 후검증 및 생성/저장 복원 경로 회귀 유지.
5. 전체 응답·판정·인용 동일, 본문 없는 증거, 기존 파일/.env/DB 보존 및 검증의 미수행 경계 명시.

## 역할과 판단

위험 높음(원문 권한·계산 근거 검증). 활성 신호 python-api-or-worker/database-or-migration/authentication-permission-or-exposure/feature-implementation/significant-change-or-merge의 필수6역할을 selector로 확인했다. 구현은 Python backend/DBA, 독립 담당은 test/security/integration/review, 메인은 설계·실측·통합·문서를 맡는다. CPU 분석은 제품 구현과 분리된 조사다. UI·AI-runtime·배포구조·외부전송 역할은 해당 변경이 없어 제외한다.
