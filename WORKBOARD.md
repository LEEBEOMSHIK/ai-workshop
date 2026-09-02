# Workboard

- 마지막 갱신일: 2026-09-02
- 현재 단계: RAG 구성 패키지 표현 및 내부 식별자 정리
- 전체 상태: 저장된 RAG 구성을 파서부터 답변까지 이어지는 하나의 패키지로 표현하고 사용자 표시값과 내부 UUID 경계를 정리한다.

## 현재 작업

### 목표

RAG 구성 화면에는 Parser, Chunker, Embedding, BM25, Dense Retriever, RRF, Reranker, Answer Policy와 LLM을 하나의 저장 패키지로 표시한다. 이해 가능한 이름·버전만 기본 노출하고 내부 UUID는 저장·호환성·재현 계약에 유지하며, 승인된 pytest 임시 경로 두 개의 정리 결과를 기록한다.

### 진행 상태

- 색인·검색 구성의 profile/model UUID가 사용자 옵션과 요약에 직접 노출되는 원인을 확인했고, 내부 식별자를 API 값으로 유지하면서 기본 표시에서 감추는 설계를 승인받았다.
- 저장 구성은 개별 모델 하나가 아니라 Indexing·Retrieval·Answer Policy·선택적 Generation의 불변 버전을 묶은 RAG 패키지로 표시한다. 현재 구성 계약에 고정되지 않은 Parser와 V1에서 비활성인 Reranker·LLM은 추측값 대신 명시적 미사용·미고정 상태로 표시한다.
- 정리 대상은 `backend/.pytest-nextjs-final-contract`와 `backend/.pytest-tmp` 두 리터럴 경로로 한정했으며 애플리케이션 데이터·프론트 의존성·실행 서비스는 보존한다.
- `backend/.pytest-nextjs-final-contract`는 Windows 관리자 ACL로 소유돼 현재 실행 계정의 정확 경로 삭제도 거부됐고, `backend/.pytest-tmp`는 내부 확인 자체가 거부됐다. 우회 삭제하지 않고 차단 요소로 인계한다.
- RAG 패키지·UUID 회귀 테스트 32개, 전체 프론트 테스트 83개, TypeScript, ESLint, Next production build, 백엔드 YAML 테스트 11개, 에이전트 계약과 문서 diff 검사가 통과했으며 독립 코드 리뷰는 Ready 판정을 내렸다.
- Next.js는 프론트엔드와 최소 rewrite 계층만 담당하고 인증·권한·AI·DB 업무 로직은 FastAPI에 유지하기로 결정했다.
- 사용자 역할·관리자 RAG 명령 API, Next.js 도구체인·접근 레이아웃, 공개·지식 공간·문서 화면 전환을 구현했다.
- RAG 검색·구성·모델·출처 뷰어를 App Router에 연결하고, 의미·키워드 하이라이트 메타데이터를 원문 문구 노출 없이 canonical URL에서 복원하도록 구현했다.
- Vite·React Router 진입점과 의존성을 제거하고 이전 URL 여섯 개를 permanent redirect로 보존했다.
- Next 서버가 설정 파일 위치를 기준으로 루트 `.env`를 강제 로드해 호스트 FastAPI 포트를 rewrite와 Server Component에서 동일하게 사용한다.
- 보호 경로의 실제 pathname·query를 Next 프록시가 레이아웃에 전달해 로그인 뒤 원래 화면으로 복귀하며, 서버 렌더링 API 실패는 FastAPI correlation ID를 안전한 직렬화 데이터로 표시한다.
- 로컬 Next 서버와 기존 호스트 FastAPI를 연결해 health 200, 공개 화면 200, 레거시 검색 URL 308, 원래 경로를 보존한 비로그인 사용자·관리자 경로 307을 확인했다.
- Vite·React Router를 병행하지 않는 전체 전환과 `/app/*`, `/admin/*` canonical URL 및 기존 URL 영구 리다이렉트를 승인했다.
- Next.js `16.3.4` 안정 버전, App Router, Server Component 우선, 상호작용 경계만 Client Component로 사용하는 기준을 설계에 반영한다.
- DB에서 사용자 1명, 기본 공간 2개와 멤버십 2개가 정상 생성된 것을 확인했다.
- `/workspaces` 라우트가 인증만 확인하고 `listWorkspaces()`를 호출하지 않아 화면에 기본 빈 배열이 전달되는 원인을 확인했다.
- `/workspaces` 전용 보호 로더와 route wrapper를 연결해 API의 전사·개인 공간을 표시하고 회귀 테스트로 고정했다.
- 최초 관리자 설정 서비스·공개 상태 API·`/setup` UI, 생성 직후 세션 발급과 보호 경로의 setup/login 분기를 구현했다.
- 관리자와 전사·개인 기본 지식 공간을 동일 트랜잭션에서 생성하고 PostgreSQL table lock으로 동시 최초 설정을 직렬화한다.
- CLI owner bootstrap은 정상 사용자 흐름에서 제외하고 같은 계약을 따르는 복구 수단으로 한정했다.
- 깨끗한 로컬 DB의 설정 필요 상태를 호스트 API와 Vite proxy에서 확인했으며 실제 사용자 비밀번호나 임의 관리자 계정은 만들지 않았다.
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
- Docker가 `root:root`, mode `111`로 만든 두 물리 worktree와 네 임시 폴더를 PowerShell 7 관리자 경로에서 제거하고, 승인 경로 부재와 보존 대상 존재를 확인했다.
- Docker 용량 미회수 후속 조사에서 BuildKit 192.5 GB와 비-sparse `docker_data.vhdx` 219.079 GB를 확인했다. `uv` 캐시 5.0 GB가 이미지 레이어에 포함되고 `/app` 5.3 GB 전체 chown이 반복 copy-up되는 것이 원인이며, AI Workshop 전용 private cache ID 31개 143.849 GB를 분리했다.
- `uv` cache mount와 `/app` chown 제거를 적용한 이미지는 5.960 GB, 내장 uv cache 0 B이며 runtime·data ownership·Dockerfile build check를 통과했다.
- 구형 image와 승인된 구형 BuildKit chain 7개를 정확한 ID로 제거했다. 승인된 parent 2개는 승인 밖 child 2개가 참조해 보존했고 넓은 prune은 실행하지 않았다.
- Docker Desktop과 네 DB·검색 서비스를 정상 중단해 VHDX를 오프라인 압축했다. VHDX는 약 227.536 GB에서 57.250 GB, host 여유 공간은 약 32.624 GB에서 202.907 GB가 됐다.
- 재기동 후 AI Workshop PostgreSQL·Redis·Elasticsearch와 다른 프로젝트 PostgreSQL의 동일 container ID·volume mount·실제 응답을 확인했으며 Docker volume 52개를 모두 보존했다.
- 최종 검증에서 백엔드 테스트 424개·Ruff·mypy·OpenAPI 계약과 프론트 테스트 58개·타입 검사·린트·빌드가 통과했다.
- 추가 승인된 BuildKit child 2개와 parent 2개를 자식부터 제거해 Build cache를 24.25 GB에서 13.55 GB로 줄였다. VHDX 실제 크기와 host 여유 공간은 이번 논리 정리만으로 추가 감소하지 않았다.
- 프로젝트 개발 에이전트와 제품 런타임 에이전트를 분리하고, 공통 프로젝트 역할과 RAG 책임자 아래 전문 역할을 갖는 계층형 조직 설계를 사용자와 확정했다.
- 역할 선택·사전 고지, 구현과 독립 검증 분리, 전체 소스 하드코딩 방지, 성공 시 임시 기록 자동 정리와 계약 자동 검증 기준을 명세로 작성했다.
- 프로젝트 개발 에이전트 조직을 `main`과 원격에 반영한 뒤 승인에 따라 격리 worktree와 로컬·원격 기능 브랜치를 제거했다.
- 프로젝트 개발 에이전트 역할 계약, activation rule, workflow, 임시 기록 수명주기, Codex 어댑터와 자동 검증기를 구현하고 대표 역할 선택 시나리오를 검증했다.

