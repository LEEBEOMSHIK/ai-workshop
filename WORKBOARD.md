# Workboard

- 마지막 갱신일: 2026-09-01
- 현재 단계: 첫 RAG AI 검색 수직 슬라이스 main 통합 완료, 캐시 정책 확정
- 전체 상태: RAG 브랜치와 main 원격 반영을 완료했고 루트 캐시·임시 산출물의 보존 및 정리 기준을 확정하는 중이다.

## 현재 작업

### 목표

병합된 첫 RAG 검색 기준선을 보존하면서 `CACHE_POLICY.md`와 안전한 정리 절차를 확정한다.

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

### 완료 기준

- Markdown·TXT·텍스트 PDF가 일반적인 파일 끝 newline을 포함해 비어 있지 않은 구조 요소와 chunk를 생성한다.
- 프로파일의 활성 물리 색인이 모든 READY 문서 projection을 포함하고 기존·신규 문서를 함께 검색한다.
- Task 14 RAG E2E, 전체 백엔드·프론트엔드 검사, Compose smoke와 문서 검사가 모두 실제 exit 0을 반환한다.
- 권한 밖 문서가 답변, 관련 문서, 하이라이트, 뷰어와 평가 케이스 어디에도 노출되지 않는다.
- 캐시 정책이 영속 데이터, 재생성 가능 캐시, 테스트 임시물, 의존성, 도구 산출물과 worktree의 삭제 조건을 구분한다.

## 최근 완료 작업

최근 완료 작업은 가장 최신 항목부터 **최대 5개만 유지한다**.

1. 첫 RAG 검색 수직 슬라이스를 전체 검증하고 기능 브랜치와 main에 원격 반영했다. 관련 커밋: `47cba3a`
2. 첫 RAG 검색의 provenance, worker redelivery, system BM25 색인, 결정적 검색과 모델 tokenizer 경계를 최종 리뷰 기준으로 강화하고 실제 스택에서 검증했다. 관련 커밋: `b6a2074..fda000b`
3. 첫 RAG 검색 수직 슬라이스의 실제 API·worker·Elasticsearch E2E, smoke와 로컬 실행 인계를 완료했다. 관련 커밋: `a559c2d..a041ab6`
4. newline-terminated TXT와 빈 parse/chunk ingestion 경계를 구현하고 검증했다. 관련 커밋: `b7fbbff`
5. 검증된 자산의 READY 활성화와 RAG handoff 재시도·격리 수명주기를 구현하고 검증했다. 관련 커밋: `f51b3b9`

## 다음 작업

1. 승인된 설계로 루트 `CACHE_POLICY.md`를 만들고 정책에 따른 정확한 정리 대상을 별도 승인받는다.
2. 캐시 정리 후 DOCX 구조 파서와 권한이 적용된 원문 뷰어 지원을 설계·구현한다.
3. DOCX 실측 뒤 스캔 PDF OCR ingestion과 페이지 근거 표시를 계획한다.
4. 검색 precision과 citation 평가 정책을 통과한 뒤에만 LLM 생성 답변을 검토한다.

## 결정이 필요한 항목

- `CACHE_POLICY.md`의 분류·승인·worktree 및 junction 처리 설계 승인이 필요하다.
- 다른 프로젝트 소유의 실행 중 PostgreSQL `tpmp-db-local-55432`를 전역 Docker 정리 범위에 포함할지는 별도 결정이 필요하다.
- DOCX의 표·목록·각주를 Evidence Unit과 원문 위치로 표현하는 계약을 다음 설계에서 확정해야 한다.

## 차단 요소

- 캐시 정책 파일 생성과 실제 정리는 설계 및 정확한 삭제 대상 승인을 기다린다.

## 작업 인계 메모

- 새 작업을 시작하기 전에 이 파일과 루트 `AGENTS.md`를 읽는다.
- 첫 RAG 검색 수직 슬라이스의 검증 증거와 격리 smoke 상태는 활성 RAG worktree의 무시된 `.superpowers/sdd/2026-08-30-rag-ai-search-first-vertical-slice/task-14-report.md`에 기록돼 있으므로 worktree 정리 전에 선별 보존한다.
- 작업 트리의 `.idea/`는 사용자 환경 파일이므로 별도 요청 없이 추적하거나 수정하지 않는다.
- 활성 RAG worktree는 main과 같은 커밋이지만 미추적 `surface`와 pytest 산출물을 분류한 뒤 Git worktree 절차로만 제거한다.
- `.pnpm-store` junction은 미등록 `.worktrees/workshop-foundation` 복사본을 가리키므로 두 경로를 하나의 정리 단위로 취급한다.
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
