# 통합 파일함과 대화 범위 설계

- 기준일: 2026-09-13
- 상태: 사용자 승인 방향을 소스에 맞춰 구체화한 단계별 설계. 단계별 구현·검증 완료와 구분한다.
- 대상: Platform Assets/Workspaces, RAG domain/conversation/retrieval, 기존 파일함 UI.
- 선행 정본: [ADR-0021](../../decisions/0021-platform-document-library.md), [ADR-0023](../../decisions/0023-domain-cabinet-conversation.md), [기존 선택 문서 설계](2026-09-10-domain-cabinet-conversation-design.md).

## 1. 확정한 사용 흐름과 변경 경계

도메인을 선택하면 바로 대화 화면에 들어간다. 사용자는 대화 화면에서 회사 또는 개인 공간, 폴더, 개별 파일 중 하나의 제한 방식을 선택한다. 기존에 올린 파일을 트리에서 고를 수 있고, 파일 관리와 미리보기는 필요할 때 연다. 파일함 방문·파일 열기·미리보기 성공은 질문의 선행 조건이 아니다.

통합 파일함은 기존 Platform 파일함과 도메인 파일함 및 대화 내 패널에서 같은 탐색·관리 컴포넌트를 사용한다. 독립 관리 URL은 유지한다. 대화에서 관리하려고 독립 URL로 강제로 이동시키지 않는다. 탐색·미리보기·검색 선택은 각각 별도의 상태이며 파일을 여는 것만으로 검색 범위가 변하지 않는다.

이 문서는 ADR-0023의 `대화 화면에 전체 파일 관리 기능을 합치는 대안 제외`와 기존 설계 §11의 이동·휴지통 제외를 이번 후속 범위에 한해 대체한다. 원본 소유권, 도메인 권한 교집합, 외부 전송 승인, 독립 원문 열람 계약은 유지한다. 공개 계약 변경 전 통합 책임자가 ADR-0023 및 architecture/RAG 정본에 이 변경을 연결한다.

대안 비교: 별도 파일함으로 매번 이동하는 방식은 사용자가 정정한 흐름에 맞지 않는다. 대화 전용 파일 저장소를 새로 만드는 방식은 원본·권한을 중복한다. 기존 Platform 파일함을 도메인 어댑터와 선택 상태로 재사용하는 방식을 채택한다. 새 인프라, 외부 Drive 연결, Office 편집기, 영구 삭제, 임시 첨부 및 대화 저장 목록은 이 설계의 구현 범위가 아니다.

## 2. 소스로 확인한 현재 상태와 차이

아래 경로는 저장소 루트 기준이다. 날짜 시점의 dirty worktree를 조사했으며 기존 변경을 본 설계의 구현 성과로 간주하지 않는다.

| 확인한 소스 | 현재 동작 | 필요한 변화 |
|---|---|---|
| `frontend/src/features/rag/domains/DomainPickerPage.tsx` | 대화 및 파일함 링크 존재 | 대화 직접 진입을 주 경로로 유지 |
| `frontend/src/features/rag/conversation/ConversationPage.tsx` | 기본적으로 허용 공간 전체 선택, 폴더 배열과 문서 선택 상태 별도 | 명시 제한 모드와 비어 있는 선택을 분리하고 자동 확대 방지 |
| `conversation/DocumentSelectionPanel.tsx` | DomainFileCabinet 임베드, 현재 공간/폴더 제한 안에서 파일 선택 | 같은 트리에서 공간/폴더/문서를 선택하고 적용·취소를 분리 |
| `domains/DomainFileCabinet.tsx` | DocumentBrowser 재사용, `readOnly` 고정, 문서 선택 콜백 | 재사용 경계 유지, 추후 서버 capability에 따른 관리 모드 |
| `frontend/src/features/assets/DocumentBrowser.tsx` | 트리·breadcrumb·페이지 조회·뷰어·새 폴더·업로드·새 버전 | rename/move/trash/restore 없음; 관리 어댑터와 선택 상태 분리 필요 |
| `backend/src/ai_workshop/platform/assets/service.py` | upload/create_folder는 membership 접근 여부, upload_version은 사용자 문서 조회로 허용 | 읽기 접근을 쓰기 권한으로 사용하지 않는 동작별 검사 |
| `platform/assets/models.py` | folder parent/name, document folder/name/active_version; tombstone/수정 revision 없음 | 메타데이터 revision과 휴지통 상태를 migration으로 도입 |
| `platform/workspaces/repository.py` | 생성자는 owner membership, 목록은 membership 기준 | personal의 소유자 조건을 별도로 강제 |
| `labs/rag/retrieval/scope.py` | 활성 READY Asset/정확한 profile·projection/build 확인, folder_id 직접 일치 필터 | 변경 후 최신 권한·휴지통·폴더 위치를 같은 검색 전 해석에 반영 |
| `labs/rag/retrieval/selection.py` | 명시 null/빈 document_ids 거부 | UI가 빈 파일 선택을 필드 생략으로 바꾸지 않도록 보존 |

