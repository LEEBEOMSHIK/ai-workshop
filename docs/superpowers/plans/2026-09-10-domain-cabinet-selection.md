# 도메인 파일함과 선택 문서 대화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. 각 작업은 TDD와 독립 검토를 거친다.

**Goal:** 도메인 안의 회사·개인 파일함에서 선택한 기존 문서만으로 대화하며, 대화 중 기존 문서를 추가할 수 있게 한다.

**Architecture:** Platform 문서 라이브러리를 RAG 도메인 조립 계층에서 재사용한다. 선택 문서 제한은 요청부터 활성 원본/색인 선필터와 assistant 서명까지 전달한다. 원본 열람과 생성 준비를 분리한다.

**Tech Stack:** 기존 Next.js/React/TypeScript, FastAPI/Pydantic/SQLAlchemy, PostgreSQL, Elasticsearch, pytest/Vitest. 새 dependency 없음.

**Spec:** `docs/superpowers/specs/2026-09-10-domain-cabinet-conversation-design.md`, ADR-0023. 상세 문서 사용자 승인: 2026-09-10.

**실행 상태:** Task1–4 코드·자동 검증·독립 검토 완료. Task5 합성 수용 검증과 최종 재검토 완료;
승인된 백엔드 재시작·새 API 반영은 확인했고 로그인된 실제 화면 검증은 대기 중이다. 전체 계획을 실제 사용자 검증 완료로 표시하지 않는다.
최종 결과와 잔여 사항은 [작업 기록](../../worklogs/2026-09-10-domain-cabinet-selection.md), 다음 순서는 `WORKBOARD.md`를 따른다.

## Global Constraints

- main에서만 작업하며 기존 dirty 변경을 보존한다. 커밋·push·worktree·실사용 DB migration은 이번 실행에서 하지 않는다.
- 이번 계획은 상세 설계 7절의 **1단계**다. 개인 자료는 기존 도메인/구성에 연결된 허용 개인 공간까지만 지원한다.
- 신규 임시 첨부, 사용자별 동적 도메인 자료 연결, 영속 대화 소유권/만료/개인 보관은 별도 2단계다. 가짜 첨부 버튼을 만들지 않는다.
- 도메인은 권한이 아니다. 모든 선택 문서를 현재 권한·도메인·구성·공간/폴더에 대조한다.
- `document_ids` 생략만 기존 범위를 의미한다. 명시 null/빈 배열은 422, 권한/소속/부재는 일반404, 적격 색인 미준비는409다.
- 선택 실패 시 전체 요청을 중단한다. 부분 문서만 사용하거나 전체 공간 검색으로 확대하지 않는다.
- 원본 열람은 LLM 준비나 외부 동의를 요구하지 않는다. 문서 선택은 외부 전송 승인이 아니다.
- 테스트는 합성 자료와 mock 또는 격리 저장소만 사용한다. 기존 실사용 서비스·문서·계정과 모델 호출은 변경하지 않는다.
- 임시 인계 기록은 `.local-data/project-agent-work/domain-cabinet-selection/`만 사용한다. 성공 기록 정리는 기존 정책대로 한다.

## 공용 인터페이스와 파일 책임

다음 이름은 새 계약이다. 구현 시 한 곳에서 정의하고 다른 작업이 복제하지 않는다.

```python
# labs/rag/retrieval/domain.py
@dataclass(frozen=True, slots=True)
class SelectedDocumentIdentity:
    document_id: UUID
    asset_version_id: UUID
    projection_id: UUID
    index_build_id: UUID

# 기존 ResolvedSearchScope에 append (기존 positional 생성 호환 유지)
document_ids: tuple[UUID, ...] | None = None
selected_documents: tuple[SelectedDocumentIdentity, ...] = ()
scope_fingerprint: str | None = None
```

`None`은 내부적으로 미제한 모드만 나타낸다. 요청 schema는 명시 null을 거절한다.
문서 개수 상한은 `rag_selected_documents_max_count` typed setting(초기100)으로 관리하고
파일함 문맥 응답의 `selection_limit`으로 UI에 전달한다. 정렬·중복 제거한 원소 수 기준이며 큰 raw 배열도
기존 요청 크기 보호와 함께 상한 검사한다. 이 제한은 검색 top_k와 다르다.