### 완료 기준

- 저장 구성과 편집 미리보기가 Parser부터 LLM까지 전체 RAG 패키지 단계를 표시한다.
- BM25, bi-encoder Dense Retriever, RRF, Reranker와 LLM을 기술적으로 구분한다.
- 현재 계약에 고정되지 않은 Parser와 V1 미지원 Reranker·LLM을 정확한 상태로 표시한다.
- 내부 UUID는 기본 UI에서 숨기고 닫힌 기술 상세, React identity와 API payload에 유지한다.
- 백엔드 V1이 거부하는 리랭커 프로파일은 구성 후보에서 제외한다.
- 대상·전체 테스트, 타입 검사, 린트, production build와 독립 리뷰가 통과한다.

## 최근 완료 작업

최근 완료 작업은 가장 최신 항목부터 **최대 5개만 유지한다**.

1. 저장된 RAG 구성을 Parser·Chunker·Embedding·Sparse/Dense Retriever·Fusion·Reranker·Answer Policy·LLM의 한 패키지로 표시하고 내부 UUID 기본 노출을 제거했으며 V1 리랭커 호환성과 파서 비고정 계약을 테스트·문서·독립 리뷰로 검증했다. 관련 계획: `docs/superpowers/plans/2026-09-02-rag-configuration-package-ui.md`
2. Vite SPA를 Next.js 16 App Router로 전체 전환하고 사용자·관리자 경로, 정확한 로그인 복귀 URL, RAG 화면, owner 명령 API, FastAPI 오류 참조, 영구 리다이렉트와 로컬 실행을 구현·검증했다. 관련 설계: `docs/superpowers/specs/2026-09-02-nextjs-frontend-migration-design.md`
3. `/workspaces` 보호 라우트가 인증 후 목록 API를 로드하고 전사·개인 기본 공간을 표시하도록 연결 누락을 수정·검증했다.
4. 최초 관리자 1명을 만드는 `/setup` UI와 API, 전사·개인 기본 공간의 원자적 생성, 동시 설정 방지, setup/login 보호 경로 분기와 복구용 CLI 계약을 구현·검증했다. 관련 결정: `docs/decisions/0004-first-owner-ui-setup.md`
5. 프로젝트 개발 에이전트 조직의 역할 계약, activation rule, workflow, 수명주기, Codex 어댑터와 자동 검증을 구현하고 대표 시나리오를 검증했다. 관련 설계: `docs/superpowers/specs/2026-09-02-project-development-agent-organization-design.md`