`DocumentBrowser.readOnly`를 제거하는 것만으로 통합 관리를 완료할 수 없다. 현재 서버 쓰기 검사는 회사 read/write/delete를 구분하지 않으며 UI 버튼 감추기는 서버 권한을 대체하지 않는다.

## 3. 범위 모드와 요청 의미

프론트 상태는 `workspace`, `folder`, `documents`의 판별 가능한 모드로 표현한다. 각 모드의 선택 draft는 적용 전 검색에 영향을 주지 않는다. 트리 위치 변경과 미리보기는 draft를 자동 적용하지 않는다.

| 모드 | 필수 선택 | 기존 요청 직렬화 | 포함 범위 |
|---|---|---|---|
| 공간 | 하나 이상의 명시 선택 공간 | workspace_ids, folder_ids=[], document_ids 생략 | 해당 공간에서 도메인·구성·현재 권한과 READY 조건에 맞는 문서 |
| 폴더 | 하나 이상의 폴더 | 해당 공간 ID, folder_ids, document_ids 생략 | 선택 폴더에 직접 속한 문서만; 1단계에서 하위 폴더 자동 포함하지 않음 |
| 파일 | 하나 이상의 파일 | 해당 공간 ID와 document_ids, 의도한 폴더 제한만 유지 | 정확히 선택한 문서의 현재 활성 버전; 하나라도 무효면 전체 요청 차단 |

회사/개인은 workspace kind의 구분이며 표시 이름이나 고정 UUID로 권한을 결정하지 않는다. 회사와 개인을 함께 조회하려면 사용자가 두 공간을 명시 선택한다. 화면 진입 시 모든 허용 공간을 조용히 선택하지 않는다. 미선택 상태에는 안내와 비활성 전송을 제공하며 사용자가 보이는 범위 선택을 완료한다. 기존 명시 문서 deep link는 파일 모드로 복원한다.

마지막 폴더나 파일을 해제해도 해당 모드를 유지하고 전송을 막는다. 공간 모드 전환은 명시 조작이며 이를 통해서만 제한이 넓어진다. 패널 취소·조회 실패·권한 철회·선택 객체 소실은 기존 범위를 전체 공간으로 바꾸지 않는다. 실패한 선택은 무효 상태와 재선택 안내를 남긴다.

1단계는 기존 서버 wire contract를 재사용한다. UI의 폴더 포함 의미를 `하위 폴더 제외`로 명확히 표시한다. 재귀 하위 폴더 포함은 별도 계약·서명·회귀 검증 없이 추가하지 않는다. 후속 명시 scope_mode API 도입 시 unknown field 거부, 모드/필드 일치 검증, OpenAPI 타입 생성과 기존 클라이언트 전환을 같은 단계에서 한다.

