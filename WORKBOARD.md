# Workboard

- 마지막 갱신일: 2026-09-01
- 현재 단계: 승인된 캐시·worktree·Docker 정리 적용과 ACL 잔여물 인계
- 전체 상태: 정책 적용과 Docker 이미지 정리는 완료했고, Docker가 만든 관리자 ACL 물리 폴더만 후속 제거가 필요하다.

## 현재 작업

### 목표

프론트 Node 의존성을 `frontend/`에 한정하고, 완료된 worktree와 프로젝트 소유 Docker 이미지 캐시의 정리 절차를 `CACHE_POLICY.md`와 Codex 지침에 반영한다.

### 진행 상태

- Markdown·TXT·텍스트 PDF 파싱, 구조 청킹, 로컬 E5 임베딩, Elasticsearch BM25+dense, Python RRF, 근거 응답·뷰어, 저장 구성과 평가 UI를 구현했다.
- 자산 READY 활성화, 구독별 ingestion handoff, 다중 활성 build alias와 PostgreSQL-authoritative 검색 수명주기를 구현했다.
- newline-terminated TXT와 빈 parse/chunk 경계를 명시적으로 처리하며, 실패 시 parser나 모델을 조용히 바꾸지 않는다.
- 보호 Compose smoke에서 원본 세 형식, 기존·신규 검색, keyword·semantic highlight, 원문 뷰어, BM25/E5 평가, 승격 거절과 두 사용자 권한 비노출을 실제 API·worker·Elasticsearch로 검증했다.
- Task 14 강화 E2E는 live runtime 밖의 격리 DB·Redis·Elasticsearch reset, foundation/RAG API·worker phase와 beat-only phase를 분리한 보호 프로젝트에서 두 cold/default 실행과 최종 리뷰 실행 모두 통과했다. 최종 실행은 foundation `2 passed`, RAG `17 passed in 110.70s`, beat-only liveness와 post-reset을 검증하고 컨테이너·네트워크만 정리했다.
- 문장 단위 정확한 provenance와 PDF bbox 제한, ingestion redelivery·오류 위생, system BM25 독립 색인 구독, 검색 tie-break, 고정 모델 tokenizer 기반 청킹·질의 한도를 구현·검증했다.
- 루트 `surface`, 잠긴 pytest 임시 디렉터리와 개발 Docker 볼륨은 보존했다.
- `feature/rag-ai-search-first-slice`와 `main`을 동일한 검증 커밋 `47cba3a`로 원격에 반영했다.
- 병합 검증용 PostgreSQL·Redis·Elasticsearch와 전용 네트워크만 제거해 AI Workshop 서비스는 종류별 한 개씩 유지했다.
- 루트 캐시를 재점검해 pnpm 의존성 연결, 영속 로컬 데이터, 도구 목업, 테스트 임시물과 worktree를 구분했다. 실제 삭제는 정책 승인 뒤 별도 범위로 진행한다.
- 루트 `CACHE_POLICY.md`, worktree 수명주기 지침과 Codex 연결 규칙을 구현했다. 프론트 package·lockfile·가상 저장소를 `frontend/`에 한정하고 58개 테스트, 타입 검사, 린트, 빌드와 Docker 기반 OpenAPI 계약 검사를 통과했다.
- 승인된 미태그 AI Workshop 이미지 36개와 종료 컨테이너를 제거해 Docker image 사용량을 `198.4 GB → 24.64 GB`로 줄였다. 볼륨과 shared BuildKit cache는 제거하지 않았다.
- PostgreSQL·Redis·Elasticsearch를 기존 named volume에 연결한 채 main Compose 경로로 재생성했고 모두 healthy다.
- 루트 Node 의존성·pnpm junction과 접근 가능한 캐시·임시물을 제거했다. 독립 프론트 구조에서 frozen lockfile, 58개 테스트, 타입 검사, 린트, 빌드와 OpenAPI 계약을 다시 검증했다.
- RAG worktree의 Git 등록은 제거됐지만 Docker가 `root:root`, mode `111`로 만든 하위 디렉터리 때문에 두 물리 worktree와 네 임시 폴더는 관리자 ACL 정리가 필요하다.

### 완료 기준

- Markdown·TXT·텍스트 PDF가 일반적인 파일 끝 newline을 포함해 비어 있지 않은 구조 요소와 chunk를 생성한다.
- 프로파일의 활성 물리 색인이 모든 READY 문서 projection을 포함하고 기존·신규 문서를 함께 검색한다.
- Task 14 RAG E2E, 전체 백엔드·프론트엔드 검사, Compose smoke와 문서 검사가 모두 실제 exit 0을 반환한다.
- 권한 밖 문서가 답변, 관련 문서, 하이라이트, 뷰어와 평가 케이스 어디에도 노출되지 않는다.
- 캐시 정책이 영속 데이터, 재생성 가능 캐시, 테스트 임시물, 의존성, 도구 산출물과 worktree의 삭제 조건을 구분한다.
- 프론트 설치 기준은 `frontend/package.json`과 `frontend/pnpm-lock.yaml` 하나이며 루트 Node package 파일에 의존하지 않는다.