```typescript
// OpenAPI 생성 타입에서 추출하여 사용, 별도 수기 DTO 복제 금지
type Selection = { documentIds: string[]; documentNames: string[] } | null;
// null = 공간/폴더 범위. { documentIds: [] }는 전송 불가.
```

## Task 1: 검색 요청과 활성 문서 범위

**Files:**
- Modify: `backend/src/ai_workshop/config.py`
- Create: `backend/src/ai_workshop/labs/rag/retrieval/selection.py` — 요청 선택 검증·정규화·지문 계산의 순수 함수
- Modify: `backend/src/ai_workshop/labs/rag/retrieval/domain.py`, `scope.py`, `service.py`
- Modify: `backend/src/ai_workshop/labs/rag/search/schemas.py`, `service.py`
- Modify: `backend/src/ai_workshop/labs/rag/domains/schemas.py`, `service.py`, `api.py`
- Test: `backend/tests/unit/labs/rag/retrieval/test_scope.py`
- Create test: `backend/tests/unit/labs/rag/retrieval/test_document_selection.py`
- Modify test: `backend/tests/integration/labs/rag/retrieval/test_search_scope_repository.py`

**Interfaces:** 양쪽 검색 DTO에 `document_ids: list[UUID] | None = None`을 추가하고 before validator로 명시 null/빈 배열을 거절한다.
내부 SearchRequest 조립에서는 미선택일 때 이 키를 생략하고 선택 시에만 포함한다. `resolve`와 검색 포트에
`document_ids: tuple[UUID, ...] | None = None`, `document_processing_profile_id: UUID | None = None`을 추가한다.
제한 검색에서 처리 profile이 없으면 구성 오류로 중단한다. 실제 profile은 `configuration.active_index_alias.document_processing_profile_id`에서 전달한다.

- [ ] RED: 새 schema 테스트에서 양쪽 DTO의 null/빈 배열 거절과 생략 호환을 검사한다.

```python
@pytest.mark.parametrize("request_type", [SearchRequest, DomainSearchRequest])
@pytest.mark.parametrize("invalid", [None, []])
def test_explicit_empty_document_selection_is_rejected(request_type, invalid):
    base = dict(query="합성 질문", workspace_ids=[uuid4()])
    base["configuration_id" if request_type is SearchRequest else "connection_version_id"] = uuid4()
    with pytest.raises(ValidationError):
        request_type(**base, document_ids=invalid)
```

- [ ] 실행: `backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/labs/rag/retrieval/test_document_selection.py -q`.
  예상 실패는 현재 명시 null/빈 선택이 무시되거나 허용되는 점이다. import/환경 오류를 RED로 세지 않는다.
- [ ] 원본 문서 소속 조회를 READY 조회와 분리한다. `find_document_locations(document_ids)`는
  `(document_id, workspace_id, folder_id)`를 반환하고 resolver가 현재 승인 공간/폴더와 전부 대조한다.
- [ ] SQL의 활성 lifecycle 조회에 문서 제한과 정확한 처리profile을 추가한다. 선택 모드의 적격 결과는
  SelectedDocumentIdentity를 반환하며 document 집합이 요청 집합과 다르면 `selected_documents_not_ready`409다.
  여러 활성 build가 충돌하면 임의 선택하지 않고 같은 준비 오류로 중단한다.
- [ ] identity를 document UUID 기준 정렬하고 안정 직렬화한 데이터의 SHA-256을 fingerprint로 만든다.
  scope의 asset/build 목록은 이 identity에서 파생한다. 기존 비제한 경로와 frozen evaluation은 그대로 유지한다.
- [ ] 검색 서비스가 선택 해석을 generation/contextualization 전에 실행하게 한다. `_ResolvedScopeResolver` 재사용 검사에도
  document_ids를 포함해 나중 검색 단계가 다른 선택으로 바뀌지 않도록 한다. ES 기존 build_scope_filter를 재사용한다.
- [ ] GREEN: 단위 scope/selection 및 격리 SQL 테스트로 미준비 혼합, 부재/타사용자/폴더 불일치, 처리profile 불일치,
  활성 버전 교체, 중복 선택, 전체 선택 누락을 검사한다. 선택 외 문서의 asset/build가 필터에 없는지 단정한다.
- [ ] 독립 검토: 공통 SearchRequest가 제한을 무시하지 않는지, 404 전에 READY 여부를 노출하지 않는지 확인한다.

## Task 2: 대화 서명과 응답의 실제 범위