적용한 범위가 바뀌면 기존 대화는 화면에 보존하되 새 구간을 시작한다. 이전 구간을 새 history에 자동 포함하지 않는다. 진행 중 적용은 막고 늦은 응답을 배제한다. 실제 서버가 확정한 문서/Asset/build 지문 및 기존 서명 검증을 유지한다. 권한·버전 변화가 확인되면 과거 문맥을 그대로 재사용하지 않는다.

## 4. 공통 파일함 경계와 권한

Platform은 원본·논리 폴더·버전·권한·휴지통을 소유한다. RAG는 도메인 가용 범위와 검색 준비 상태를 공통 읽기/관리 계약 위에서 조립한다. Platform 모듈에서 RAG 구현을 import하지 않는다. 기존 데이터베이스, 객체 저장소, Job 및 worker를 사용한다.

개인 공간은 생성 소유자 본인만 일반 파일함 읽기·쓰기·삭제·복원 가능하다. 다른 membership이나 시스템 관리자 역할만으로 타인의 개인 본문을 읽을 수 없다. 기존 생성 소유자·owner membership 불일치는 migration 검증에서 보고하고 자동 소유권 이전하지 않는다. 개인 파일의 도메인 사용 가능 여부는 기존 도메인/구성 경계와 별도이며 개인 공간이 있다는 이유로 전사 연결에 추가하지 않는다.

회사 권한은 `read`, `write`, `delete`를 구분한다. 읽기는 목록·버전·원문·허용된 검색, 쓰기는 업로드·새버전·새폴더·이름변경·이동의 대상 위치 생성, 삭제는 휴지통 이동을 허용한다. 폴더/문서 작업의 현재 유효 capability를 서버가 반환하되 각 변경 요청에서 재검증한다. 초기 세분화 단위는 회사 workspace membership의 명시 권한 집합이며 객체별 ACL 편집은 이 단계에서 추가하지 않는다. 소유자는 해당 회사 관리 권한을 가진다. 기존 일반 member를 자동 삭제 가능 관리자로 승격하지 않는다. 기존 역할별 migration 매핑과 회귀 검증은 단계2 공개 계약에 포함한다.

이동은 원본 위치 write와 목적지 write를 모두 요구한다. 복원은 delete와 목적지 write를 모두 요구한다. 권한 편집은 별도 관리 권한으로 제한한다. 공유·복원·이동은 외부 전송 승인을 새로 부여하거나 문서 버전 승인 이력을 변경하지 않는다. 권한 없는 대상 ID는 기존 404 비노출 방식으로 응답한다.

## 5. 수정 및 휴지통 불변 조건

각 Folder/Document에 단조 증가하는 metadata_revision을 둔다. 원본 내용 버전과 혼동하지 않는다. rename/move/trash/restore는 expected_revision을 필수로 받고 트랜잭션 조건부 갱신을 수행한다. 일치하지 않으면 409 conflict와 현재 읽기 가능한 메타데이터를 반환한다. 자동 덮어쓰기·자동 이름 바꾸기·자동 재시도하지 않는다. 사용자가 최신 상태를 보고 다시 적용한다.

이름 변경은 논리 표시 이름만 바꾸며 document ID, Asset ID, 저장 object key, content hash, 인용 식별자를 유지한다. 폴더 형제 이름 충돌은 기존 정규화 규칙과 잠금을 적용한다. 문서 이름은 현재 중복 가능하므로 이 단계에서 기존 동명 문서를 자동 병합하거나 새로운 유일 제약을 소급하지 않는다. 동일 내용 업로드의 기존 해시 중복 검사와 이름 충돌은 구분한다.

이동은 동일 workspace 안의 논리 위치 변경으로 제한한다. 회사↔개인 및 다른 workspace 이동은 명시적으로 지원하지 않는다. 자기 자신·자손으로의 폴더 이동, depth 초과, 휴지통 목적지, 서로 다른 workspace parent, 권한 없는 목적지를 거부한다. 동시 폴더 이동은 workspace 수준의 일관된 계층 잠금으로 순환 검사를 직렬화하고 metadata_revision도 검증한다. Folder FK의 CASCADE/SET NULL을 삭제 UX로 사용하지 않는다.

