# Codex 호출 승인 검사 Implementation Plan

상태: 구현·독립 재검토 완료. 신규 56개·전체 1,196개 테스트 통과. 실제 DB/CLI adapter 배선은 제외.
검증 정본: `docs/worklogs/2026-09-08-codex-call-authorization.md`.

**Goal:** 실제 프로세스를 연결하지 않고 호출별 승인 검증과 단회 실행 경계를 구현한다.
**Architecture:** RAG generation 내부 typed 요청/현재 승인 snapshot과 서버 전용 승인 저장소 port를 둔다.
검사부터 승인 소비·서버 operation 종료까지 저장소의 잠금 context 안에서 수행한다.
**Tech Stack:** Python dataclass, async context manager Protocol, pytest; 새 의존성 없음.
**Spec:** `docs/superpowers/specs/2026-09-07-personal-codex-exec-rag-design.md` §4·6·10,
`docs/worklogs/2026-09-08-codex-pre-execution-check.md`의 다음 구현.

## Global Constraints

- main-only, 기존 dirty 변경 보존. commit/push/worktree 생성 없음.
- 실제 CLI·모델·인증·사용자 DB 호출/변경 없음. 등록/runtime/readiness 차단 유지.
- API에서 snapshot이나 operation을 받지 않는다. 승인 저장소 port는 서버 신뢰 경계이며 fake 구현은 tests에만 둔다.
- HTTP 실행 계약은 수정하지 않는다. 실제 DB adapter/검색·평가·연결 검사 배선은 후속이다.
- 원문·질문·환경/비밀값을 repr/오류에 담지 않는다. 모델명·예산은 하드코딩하지 않는다.

## Task 1: 호출 승인 계약과 검사기

Create `backend/src/ai_workshop/labs/rag/generation/codex_authorization.py`.
Test `backend/tests/unit/labs/rag/generation/test_codex_authorization.py`.

공개 인터페이스는 다음 책임을 가진 typed dataclass/enum/Protocol로 제한한다.

- 호출 operation 종류: 검색/평가/연결 검사, stage: contextualize/generate. 문자열 자유 입력 불가.
- 불변 intent: actor UUID, request UUID, operation/stage, configuration/deployment/profile UUID,
  runner 참조/모델 ID/지침·schema digest, 전체 선택 공간과 정책 version mapping, installation정책/generation고지 version,
  전체 evidence asset revision UUID+content SHA256, 승인 ID. tuple/frozen 구조로 mutable 입력 보관 금지.
- 실제 전송 payload: stdin bytes와 developer instructions bytes, schema bytes를 별도
  length-framed SHA256으로 결합. digest는 검사기가 실제 전달할 bytes로 계산한다.
  payload dataclass repr=False. 모든 외부 전송 metadata는 이 실제 bytes 안에 있어야 한다.
- current snapshot: 서버 조회 actor의 active/owner, environment, 현재 exact intent binding,
  승인자 UUID, awareUTC 유효기간, revoked, consent, revision별 public/synthetic 승인분류와 동일SHA256,
  허용된 전체 공간, 승인된 payload digest. 사용자 주장만으로 구성하지 않는다.
  현재 provider 전송 정책의 allowed 판단도 독립 검증한다. version 일치만으로 금지 정책을 허용하지 않는다.
- `CodexAuthorizationSource` Protocol의 `locked_snapshot(intent)` async context manager가
  current snapshot을 제공한다. 해당 context 안에서 `consume(approval_id, request_id, stage)`가
  원자적으로 단회 소비하며 이미 소비됐으면 False. 잠금·소비의 실제 DB 구현은 이번에 제공하지 않는다.
  consume은 operation 실패/취소 및 context 종료 오류에도 되돌아가지 않는 영속 소비 계약이다.
- `CodexExecutionGate.run(intent, payload, operation)`은 source와 주입 clock을 사용한다.
  snapshot 조회→검사→단회소비→operation(payload) 순서. operation은 서버가 전달한 async callable이다.
  불허/누락/만료/불일치면 callback 호출0. 소비 후 operation 실패/취소에도 승인 재사용 금지.
  operation은 검증한 동일 불변 payload를 받는다. gate는 프로세스·DB·UI를 직접 호출하지 않는다.
- 검사: development만, 현재 active owner와 actor/승인자 일치, request/종류/단계/모든버전/runner/model/digest
  exact match, 전체공간 일치(금지공간 일부제거 금지), 중복공간/승인revision 거절, revision승인분류는
  public/synthetic만, 질문/이력/지침을 포함한 payloaddigest exact match, aware시간 issued<=now<expires,
  현재 revoke/consent 검사. 연결검사 합성입력은 evidence가 비어도 payload 승인 필수.
- 안정적인 enum 오류코드만 노출. payload 포함 예외 원문을 승인 오류로 그대로 감싸지 않는다.

TDD 순서:

- [x] 모듈 존재 assertion 실패 후 최소 모듈 작성, 행동 테스트 실패부터 추가한다.
- [x] 실제 검사기를 in-memory async 잠금 source와 연결해 아래 행동을 검증한다.

```python
async def test_denied_actor_never_invokes_operation():
    # fixture는 서버 snapshot의 active=False. operation은 호출되면 pytest.fail.
    with pytest.raises(CodexAuthorizationError):
        await gate.run(intent, payload, forbidden_operation)
```

- [x] 성공·비로그인/다른actor/member/비활성/운영/만료/미동의/철회/버전변경/모델변경/
  다른stage·request·operation/한byte payload변경/공간누락·중복·금지혼합/revision변경·비공개를 검사한다.
- [x] 동일 승인 재사용과 동시호출은 한 번만 operation 실행. 실패·취소 후에도 재사용하지 못한다.
- [x] 거절 시 operation 미실행, 성공 시 source context 안에서 같은 payload 전달을 검사한다.
- [x] 신규 테스트, 기존 generation/deployments/policies 회귀, mypy/Ruff를 실행한다.

## Task 2: 독립 리뷰와 메인 검증

메인은 코드와 tests를 독립 보안 reviewer에게 전달한다. 실제 DB 구현 없이 production 연결 완료라고
하지 않는다. 전체 unit/contract를 합성 테스트 secret 설정으로 실행하고 worklog/WORKBOARD를 마감한다.
검증 명령: backend `.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q`,
`.venv/Scripts/python.exe -m mypy src`, 관련파일 `ruff check`.