## 최근 완료 작업

최근 완료 작업은 가장 최신 항목부터 **최대 5개만 유지한다**.

1. 캐시 정책을 적용해 Compose를 main 경로로 이전하고 AI Workshop 반복 빌드 이미지 36개, 루트 Node 의존성과 접근 가능한 캐시를 정리·재검증했다. 관련 문서: `CACHE_POLICY.md`, `docs/worklogs/2026-09-01-cache-audit.md`
2. 첫 RAG 검색 수직 슬라이스를 전체 검증하고 기능 브랜치와 main에 원격 반영했다. 관련 커밋: `47cba3a`
3. 첫 RAG 검색의 provenance, worker redelivery, system BM25 색인, 결정적 검색과 모델 tokenizer 경계를 최종 리뷰 기준으로 강화하고 실제 스택에서 검증했다. 관련 커밋: `b6a2074..fda000b`
4. 첫 RAG 검색 수직 슬라이스의 실제 API·worker·Elasticsearch E2E, smoke와 로컬 실행 인계를 완료했다. 관련 커밋: `a559c2d..a041ab6`
5. newline-terminated TXT와 빈 parse/chunk ingestion 경계를 구현하고 검증했다. 관련 커밋: `b7fbbff`

## 다음 작업

1. 관리자 권한에서 감사 보고서의 ACL 잔여 경로 여섯 개만 제거하고, 물리 경로 부재·Git 상태·Docker health를 최종 확인한다.
2. 캐시 정리 후 DOCX 구조 파서와 권한이 적용된 원문 뷰어 지원을 설계·구현한다.
3. DOCX 실측 뒤 스캔 PDF OCR ingestion과 페이지 근거 표시를 계획한다.
4. 검색 precision과 citation 평가 정책을 통과한 뒤에만 LLM 생성 답변을 검토한다.

## 결정이 필요한 항목

- 관리자 권한이 필요한 Docker 생성 ACL 잔여 폴더를 Codex 외부에서 제거할지 결정해야 한다.
- DOCX의 표·목록·각주를 Evidence Unit과 원문 위치로 표현하는 계약을 다음 설계에서 확정해야 한다.

## 차단 요소

- Docker가 만든 `root:root`, mode `111` 폴더는 현재 Codex 프로세스에서 ACL 조회·소유권 회수·삭제가 거절된다.

## 작업 인계 메모

- 새 작업을 시작하기 전에 이 파일과 루트 `AGENTS.md`를 읽는다.
- 첫 RAG 검색 수직 슬라이스의 최종 증거와 선별 실패 기록은 `docs/worklogs/2026-09-01-rag-integration-verification.md`로 공식 인계했다.
- 작업 트리의 `.idea/`는 사용자 환경 파일이므로 별도 요청 없이 추적하거나 수정하지 않는다.
- RAG worktree의 Git 등록은 제거됐다. 물리 폴더와 미등록 foundation 복사본은 관리자 ACL 후속 대상이며 상세 경로는 캐시 감사 보고서를 따른다.
- 루트 `.pnpm-store` junction과 `node_modules`는 제거됐다.
- 프론트 의존성은 `frontend/node_modules/.pnpm`에 독립 설치됐으며 루트 `node_modules`는 감사 보고서의 레거시 제거 후보로 확정했다.
- 캐시 정책과 정리를 완료한 뒤 DOCX 구조·뷰어 계약을 먼저 확정한다.

## 갱신 규칙

- 작업을 시작할 때 `현재 작업`, `진행 상태`, `다음 작업`을 확인하고 필요한 경우 갱신한다.
- 작업을 끝낼 때 `최근 완료 작업`, `다음 작업`, `결정이 필요한 항목`, `차단 요소`를 갱신한다.
- 최근 완료 작업은 최대 5개만 유지한다. 여섯 번째 항목이 생기면 가장 오래된 항목을 제거한다.
- 장기 작업 이력이 필요해질 때만 제거 대상 기록을 `docs/worklogs/`의 기간별 문서로 옮긴다.
- 완료 항목에는 가능하면 관련 커밋, 설계 문서 또는 검증 결과를 연결한다.
- 실제 검증하지 않은 작업을 완료로 기록하지 않는다.
- 상세 실행 로그를 계속 누적하지 않고, 다음 작업에 필요한 상태와 결정만 남긴다.
- 날짜는 `YYYY-MM-DD` 형식으로 기록한다.
