# 파일함 이동 서버 구현

- 상태: 서버 구현·프론트 타입 인계·최종 독립 리뷰 완료. 실사용 적용 및 사용자 화면 이동 테스트 완료는 아니다.
- 승인: [이동 상세 계약](../superpowers/specs/2026-09-13-explorer-movement-design.md).
- 실행: [서버 계획](../superpowers/plans/2026-09-13-explorer-movement-server.md).

## 범위와 역할

같은 공간의 문서·폴더 위치 변경 API, metadata_revision, 폴더 계층 검사와 동시 변경을 다룬다.
백엔드·DB 구현과 테스트 설계를 맡는 구현 담당, 보안 사전 점검 담당, 독립 리뷰 담당을 분리한다.
오케스트레이터는 설계·문서·통합을 맡는다. main에서 진행하며 기존 프론트 변경과 사용자 자료를 보존한다.
모델 변경·Docker 변경·실제 사용자 자료 이동은 범위 밖이다.

## 중요한 경계

- null 위치는 실제 파일함 최상위다. root라는 이름의 기존 폴더를 합치거나 자료를 옮기지 않는다.
- 실제 이동에서만 메타데이터 revision을 증가시키며 원본·버전·해시·승인·검색 ID를 변경하지 않는다.
- 공간의 기존 쓰기 잠금과 권한 확인을 재사용한다. 폴더 생성도 같은 깊이 규칙을 따른다.
- 플랫폼 원본 위치와 색인 위치가 다를 수 있으므로 RAG 정합성 검증 전에는 이동 UI를 제공하지 않는다.

## 실사용 적용 전 조건

새 스키마 코드와 기존 DB 스키마를 섞어 재시작하면 컬럼 누락 오류가 날 수 있다.
이번 작업에서 실사용 DB migration이나 서버/worker 재시작은 하지 않는다.
새 스키마가 필요한 코드를 적용하기 전에는 별도 유지보수 범위로 다음을 확인한다.

1. 대상 DB와 현재 migration revision, 작업 중인 API/worker/beat를 식별한다.
2. 백업 후 별도 복원 DB에서 새 migration 및 자료·버전·해시 보존을 검증한다.
3. 쓰기를 중지한 상태에서 실제 migration을 적용한 뒤 API/worker를 일치하는 코드로 재시작한다.
4. health뿐 아니라 인증된 목록·문서 조회와 권한 경계까지 확인한다.
5. 실패 시 migration downgrade만으로 완료라고 하지 않는다. 코드와 스키마를 함께 복구한다.

실제 문서를 테스트용으로 이동시키거나 샘플을 업로드하지 않는다.
격리 테스트가 생성한 DB는 기존 검증된 helper의 정확한 이름 검사를 거쳐 정리한다.

## 후속 순서

서버 검증 → RAG의 현재 허용 원본/빌드 조합 선필터·생성 직전 재검증 → 이동 메뉴·확인 창·DnD → 실사용 적용·사용자 테스트.
frozen 평가의 과거 스냅샷 의미를 현재 폴더로 소급 변경하지 않는다.
기존 검색 원문 resolver는 DB의 DocumentRecord.folder_id로 표시 위치를 재구성하고 있다.
그러나 검색 선필터의 과거 folder_id와 재검증 결과를 버리는 경로는 별도 보완 대상이다.

## 서버 구현과 검증 결과

`0034_asset_metadata_revision`과 문서/폴더 이동 POST를 추가했다. 요청은 목적지(null 허용)와 strict 정수 revision을 요구하고 알 수 없는 필드를 거부한다.
응답과 기존 목록/상세에는 실제 metadata_revision이 포함된다. 오류는 not_found404, asset_revision_conflict409,
folder_exists409, folder_cycle409, folder_depth_exceeded409, folder_hierarchy_invalid409로 구분한다.

처음 단위10건이 미구현으로 실패한 뒤 구현했다. 격리 통합 테스트에서 오래된 ORM 객체의 no-op 오판을 재현해
잠금 후 populate_existing 재조회로 수정했다. 독립 검토에서 다른 공간의 폴더가 손상된 FK로 source 하위에 들어온 경우를 발견했다.
이동/no-op 모두 내부 EXISTS 검사로 거부하도록 보완했고, source/descendant×move/no-op4건의 RED→GREEN을 확인했다.
공유 깊이 설정의 중복 기본값도 제거했다. 타 공간 메타데이터를 응답에 노출하거나 손상 자료를 고치지는 않는다.

메인에서 최종 코드를 재실행한 결과:

```text
.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider tests/unit/platform/assets tests/integration/platform/assets/test_asset_movement.py tests/integration/platform/assets/test_asset_library.py tests/integration/platform/assets/test_personal_workspace_isolation.py tests/integration/platform/workspaces/test_member_permissions.py -q
95 passed, 1 warning in 86.73s
```

명령은 backend를 작업 디렉터리로 실행한다.
경고1건은 기존 FastAPI/Starlette TestClient의 httpx 사용 중단 예정 안내다. 의존성은 변경하지 않았다.
이동 통합15건과 기존 단위·라이브러리·개인 격리·구성원 권한 회귀를 포함한다.
독립 재검토는 두 지적의 수정 및 신규 차단 문제 없음을 확인했다.
메인의 `mypy --cache-dir=nul src/ai_workshop/platform/assets`(16파일), 변경 범위 Ruff `--no-cache`,
`git diff --check`도 통과했다. AGENTS.md는123줄이며 main에서만 작업했다.

검증한 보존 범위는 버전 ID·활성 버전·object key 등 DB 메타데이터와 SQL 변경 경계다.
물리 원본 bytes/hash 스냅샷, 전체 RAG 표 스냅샷, 실제 worker 실행 중 이동은 아직 검증하지 않았으므로
전체 검색·인용·실사용 보존 검증이 끝났다고 표현하지 않는다.

## 프론트 계약 인계와 최종 검토

기존 OpenAPI 생성기로 schema.d.ts를 갱신했다. 실제 UI 로직·이동 버튼·DnD는 추가하지 않았다.
필수 metadata_revision은 합성 테스트 문서/폴더에만 명시했고 런타임 대체 기본값은 넣지 않았다.
초기 타입 검사0 이후 남은 fixture에서 누락 오류가 발생해 수정했다. 초기0의 원인은 단정하지 않는다.
tsconfig는 테스트를 포함하며 검사 범위를 바꾸지 않았다.

메인 최종 프론트 검증:

```text
node node_modules/vitest/vitest.mjs run src/features/assets src/features/rag/domains/DomainFileCabinet.test.tsx src/features/rag/conversation/DocumentSelectionPanel.test.tsx src/features/rag/conversation/ConversationAnswer.test.tsx src/features/rag/conversation/ConversationPage.test.tsx
10 files, 105 tests passed, 113.19s

node node_modules/typescript/bin/tsc --noEmit --pretty false --incremental false
Exit0

node openapi-ts.config.mjs --check
Exit0
```

메인의 전체 ESLint(`node node_modules/eslint/bin/eslint.js . --max-warnings 0`)도 exit0이었다.
최종 독립 리뷰는 Task3 계약/fixture와 전체 서버 slice를 각각 승인했다.
실사용0034 적용 전 재시작 금지, RAG 정합성 전 이동 UI 미노출 조건은 그대로 남는다.
추가 커밋·푸시·의존성 설치·샘플 업로드는 하지 않았다.