## 다음 작업

1. 형식별 Parser Policy Version과 Saved RAG Configuration 연결, 재파싱·재청킹·재색인 수명주기 설계
2. Parser Policy에 포함되는 DOCX 구조 파서와 원문 뷰어 계약 설계
3. DOCX 파싱·청킹·하이라이트 수직 슬라이스 구현 계획 수립

## 결정이 필요한 항목

- 없음.

## 차단 요소

- `backend/.pytest-nextjs-final-contract`는 untracked지만 Windows 관리자 ACL 때문에 현재 비관리자 환경에서 삭제할 수 없다.
- `backend/.pytest-tmp`는 Git ignored 경로이며 같은 ACL 문제로 내부 확인과 삭제가 거부된다. 두 경로 모두 애플리케이션 소스와 실행 데이터에는 영향을 주지 않으며, 대화형 Windows 관리자 세션에서 소유권과 내용을 확인한 뒤 정확 경로만 삭제해야 한다.

## 작업 인계 메모

- 새 작업을 시작하기 전에 이 파일과 루트 `AGENTS.md`를 읽는다.
- 첫 RAG 검색 수직 슬라이스의 최종 증거와 선별 실패 기록은 `docs/worklogs/2026-09-01-rag-integration-verification.md`로 공식 인계했다.
- 작업 트리의 `.idea/`는 사용자 환경 파일이므로 별도 요청 없이 추적하거나 수정하지 않는다.
- RAG worktree의 Git 등록과 물리 폴더, 미등록 foundation 복사본, 네 테스트 임시 폴더가 모두 제거됐다. 상세 결과는 캐시 감사 보고서를 따른다.
- 루트 `.pnpm-store` junction과 `node_modules`는 제거됐다.
- 프론트 의존성은 `frontend/node_modules/.pnpm`에 독립 설치됐으며 루트 `node_modules`는 감사 보고서의 레거시 제거 후보로 확정했다.
- RAG 패키지 UI는 현재 Parser가 구성에 고정되지 않음을 명시한다. 다음 우선 작업은 형식별 Parser Policy Version과 패키지·산출물 수명주기 설계다.
- Next.js 프론트는 `http://127.0.0.1:5173`, 기존 호스트 FastAPI는 `http://127.0.0.1:18000`에서 실행한다.
- 최종 Docker 상태와 잔여 BuildKit 계보는 `docs/worklogs/2026-09-01-cache-audit.md`를 정본으로 사용한다.
- 추가 승인된 잔여 BuildKit 네 레코드는 모두 제거됐으며 추가 Docker 정리는 새 조사와 승인 없이 진행하지 않는다.
- 프로젝트 개발 에이전트 조직 설계 정본은 `docs/superpowers/specs/2026-09-02-project-development-agent-organization-design.md`다.

## 갱신 규칙

- 작업을 시작할 때 `현재 작업`, `진행 상태`, `다음 작업`을 확인하고 필요한 경우 갱신한다.
- 작업을 끝낼 때 `최근 완료 작업`, `다음 작업`, `결정이 필요한 항목`, `차단 요소`를 갱신한다.
- 최근 완료 작업은 최대 5개만 유지한다. 여섯 번째 항목이 생기면 가장 오래된 항목을 제거한다.
- 장기 작업 이력이 필요해질 때만 제거 대상 기록을 `docs/worklogs/`의 기간별 문서로 옮긴다.
- 완료 항목에는 가능하면 관련 커밋, 설계 문서 또는 검증 결과를 연결한다.
- 실제 검증하지 않은 작업을 완료로 기록하지 않는다.
- 상세 실행 로그를 계속 누적하지 않고, 다음 작업에 필요한 상태와 결정만 남긴다.
- 날짜는 `YYYY-MM-DD` 형식으로 기록한다.
