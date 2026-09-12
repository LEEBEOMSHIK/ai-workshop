# Codex 실제 승인 저장소 연결

## 구현 목표

기존 호출 승인 gate를 실제 PostgreSQL 현재 상태 조회와 영속 단회 소비에 연결한다.
계획: `docs/superpowers/plans/2026-09-08-codex-approval-storage.md`.
역할: DB 아키텍처 검토, Python/AI·DB 구현, 메인 격리 DB 검증, 독립 보안/DB 리뷰.
실제 사용자 DB migration·문서·정책·계정·CLI/모델·UI 변경은 이번 검증에 포함하지 않는다.

## 데이터 경계

- 호출 승인: 정확한 버전/범위/모델/지침 식별자와 전송 payload digest, 명시적인 전체 입력 분류/동의.
- 근거 승인: 원본 revision ID와 SHA-256, 명시적인 공개/합성 분류와 승인자·철회 상태.
- 소비 장부: 승인 ID의 원자적 단회 예약. 본문·질문·이력·초안은 어떤 테이블에도 보관하지 않는다.
- 철회한 승인 내용을 덮어쓰거나 소비 장부를 삭제해 재사용시키지 않는다. 재승인 UI는 이번 범위가 아니다.

## 트랜잭션과 잠금

현재 상태 조회의 잠금과 실제 소비 transaction을 분리한다. 소비는 별도 DB pool에서 확정하고
callback 실패/취소로 되돌리지 않는다. 소비 테이블에는 잠긴 부모 행에 대한 FK를 두지 않아
별도 transaction이 부모 잠금을 기다리는 교착을 만들지 않는다. 검증된 source context만 소비 가능하다.

프로젝트의 기존 AssetVersion→Document 잠금 순서를 유지한다. DBA가 일반 cascade 삭제를 고려해
Document→AssetVersion 대안을 제안했으나, 현재 ingestion 수명주기와 승인된 공통 지침이 반대 순서이므로
새 adapter만 역순으로 만들지 않는다. 수동 DB cascade 삭제 등 외부 역순 작업은 bounded timeout으로
실패할 수 있으며 자동 재시도·실행 허용으로 우회하지 않는다.

전체 구성의 전송 정책/기존 외부 승인과 선택 공간의 권한을 함께 확인한다. 선택된 일부 공간만
검사해 금지된 구성 공간을 숨기지 않는다. 임시 공간 만료도 callback 직전 승인 만료에 반영한다.

## 사용자 테스트 완료 기준

DB 단위·통합 검사 통과만으로 전체 RAG 테스트 가능이라고 안내하지 않는다.
runner registry·실시간 이벤트 중단·실제 모델 확인·관리자 실행 설정·Hybrid/도메인 연결 후,
실제 질문→LLM 답변→인용/원문→후속 질문→근거 부족/실패까지 확인한 뒤 사용자에게 요청한다.

## 검증 진행과 발견 사항

- 최초 격리 DB 실행은 합성 생성 프로파일의 `citation_mode=required` 누락으로 fixture 단계에서 실패했다.
  기존 DB 제약은 그대로 유지하고 fixture를 수정한 뒤 통합 27개와 전체 unit/contract 1,225개가 통과했다.
- 독립 보안/DB 리뷰에서 사용자 지정 REPEATABLE READ 연결은 과거 정책을 읽을 수 있고,
  AUTOCOMMIT 연결은 행 잠금과 지역 timeout을 유지하지 못하는 문제를 발견했다.
  실제 드라이버 상태를 확인하는 두 회귀 테스트가 각각 의도한 원인으로 실패했다.
  snapshot과 독립 소비 양쪽에서 첫 SQL 전에 READ COMMITTED transaction을 강제하는 보완을 진행한다.
- 보완 전 전체 mypy는 218개 소스 파일, 관련 Ruff는 통과했다. 보완 후 재검증과 독립 재리뷰는 별도로 기록한다.
- 격리 수준 보완은 실제 DB 회귀 2개와 독립 재검토를 통과했다. 후속 전체 DB 실행에서 뒤늦게 추가한
  중복 근거 승인 오류 검사가 원시 SQL 예외 체인을 발견했다(28 통과·1 실패).
  async context manager 내부에서 오류를 바꾸는 것만으로는 호출부 예외 체인이 완전히 제거되지 않았다.
  공개 저장소 변경 메서드 4개의 종료 경계에 오류 정제를 추가했다. 원인 재현 단위 테스트는
  RED 1개→GREEN 30개, 실제 중복 승인 DB 회귀는 1개 통과했고 독립 재검토가 수정을 승인했다.
  `CancelledError` 전파와 기존 gate/정책/스키마 계약은 유지한다.
- 모든 DB 검증은 이름과 current_database를 확인하는 기존 격리 helper로 생성·제거했다.
  실제 사용자 DB에 0026/0027을 적용하거나 CLI/모델을 실행하지 않았다.

## 최종 검증과 인계

- 실제 PostgreSQL 격리 통합: **29 통과** (91.94초).
- 전체 backend unit/contract: **1,226 통과** (66.15초), 기존 Starlette/httpx 폐기 예정 경고 1개.
- 전체 mypy: **218 소스 파일 통과**. 변경 Python 파일·Alembic import 관련 Ruff 통과.
- 독립 DB/security 재검토: 격리 수준과 오류 체인 문제 종료, 미해결 차단 사항 없음.
- 기존 AssetVersion→Document 잠금 순서를 유지하고 독립 소비 pool로 rollback 후 replay를 방지했다.
- 이 결과는 내부 승인 저장소 단계 완료다. 실제 CLI 실행, 사용자 DB migration, 관리자/도메인 활성화와
  질문→실제 LLM 답변→인용→후속 질문 전체 흐름 검증은 아직 남아 있다.
- 다음은 runner registry·실시간 출력 검사·요청 경로 배선이다. 새 라이브러리는 추가하지 않았다.