**Files:**
- Modify: `backend/src/ai_workshop/labs/rag/generation/integrity.py`
- Modify: `backend/src/ai_workshop/labs/rag/search/service.py`, `schemas.py`
- Modify: `backend/src/ai_workshop/labs/rag/domains/api.py`, `schemas.py`
- Test: `backend/tests/unit/labs/rag/generation/test_turn_integrity.py`
- Test: `backend/tests/unit/labs/rag/domains/test_scope_integrity.py`
- Create test: `backend/tests/unit/labs/rag/search/test_selected_scope_history.py`

**Interfaces:** ConversationScopeBinding에 선택 모드·정규화 document_ids·scope_fingerprint를 추가한다.
선택 모드는 서버에서 resolver 결과를 얻은 뒤 binding을 완성한다. SearchResult에는 선택 scope의 실제 identity와
fingerprint를 추가하고 응답 `selected_scope`에 전달한다. 비제한 응답은 null이다.

- [ ] RED: 현재 signer가 문서/버전 변경을 구별하지 못하는 회귀 테스트를 작성한다.

```python
# 기존 signer/turn fixture에 새 scope 필드를 넣어 두 경우가 달라야 함을 단정한다.
assert signer.sign_scoped(**same_turn, scope=selected_a) != signer.sign_scoped(**same_turn, scope=selected_b)
assert signer.sign_scoped(**same_turn, scope=selected_a) != signer.sign_scoped(**same_turn, scope=selected_a_new_version)
```

`same_turn`은 content,actor_id,turn_id,configuration_version_id가 같은 합성 값이다.
`selected_a/b`는 문서 ID만, `selected_a_new_version`은 서버 지문만 다른 binding으로 구성한다.
- [ ] 새 서명 payload는 v3와 제한 모드를 명시한다. 비제한 기존v2 호환은 유지하되 v2를 제한 요청에 받지 않는다.
  선택이 명시된 공통 검색의 구형 무범위 history도 거절한다. 도메인 경로에서는 v3로만 후속 질문을 이어간다.
- [ ] 이전 버전 지문 history의 실패는 `conversation_scope_changed`409로 응답하고 모델을 호출하지 않는다.
  잘못된 서명 일반 오류와 구분하되 비공개 선택 상세를 오류에 넣지 않는다. UI는 사용자 재시작 없이 자동 재전송하지 않는다.
- [ ] UI에서 이전 질문·답변을 새 구간에 보내지 않더라도 사용자 history는 임의 입력임을 유지한다.
  기존 외부 전송/구성 전체 승인 검사를 약화하지 않으며 실제 payload digest 검증은 유지한다.
- [ ] GREEN: `backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/labs/rag/generation/test_turn_integrity.py backend/tests/unit/labs/rag/domains/test_scope_integrity.py backend/tests/unit/labs/rag/search/test_selected_scope_history.py -q`.
- [ ] 독립 보안 검토: 서명 재사용·활성 버전 변경·모델 호출 전 차단 및 응답 범위가 server-derived임을 확인한다.

## Task 3: 도메인 파일함 읽기 계약

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/domains/library.py`, `library_api.py`
- Modify: `backend/src/ai_workshop/labs/rag/domains/service.py`, `schemas.py`, `api.py`
- Reuse without domain imports: `backend/src/ai_workshop/platform/assets/library.py`, `library_api.py`
- Create test: `backend/tests/unit/labs/rag/domains/test_library.py`
- Create test: `backend/tests/integration/labs/rag/domains/test_library_api.py`

**Interfaces:** `DomainService.resolve_library(slug, actor_id)`는 domain/connection 식별성과 허용 workspace_options를 반환한다.
`resolve_search`를 호출하지 않는다. 외부 모델 준비를 조회하기 위해 무거운 runtime을 만들지 않는 metadata 경로를 사용한다.
활성 도메인과 정확한 연결/구성의 허용 공간은 검사하되 생성 readiness는 열람을 차단하지 않는다.

도메인 router 하위 read-only API:

```text
GET /{slug}/library
  -> domain_id, display_name, connection_version_id, workspace_options, selection_limit
GET /{slug}/library/workspaces/{workspace_id}
  -> 기존 LibraryPage 응답; 기존 folder_id 및 페이지 cursor 계약 재사용
GET /{slug}/library/workspaces/{workspace_id}/documents/{document_id}
  -> 기존 DocumentSummary; 원문/버전은 기존 Platform 권한 endpoint 재사용
