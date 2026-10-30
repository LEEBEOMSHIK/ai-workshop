# 대화 원문 조회 개선: 한 차례 시도

2026-10-26 · ISSUE-00042. 사용자 지시: 다음 성능 작업까지 수행하고 효과나 동등성이 입증되지 않으면 보류한 뒤 다음 프로젝트 작업을 확인한다.

## 목표와 선택

새 READ ONLY 진단에서 전체508건·대화25건, 대화SQL295회 중 documents93/workspaces31/conversations62/audit36/profile36/profile bindings36을 확인했다. 제품은 `conversations/access.py`의 `visible(..., external=False)` 원문 단계만 변경한다. 요청 공간/선택 문서 검사를 유지하고 정확 document/version/projection을 최대64개씩 tuple IN으로 조회해 반환3열의 집합을 전체 비교한다.

현재 active/ready/workspace 권한 JOIN과 매 호출 새 source 추출/session을 유지한다. historical version에 새 active_version/indexbuild 조건이나 source의 선택공간 소속 조건은 추가하지 않는다. empty source라도 요청 공간 검사는 수행한다. `external=True`의 원문→승인 단건 교대 경로와 provider/status/revoked/SHA 검사는 그대로 둔다. dependency closure·최초/최종 find·숫자 검증·상세 반환 전 검사·생성/검색/인용/품질 기준은 변경하지 않는다. batch 안의 권한 관측은 단일 statement 시점으로 합쳐진다.

profile 설정 scalar 조회와 복원/병렬 처리 재설계는 이번 안과 혼합하지 않는다. CPU 직렬화 대안은 이전 조사에서 기각됐다. 새 모델/계정/DB/설치/migration/commit/push/캐시 삭제0. 본래 누적 checkout의2250파일/.env SHA와 변경 전 소스를 보존한다.

## 수용·보류 기준

후보 하나, 독립 회귀 후 같은 기존 데이터의 profiler 없는 before/after 교대2쌍으로 비교한다. 전체508건·대화25건/첫25건의 응답·통계·정렬 해시가 동일하고, source SQL이 감소하며 두 쌍 모두 대화 조회 시간이 줄고 전체 평균이 악화되지 않으면 본래 API 반영을 검토한다. 통과해도 잔여 속도 후보를 자동으로 이어서 수정하지 않는다.

권한·기능 동등성 실패 또는 위 실측 효과가 불명확하면 운영 반영 전에 이 작업의 코드만 정확한 시작 복사본으로 되돌린다. 실패/미채택 근거와 ISSUE42 보류 범위를 기록한다. 테스트·실측을 반복해 유리한 결과를 선택하지 않는다. 다음 프로젝트 순서는 기존 완료 기록을 확인한 후 별도 명시하며 실모델/새 후보 승격을 자동 수행하지 않는다.

최종 결정: 방향상 하한은 충족했으나 전체평균72.9ms(0.99%) 감소가 기준선표본차267.7ms보다 작고 첫쌍은 회귀해 실효과 입증이 불충분하다. 사용자 지시에 따라 미채택·제품 원복·후보 증거 보존·추가 성능 작업 보류로 마감했다. 본래API 재시작 없이 기존회귀27 및 파일/DB/.env 보존을 확인했다. 다음 SDK 턴 연결·문맥 관측 범위는 확인만 했으며 구현하지 않았다.

## 작업

- [x] 시작 파일·.env/원본 보존 및 기존25표2560행/실행중0 읽기 전용 확인, SQL 비용 분리.
- [x] 구현: 신규 `backend/tests/unit/labs/rag/conversations/test_access_source_batch.py`에1/64/65/129 비용 RED, 정확tuple/누락/교차/중복·빈source·space/selected early return·호출간철회·externalTrue 회귀 후 `access.py` 내부 최소 helper. 기존 테스트는 필요한 fake 반환만 조정.
- [x] 독립 보안/회귀: SQL ACL AST/actor·exacttuple, source error/cancel/session종료, dependency·최종find·외부승인 경계, scoped Mypy/Ruff 및 검증 시점 SHA.
- [x] 메인: 동일도구 교대2쌍 시간·쿼리·전체해시 비교 후 채택/보류 결정. profiler와 hash생성 시간은 제외.
- [x] 채택 시 유휴와 정확 본래 API/launcher 확인 후 동일 실행기 적용, health/ready/API·25표/.env·로그인 목록/필터/저장상세 검증. 보류 시 운영 재시작 없음.
- [x] ISSUE42/WORKBOARD/worklog 마감 및 다음 작업 확인. 과거 첫입력 지연·정답0/2는 개선으로 표시하지 않음.

## 검증과 역할

기존 승인 Conda/runbook, 합성 secret, task-local basetemp로 offline 단위 검사를 실행한다. 최초 RED는 backend에서 `python -B -m pytest tests/unit/labs/rag/conversations/test_access_source_batch.py -q --basetemp=<taskroot>/impl-pytest`다. 영향 회귀는 conversations access/history와 executions dependency/read/trace, 제품1파일 Mypy·변경파일 Ruff로 제한한다. 실제 DB는 메인의 READ ONLY 계측만 사용한다.

위험 높음: 현재권한. selector 필수6역할 Python/DBA/test/security/integration/independent review를 확인했다. 구현자와 검증자를 분리하고 메인은 통합·실측·문서, 별도 읽기 담당은 다음 작업의 최신 상태를 확인한다. UI·모델 runtime·배포 구조는 범위에 없어 제외한다. 공개계약·아키텍처 변경이 없어 새 ADR은 작성하지 않는다.
