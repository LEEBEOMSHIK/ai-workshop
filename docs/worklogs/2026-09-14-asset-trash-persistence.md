# 휴지통 영속 기반 2B 구현 기록

- 상태: 구현·통합 검증·최종 독립 검토 완료. 실사용 DB 적용 전.
- [상세 설계](../superpowers/specs/2026-09-14-asset-trash-persistence-design.md)
- [구현 계획](../superpowers/plans/2026-09-14-asset-trash-persistence.md)

## 범위와 역할

main에서 순차 Task를 구현한다. 메인은 요구/시스템·테스트 설계와 통합/문서, Python/DB 담당은 코드와 TDD, 별도 검증자는 독립 리뷰를 맡는다.
프론트·AI 모델·Docker 변경은 없다. 실사용 DB·원본·서버·원격 저장소는 변경하지 않는다.
테스트는 기존 backend/.venv와 2A의 hardened helper UUID DB만 사용한다. 새 패키지/가상환경/컨테이너를 만들지 않는다.

## 기준선

- 기존 Assets 단위 + DB 대상 안전 검사: 225 passed, 1 warning in 8.71s.
- 경고는 기존 Starlette/httpx TestClient 사용 중단 예고다.
- 수정 전에 ai_workshop Python 프로세스를 읽기 전용 조회했으며 일치하는 실행 프로세스가 없었다. 전체 명령줄/비밀값은 출력하지 않았다.
- 로컬 PostgreSQL15432 TCP 접근을 확인했다. 실제 migration은 fixture가 생성한 DB에만 수행한다.

## 구현 결과

Task1: 고정 이름 비교와 읽기 전용 사전 검사 구현. 행동 RED 33 failed/9 passed → GREEN 42 passed. production mypy2파일·Ruff4파일 통과. 메인 재실행과 독립 리뷰 진행 중.
독립 리뷰에서 비활성 항목의 비정규/빈 이름 누락과 빈PG/깊은트리 검증 공백을 발견했다. 비활성 실패 RED를 재현한 뒤 검사 범위를 고쳤다.
2,500단계 acyclic 및 2,500단계 말단 cycle과 빈 DB의 안전 오류를 추가 검증했다. btrim 사례를 같은 DB에서 반복해 의미를 유지하면서 42→38 tests, 10→6 격리 DB로 줄였다.
보완된 suite 메인38 passed in 18.40s, mypy/Ruff 통과. 수정 범위 재리뷰에서3건 모두해결·신규지적없음. 로컬 커밋8d73e60.
Task2: 0035 상태/정책/배치 구현·독립 리뷰 완료. 지정PG6건(메인18.99s)·관련회귀18건·mypy5파일·Ruff통과.
추가 API 테스트 실패를 조사해 합성secret 실행설정 누락과 기존 metadata_revision 기대값 누락을 확인했다. 업무API는바꾸지않고 test_asset_api.py 한파일의설정격리/기대값을보완했다.
보완후API3건(메인7.98s,기존warning1)·관련묶음14건·추가diff독립리뷰통과. 로컬커밋306af46.
리뷰 비차단 메모: lifecycle부정입력은folder중심, unsafe downgrade는policy-only대표경로라 최종전체리뷰에서추가테스트필요성을평가한다.
Task3: 전용 purge job/outbox 저장을 구현했다. 구현자 테스트 5건, mypy 5파일, Ruff를 통과했고 메인 재실행도 5 passed in 14.28s다.
ORM의 dispatch 복합 인덱스 누락을 발견해 별도 실패 테스트로 재현하고 DB 스키마와 일치시켰다.
독립 리뷰는 설계 일치 PASS, 검증 보완 필요로 판정했다. 다른 공간의 동일 요청 키 허용 및 정책만 존재하거나 원문 세대만 변경된 경우의 downgrade 거부를 보강한다.
상태 CHECK의 명명된 정의와 ORM/DDL 일치 검증도 보완 대상으로 전달했다. 아직 Task3 완료로 마감하지 않았다.
Task3 보완 후 메인 5 passed in 22.33s. 재검토에서 중요 2건 해결 및 신규 중요 문제 없음을 확인했다. 전체 ORM/DDL parity 회귀 확장 제안은 최종 검토에 남긴다.
Task3 로컬 커밋 4a8ba7c. Task4 활성 폴더 고유성 및 전체 migration 회귀 구현을 별도 Python/DB 담당에게 배정했다.
Task4 구현자 관련 240건 및 production mypy 5파일·Ruff 통과. 메인 통합 첫 실행은 327 passed/2 failed였으며, 기존 파일함 테스트의 같은 공간 동명 root 2개 fixture가 새 제약에 걸렸다.
해당 테스트의 폴더명만 서로 다르게 수정하고 문서 동명·페이지네이션·동시 생성 단언은 유지했다. 보완 2건 통과 후 전체 재실행과 독립 리뷰를 진행한다.
Task4 최종 11파일 독립 검토는 Spec PASS / Quality Approved, 지적 없음이다. 로컬 커밋 dcac68f.

## 통합 검증

- 메인 최종 실행: Assets 단위, 격리 DB 대상 안전, 신규 사전검사/상태/작업/마이그레이션, 기존 API·파일함·휴지통 및 구성원 권한을 묶어 **329 passed, 1 warning in 136.70s**.
- 경고 1건은 기준선과 동일한 Starlette/httpx 사용 중단 예고다. 의존성 변경이나 경고 숨김은 하지 않았다.
- 변경 production·migration 14파일 mypy: 오류 없음. 변경 Python 23파일 Ruff: 통과.
- 전체 23파일 최종 독립 리뷰 승인. Critical/Important 없음. 실제 DB 적용/삭제 실행/서버 재시작/푸시는 하지 않았다.
- 비차단 후속: 0035 문서 상태 조합/독립 세대 변경 테스트와 0036 전체 ORM/DDL parity 자동 검증 보강. 현재 구현 불일치나 실제 결함은 발견되지 않았다.
- 로컬 코드 커밋: 8d73e60 → 306af46 → 4a8ba7c → dcac68f.

## 다음 경계

이 단계는 저장 기반이다. 실제 휴지통·복원·영구 삭제 API/UI와 검색·worker 차단, provenance/최소 삭제 증명은 별도 후속이다.
다음 활성 작업은 2C의 삭제 대상·복제본 추적과 최소 삭제 증명 계약이다. 이후 조회·검색·작업자 차단, 명령과 UI를 순차 연결한다.
새 소스를 실행하기 전 대응 migration 적용이 필요하다. 실사용 DB는 이번 작업에서 변경하지 않았으며 기존 0034에 새 모델 서버를 그대로 시작하면 안 된다.
완료한 합성 DB는 hardened helper가 정확한 생성 대상만 정리했다. 사용자 자료·기존 미커밋 UI·references는 보존했다.