휴지통은 메타데이터 tombstone으로 구현하고 원본 bytes·버전·승인·감사 이력을 보존한다. 폴더 휴지통 이동은 하위 항목 전체의 유효 접근을 같은 트랜잭션에서 차단한다. 작업 batch ID 및 이전 위치를 기록하여 복원 대상을 정확히 식별한다. 하위 항목에 이전부터 있던 독립 tombstone은 부모 복원 시 되살리지 않는다. 휴지통 항목은 일반 목록·버전/원문·다운로드·RAG 접근에서 제외하며 휴지통 관리 목록은 별도 권한 확인 후 안전한 메타데이터만 반환한다.

복원 시 원래 부모가 활성이고 권한 및 이름 조건이 맞으면 원래 위치로 복원한다. 부모가 없거나 휴지통 상태이거나 충돌하면 409와 명시 목적지 선택을 요구한다. 루트로 조용히 복원하지 않는다. 재귀 작업은 전부 성공하거나 전부 롤백하며 부분 성공을 숨기지 않는다. 영구 삭제·보관기간 자동 정리·객체 파일 삭제는 구현하지 않는다.

## 6. RAG와 비동기 정합성

휴지통 및 권한 철회는 DB commit 직후 검색 scope resolver에서 제외한다. BM25와 dense 양쪽의 실행 전 최신 권한과 활성 Asset/build allowlist를 계산하므로 ES tombstone 반영 지연 중에도 검색 후보로 사용할 수 없다. 결과를 받은 뒤 숨기는 방식으로 대체하지 않는다. 원문/다운로드/인용 재열람도 현재 권한과 tombstone을 검사한다.

이동·휴지통·복원·권한 변경의 revision을 Job 입력에 담고 worker 활성화 시 다시 확인한다. 오래된 ingestion/indexing 완료가 휴지통 항목을 재활성화하지 못하게 한다. 기존 잠금 순서와 Job 멱등 키에 맞춰 변경하며 새 큐 인프라를 만들지 않는다. 검색 전 scope와 모델 전송 직전 권한 상태가 달라지면 요청을 중단하고 재선택을 요구한다. 이미 제공된 과거 답변의 회수는 보장하지 않으며 이후 인용 접근을 차단한다.

이름 변경은 원문 재파싱·임베딩 재생성 이유가 아니다. 이동은 위치 메타데이터 및 범위 해석을 갱신하고 식별자·원본을 유지한다. 복원은 기존 READY 표시만 믿지 않고 현재 Asset/profile/projection/build 및 권한을 재검증한 뒤에만 검색 가능하다. 파일 모드는 하나라도 tombstone/권한 철회/비준비이면 전체를 거부한다. 공간·폴더 모드는 현재 유효 후보가 없으면 근거 부족으로 종료하고 다른 공간을 검색하지 않는다.

## 7. 형식 지원과 합성 검증

`UploadDialog.tsx`와 `platform/assets/service.py`는 XLSX/PPTX/DOCX/PDF 등을 업로드 허용한다. `platform/assets/originals.py`의 독립 뷰어는 text/markdown/pdf/unsupported를 반환하며 `LibraryViewer`는 unsupported 안내와 명시 다운로드를 제공한다. `labs/rag/parsing`에는 XLSX 파서가 없다. 따라서 업로드 성공을 XLSX 미리보기·시트 검색·셀 인용 지원으로 표시하지 않는다.

원본 준비 상태와 RAG 검색 준비 상태를 구분해서 표시한다. XLSX는 파일함 보관/다운로드만 가능하다고 안내하며 파서 또는 현재 프로파일이 지원하지 않으면 파일 검색 선택을 비활성화하거나 서버의 명확한 비지원 오류를 표시한다. 미지원 파일을 선택 목록에서 조용히 누락시키지 않는다. 새 XLSX 파서·Office 변환 서버는 이번 단계에 추가하지 않는다.

