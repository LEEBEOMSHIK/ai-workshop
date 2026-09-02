# Workboard

- 마지막 갱신일: 2026-09-02
- 현재 단계: DOCX 구조 파서·원문 뷰어 계약 설계
- 전체 상태: 최초 관리자 UI와 로컬 인증·RAG 진입 흐름을 구현·검증했다. 다음 RAG 문서 형식 확장 계약을 설계한다.

## 현재 작업

### 목표

DOCX 구조 파서와 원문 뷰어가 RAG 공통 문서 모델, Evidence Unit과 권한·provenance 경계를 보존하도록 계약을 설계한다.

### 진행 상태

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

- DOCX 제목, 문단, 목록과 표를 공통 Structural Element로 매핑하는 규칙을 정한다.
- Evidence Unit에서 DOCX 원문 위치로 돌아가는 불변 provenance 계약을 정한다.
- 형식별 원문 뷰어와 정확·의미 하이라이트 표시 경계를 정한다.
- 손상 문서, 지원하지 않는 요소와 부분 파싱을 조용히 성공 처리하지 않는 실패 계약을 정한다.
- 공개·합성 fixture와 파서·뷰어 검증 범위를 구현 전에 확정한다.

## 최근 완료 작업

최근 완료 작업은 가장 최신 항목부터 **최대 5개만 유지한다**.

1. 최초 관리자 1명을 만드는 `/setup` UI와 API, 전사·개인 기본 공간의 원자적 생성, 동시 설정 방지, setup/login 보호 경로 분기와 복구용 CLI 계약을 구현·검증했다. 관련 결정: `docs/decisions/0004-first-owner-ui-setup.md`
2. 프로젝트 개발 에이전트 조직의 역할 계약, activation rule, workflow, 수명주기, Codex 어댑터와 자동 검증을 구현하고 대표 시나리오를 검증했다. 관련 설계: `docs/superpowers/specs/2026-09-02-project-development-agent-organization-design.md`
3. Dockerfile의 uv cache·copy-up 중복을 제거하고 승인된 전용 BuildKit 계보까지 정리한 뒤 VHDX를 압축해 host 공간 약 170.283 GB를 실제 회수했다. 관련 문서: `CACHE_POLICY.md`, `docs/worklogs/2026-09-01-cache-audit.md`
4. Docker 생성 ACL과 긴 경로가 남은 두 물리 worktree와 네 테스트 임시 폴더를 승인 경계 안에서 제거하고 보존 대상을 재검증했다. 관련 문서: `docs/worklogs/2026-09-01-cache-audit.md`
5. 캐시 정책을 적용해 Compose를 main 경로로 이전하고 AI Workshop 반복 빌드 이미지 36개, 루트 Node 의존성과 접근 가능한 캐시를 정리·재검증했다. 관련 문서: `CACHE_POLICY.md`, `docs/worklogs/2026-09-01-cache-audit.md`

## 다음 작업

1. DOCX 구조 파서·원문 뷰어 계약 설계

## 결정이 필요한 항목

- 없음.

## 차단 요소

- 없음.

## 작업 인계 메모

- 새 작업을 시작하기 전에 이 파일과 루트 `AGENTS.md`를 읽는다.
- 첫 RAG 검색 수직 슬라이스의 최종 증거와 선별 실패 기록은 `docs/worklogs/2026-09-01-rag-integration-verification.md`로 공식 인계했다.
- 작업 트리의 `.idea/`는 사용자 환경 파일이므로 별도 요청 없이 추적하거나 수정하지 않는다.
- RAG worktree의 Git 등록과 물리 폴더, 미등록 foundation 복사본, 네 테스트 임시 폴더가 모두 제거됐다. 상세 결과는 캐시 감사 보고서를 따른다.
- 루트 `.pnpm-store` junction과 `node_modules`는 제거됐다.
- 프론트 의존성은 `frontend/node_modules/.pnpm`에 독립 설치됐으며 루트 `node_modules`는 감사 보고서의 레거시 제거 후보로 확정했다.
- 다음 작업은 `DOCX 구조 파서·원문 뷰어 계약 설계`이며, RAG 설계의 공통 문서 모델·형식별 뷰어·권한 경계를 정본으로 삼는다.
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