```

- [ ] RED: mock configuration에서 생성 미준비인데 domain library 조회가 성공해야 하는 테스트와,
  타 domain 공간 조회가404인 테스트를 작성한다. Platform LibraryService stub 호출 여부도 단정한다.
- [ ] RAG 소유 DomainLibraryService가 먼저 도메인 허용 공간을 검증한 후 Platform LibraryService에 위임한다.
  입력 folder/cursor는 Platform의 기존 scope binding을 유지한다. domain endpoint를 단순 프론트 필터로 대체하지 않는다.
- [ ] 파일 목록은 원본 상태만 정확히 표시한다. 원본READY를 검색READY로 바꾸어 쓰지 않는다.
  미준비 선택의 구체 확인은 Task1검색 gate에서 보장하고 UI에 안전한 준비 오류를 안내한다.
- [ ] GREEN: 새 unit과 격리API 테스트에서 폴더/문서 직접 URL, 과거 버전 열람, 모델 미준비, 도메인 변경을 검증한다.
- [ ] API 생성: `pnpm --dir frontend api:generate`, `pnpm --dir frontend api:check`.
  생성 스크립트가 로컬 backend 모듈에서 schema를 만드는 기존 설정을 먼저 확인하고 실사용API 의존이 없음을 확인한다.
- [ ] 독립 검토 후 생성 타입과 backend 계약을 Task4에 인계한다. 이 시점에는 사용자 화면 완성으로 보고하지 않는다.

## Task 4: 파일함·대화 화면 연결

**Files:**
- Create: `frontend/src/app/(workspace)/workshop/rag/domains/[slug]/files/page.tsx`, `page.test.tsx`
- Create: `frontend/src/features/rag/domains/DomainFileCabinet.tsx`, `DomainFileCabinet.module.css`, `DomainFileCabinet.test.tsx`
- Create: `frontend/src/features/rag/domains/DomainNavigation.tsx`, `DomainNavigation.test.tsx`, `library-api.ts`
- Create: `frontend/src/features/rag/conversation/DocumentSelectionPanel.tsx`, `DocumentSelectionPanel.test.tsx`
- Modify: `frontend/src/features/assets/DocumentBrowser.tsx`, `DocumentBrowser.test.tsx` — 일반 주입 port/선택 slot만 추가
- Modify: `frontend/src/features/rag/domains/DomainPickerPage.tsx`, `DomainPickerPage.test.tsx`
- Modify: `frontend/src/features/rag/conversation/ConversationPage.tsx`, `ConversationPage.test.tsx`, `ScopeSelector.tsx`, `types.ts`, `api.ts`
- Modify: `frontend/src/app/(workspace)/workshop/rag/domains/[slug]/chat/page.tsx`, `page.test.tsx`
- Modify: `frontend/src/shared/routing/routes.ts`

**Interfaces:** 도메인 shell은 파일함/대화 두 메뉴와 현재 표시명을 공유한다. `ragDomainFilesPath(slug)`를 route helper로 추가한다.
DocumentBrowser는 RAG를 import하지 않고 주입한 browse/getDocument 함수와 optional selection callback을 사용한다.
기본 props는 현재 Platform 동작을 유지한다. 도메인 wrapper가 domain API와 workspace_options를 주입한다.
선택 상태는 현재 domain/connection에 묶고, 파일함→chat 전달에는 UUID 목록만 query로 전달한다.
새 chat page는 metadata를 서버에서 다시 해석해 이름을 표시하며 이름·권한을 URL에서 신뢰하지 않는다.

- [ ] RED: 도메인 입구에서 파일함/대화 두 경로, 회사/개인 구분, 선택 문서 이동, 빈 선택 방지 테스트를 추가한다.

```typescript
expect(screen.getByRole("link", { name: "파일함" })).toHaveAttribute("href", ragDomainFilesPath(domain.slug));
expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeDisabled();
// 합성 doc checkbox 선택 후 같은 domain 경로로 이동하며 문서 본문/이름은 query에 없음을 검사한다.
```

- [ ] 도메인 파일함은 전체 폭과 기존 style token을 재사용하고 같은 domain 공간만 표시한다.
  선택은 페이지를 넘겨도 현재 domain 내에서 유지하되 연결 변경/권한 실패 시 무효화한다.
  검색 상한은 서버 selection_limit으로 표시하고 제한에 도달하면 추가 선택을 막는다.
- [ ] ConversationPage는 documentIds/names를 scopeSnapshot에 추가한다. 선택 모드와 전체 모드를 명시적으로 구분하고
  마지막 문서 해제가 전체 검색으로 바뀌지 않게 빈 선택 안내와 전송 차단을 유지한다.
- [ ] `문서 추가` 패널은 도메인 내 기존 문서를 탐색한다. 적용 시 scope-divider, 이전 history 제외,
  외부 동의 해제, 선택 범위 요약을 갱신한다. 신규 업로드 action은 이 단계에서 제공하지 않는다.
- [ ] 응답 selected_scope를 당시 메시지에 저장해 실제 사용 버전/범위를 표시한다. 409 문맥 변경은 재시작 안내,
  준비 오류는 선택 수정 안내로 처리하며 자동 모델 재시도나 전체검색 전환은 금지한다.
- [ ] 기존 LibraryViewer 열기/닫기·버전·URL 상태와 초점 복귀를 유지한다. 대화 패널도 Escape/닫기/초점 복귀를 지원한다.
- [ ] GREEN: `pnpm --dir frontend test --run src/features/rag/domains src/features/rag/conversation src/features/assets/DocumentBrowser.test.tsx`.
  route tests도 exact 경로를 따옴표로 감싸 실행한다. `pnpm --dir frontend typecheck`, `pnpm --dir frontend lint`.
- [ ] 독립 UI/보안 검토 후 넓은/좁은 viewport에서 실제 읽기 전용 탐색을 확인한다. 실제 업로드·모델 전송은 하지 않는다.

## Task 5: 통합 검증과 인계

**Files:** 위 변경 테스트, `docs/worklogs/2026-09-10-domain-cabinet-selection.md`(신규), `WORKBOARD.md`, ADR-0023와 spec 상태.

- [ ] 격리 실행 지침: `docs/runbooks/local-development.md`와
  `docs/worklogs/2026-09-09-rag-test-isolation.md`를 읽고 기존 fixture의 실사용 DB 차단을 확인한다.
  검증용 DB/ES를 실사용으로 바꿔 테스트하지 않는다. 실행 자원이 없다면 실행하지 않은 통합 게이트를 명시한다.
- [ ] 합성 문서A/B의 다른 답을 준비한 mock generation에서 A선택→B근거 제외, B추가→새문맥,
  A활성버전교체→옛서명409, 타사용자/처리중 문서 포함→모델호출0을 종단 검증한다.
- [ ] 실행: backend 변경 모듈 pytest, `backend/.venv/Scripts/python.exe -m ruff check`와 `-m mypy`에 실제 변경 Python 경로를 명시한다.
  frontend는 Task4 검사 및 `pnpm --dir frontend api:check`, 마지막 `git diff --check`.
- [ ] 독립 reviewer는 모든 diff와 실행 결과를 검토한다. 구현자와 검증자는 같은 책임을 맡지 않는다.
- [ ] WORKBOARD 최근 완료 최대5개를 유지하며 결과와 미실행 항목을 기록한다. 2단계 첨부/동적개인자료는 미구현으로 남긴다.
- [ ] 사용자 테스트 안내는 실제 통과 범위에만 한정한다. 실제 LLM 응답/모델 전송을 실행하지 않았다면 그 사실을 명시한다.

## 역할과 실행 순서

메인: 오케스트레이터·요구사항/아키텍처·문서 통합. RAG 책임자: 범위/프로파일 검토.
Python 담당: Task1→2→3. 프론트 담당: 계약 확정 후 Task4. 독립 테스트/보안/통합 검증: 각 단계 게이트와 Task5.
같은 `search/service.py`를 여러 구현자에게 동시에 배정하지 않는다. DB관리자는 migration이 없는 1단계에서는 제외하고,
인프라·모델 엔지니어도 런타임/배포 변경이 없어 제외한다. 실제 수정 범위가 확장되면 역할을 다시 고지한다.

## 자체 점검

1단계는 상세설계의 도메인 진입·회사/기존개인 파일함·선택검색·기존문서 추가·문맥/전송 경계를 포함한다.
2단계 새 첨부·개인도메인연결·만료는 별도 계획이며 이번 게이트와 섞지 않는다.
문서 선택의 None/empty 의미, 실제 active version과 서명 지문, 일반 검색 경로의 제한 유지가 backend/frontend에서 같다.