합성 PDF 수용 기준: 서로 다른 회사/개인 사용자, 루트와 중첩 폴더, 텍스트 2쪽 이상 및 서로 다른 v1/v2로 목록→선택→원문 열람→다음/이전 페이지→버전 전환→닫기 초점 복귀를 검증한다. 파일명·크기·형식·버전 표시, 선택한 원본의 페이지와 실제 문서 일치, 권한 없는 원문/페이지 요청 거부, 깨진 PDF의 오류·재시도, 모바일 폭과 키보드 조작을 포함한다. 파일을 미리 열지 않고 선택 후 질문할 수 있어야 한다.

검색 수용 기준은 합성 A/B 문서의 구별 가능한 문구로 공간/폴더/파일 모드마다 요청 범위와 실제 retrieval 필터를 대조한다. 문서 선택 상태 유지, 마지막 선택 해제 차단, 범위 변경 후 history 분리, 권한 철회/휴지통/버전 변경 중 지연 응답 배제를 검증한다. PDF 페이지 확인만으로 OCR·하이라이트·실제 LLM 응답까지 통과했다고 보고하지 않는다. 실제 LLM 호출은 기존 명시 전송·비용 승인 경계에서 별도 검증한다.

## 8. 실행 단계와 완료 기준

1. **대화 범위 UX**: ConversationPage/ScopeSelector/DocumentSelectionPanel/DomainFileCabinet의 기존 경로를 재사용한다. 공간·폴더·파일 명시 모드, 적용/취소, 빈 선택 차단, 트리 선택, 직접 대화 진입을 구현한다. 이 단계는 DB·권한·서버 공개 계약 변경 없이 기존 API를 사용한다. 기존 독립 관리 기능은 남지만 새로운 inline 쓰기 버튼은 단계2까지 노출하지 않는다. 이 단계 완료는 전체 통합 관리 완료가 아니다.
2. **권한과 공통 inline 기본관리**: 개인 owner 조건, 회사 read/write/delete 계약과 migration·capability 응답·서버 권한을 먼저 구현한다. API 계약 테스트와 부정 권한 테스트 후 기존 새폴더/업로드/새버전 기능을 공통 관리 어댑터로 대화 패널에도 제공한다. 기존 URL은 동일 컴포넌트를 사용한다. 도메인 관리 목적지와 실제 쓰기 권한을 모두 확인한다.
3. **이름·이동·휴지통·복원**: metadata revision/tombstone/계층 잠금/API/관리 UI를 함께 구현한다. 목록·원문·RAG·worker의 tombstone와 권한 선필터가 준비된 뒤 휴지통 동작을 노출한다. 격리 PostgreSQL 통합에서 동시성·원자성·복원 충돌·index 지연을 검증한다.
4. **통합 수용**: 합성 PDF/XLSX 및 회사/개인 역할 조합으로 독립 파일함과 대화 패널을 검증한다. 사용자 실제 자료 또는 외부 모델 테스트는 합성 자동 검증과 구분해 결과를 기록한다.

1단계 검증은 `pnpm --dir frontend test --run`에 관련 conversation/domains/assets 테스트를 지정하고 `pnpm --dir frontend typecheck`, 변경 파일 ESLint를 수행한다. scope 요청 본문에 대해 workspace/folder/document 상호 배타성, 마지막 선택 해제, 실패 시 무확대, deep link, 패널 취소 및 미리보기 독립성을 테스트한다. 공용 API가 바뀌는 단계부터 `pnpm --dir frontend api:check`, backend 단위·격리 통합·ruff·mypy를 추가하며 정확한 실행 방법은 [로컬 실행 정본](../../runbooks/local-development.md)을 따른다.

각 단계는 구현 책임과 독립 보안/코드 리뷰 책임을 분리하고 관련 검증 결과를 확인한 뒤 다음 단계로 통합한다. 사용자 방향 승인은 이미 있으며 같은 방향을 다시 승인받는 절차를 추가하지 않는다. 예상하지 않은 공개 계약 확장이나 실제 데이터의 파괴적 변경이 필요해지면 그 구체적인 차이만 다시 협의한다.
