# Codex 실행 설정 저장 경계 Implementation Plan

**Goal:** HTTP endpoint와 Codex runner 참조를 구분하고 아직 검증되지 않은 CLI 실행은 차단한다.
**Architecture:** 기존 RAG Deployment 불변 버전을 확장한다. 기존 HTTP provider 계약과 정책 잠금을 유지한다.
**Tech Stack:** Python dataclass/Pydantic, SQLAlchemy, Alembic, pytest.
**Spec:** `docs/superpowers/specs/2026-09-07-personal-codex-exec-rag-design.md` §6·8·11, ADR-0017.

**Status:** 저장 계약과 fail-closed 경계 구현·검증 완료. 전체 unit/contract 1,140개,
격리 DB 4개, frontend 43개, mypy 214개·TS/API/관련 린트 통과.
실제 사용자 DB 적용과 CLI 실행은 제외했다. 독립 리뷰의 Workspace-only downgrade 테스트
분리 공백은 worklog에 남겼다. 상세: `docs/worklogs/2026-09-08-codex-deployment-boundary.md`.

## Global Constraints

- 사용자 지시대로 main에서만 작업하며 관련 없는 변경을 보존한다. 자동 commit/push 없음.
- 실제 모델·인증 호출, 실제 애플리케이션 DB migration·설정 등록은 하지 않는다.
- `development_codex_exec`는 development-only, external, 공식 CLI 인증, 자동 재시도 0이다.
- endpoint_ref에 가짜 URL/runner 문자열을 넣지 않는다. 모델명은 설정 값이며 코드에 고정하지 않는다.
- 이 단위는 저장/실행 차단 경계다. owner·입력 revision 승인·실제 identity가 검증되기 전 실행하거나 ready로 표시하지 않는다.

## Task 1: domain/DB/serialization과 fail-closed 실행

수정 범위: `deployments/{domain,models,repository,schemas,service}.py`,
`generation/runtime_resolver.py`, 필요한 경우 `generation/readiness.py`, `policies/models.py`.
신규 migration: `backend/alembic/versions/0026_codex_runner_reference.py` (down_revision 기존 head 확인).
테스트: 기존 deployment/policy/generation 단위·계약 검사와 신규 migration 통합 검사.

- [ ] 기존 HTTP 생성/직렬화, Codex 올바른 설정과 부정 사례를 실패 테스트로 작성한다.
- [ ] ProviderKind에 DEVELOPMENT_CODEX_EXEC를 추가한다.
- [ ] ModelDeploymentVersion.endpoint_ref를 str|None으로, runner_ref를 기본 None인 별도 필드로 추가한다.
  HTTP는 nonempty endpoint/runner None, Codex는 endpoint None/nonempty runner를 강제한다.
  runner_ref는 기존 안전한 참조 이름 규칙을 재사용하며 경로/URL/임의 명령이 아니다.
- [ ] Codex는 external_transfer=True, location EXTERNAL, development_only=True,
  allowed_environments=(DEVELOPMENT,), secret_ref=None, max_retries=0, retry_backoff_seconds=0,
  healthcheck_enabled=False를 강제한다. 기존 외부 고지와 전송항목 필수 계약을 유지한다.
- [ ] ORM/repository 양방향 직렬화와 create builder에 runner_ref를 연결한다.
- [ ] 새 migration으로 endpoint nullable/runner nullable/provider 제약을 확장한다.
  명명된 CHECK로 HTTP/Codex 참조 상호배타 및 Codex 제한을 DB에도 강제한다.
  기존 Installation/Workspace 정책 JSON provider 허용 제약에도 새 provider를 추가하되 기존 승인 값은 바꾸지 않는다.
  downgrade는 Codex deployment 또는 Codex 승인 정책 행이 있으면 삭제하지 않고 명시 실패한다.
  기존 행이 없는 경우에만 nullable/제약을 되돌린다. 기존 migration 파일은 수정하지 않는다.
- [ ] 등록 서비스는 runner registry/실행 게이트가 미완성이므로 Codex 등록을 안정적인
  `deployment_not_ready`로 거부한다. 기존 HTTP 참조 검사는 그대로다.
  runtime resolver는 custom factory가 주입되어도 Codex를 endpoint/secret 해석 전에 차단한다.
  관리자 metadata readiness도 Codex에 ready 과거행이 있어도 false로 표시한다.
- [ ] 신규 및 관련 테스트, 전체 unit/contract, mypy와 Ruff를 실행하고 독립 보안/DB 리뷰한다.

```python
def test_codex_uses_runner_not_http_endpoint():
    deployment = create_deployment(
        provider=ProviderKind.DEVELOPMENT_CODEX_EXEC,
        endpoint_ref=None,
        runner_ref="personal-codex-v1",
        secret_ref=None,
        development_only=True,
        allowed_environments=(DeploymentEnvironment.DEVELOPMENT,),
        max_retries=0,
        retry_backoff_seconds=0,
        healthcheck_enabled=False,
    )
    assert deployment.endpoint_ref is None
    assert deployment.runner_ref == "personal-codex-v1"
```

위 테스트는 기존 `tests/unit/labs/rag/deployments/test_domain.py`의 create_deployment helper를 사용한다.

기존 HTTP 필드·provider 응답은 유지한다. API enum 확장 때문에 생성 타입 변경이 필요하면
부모에게 보고하여 지정 생성 명령으로 함께 갱신하며 임의 UI를 만들지 않는다.

## Task 2: 검증과 인계

메인은 실제 정책 잠금과 이번 변경의 범위를 worklog/WORKBOARD에 기록한다.
격리 DB 테스트의 적용/rollback 절차를 확인하고 실제 사용자 DB와 구분한다.
격리 DB가 사용 불가하면 migration은 작성·오프라인 검증 상태로만 보고하며 적용 완료라고 하지 않는다.
다음은 runner registry와 owner/전체 입력 승인 snapshot을 결합한 실행 경계다.
