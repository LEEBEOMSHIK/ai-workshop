# Workboard

- 마지막 갱신일: 2026-08-31
- 현재 단계: 첫 RAG AI 검색 수직 슬라이스 완료
- 전체 상태: Markdown·TXT·텍스트 PDF의 ingestion부터 검색·근거·평가까지 실제 스택 검증 완료

## 현재 작업

### 목표

첫 RAG 검색 수직 슬라이스를 안정적인 기준선으로 유지하고 다음 형식 확장을 준비한다.

### 진행 상태

- Markdown·TXT·텍스트 PDF 파싱, 구조 청킹, 로컬 E5 임베딩, Elasticsearch BM25+dense, Python RRF, 근거 응답·뷰어, 저장 구성과 평가 UI를 구현했다.
- 자산 READY 활성화, 구독별 ingestion handoff, 다중 활성 build alias와 PostgreSQL-authoritative 검색 수명주기를 구현했다.
- newline-terminated TXT와 빈 parse/chunk 경계를 명시적으로 처리하며, 실패 시 parser나 모델을 조용히 바꾸지 않는다.
- 보호 Compose smoke에서 원본 세 형식, 기존·신규 검색, keyword·semantic highlight, 원문 뷰어, BM25/E5 평가, 승격 거절과 두 사용자 권한 비노출을 실제 API·worker·Elasticsearch로 검증했다.
- Task 14 전체 E2E는 같은 보호 프로젝트에서 `6 passed in 113.76s`, `6 passed in 92.64s`로 반복 통과했고 컨테이너·네트워크만 정리하며 named volume을 보존한다.
- 루트 `surface`, 잠긴 pytest 임시 디렉터리와 개발 Docker 볼륨은 보존했다.

### 완료 기준

- Markdown·TXT·텍스트 PDF가 일반적인 파일 끝 newline을 포함해 비어 있지 않은 구조 요소와 chunk를 생성한다.
- 프로파일의 활성 물리 색인이 모든 READY 문서 projection을 포함하고 기존·신규 문서를 함께 검색한다.
- Task 14 RAG E2E, 전체 백엔드·프론트엔드 검사, Compose smoke와 문서 검사가 모두 실제 exit 0을 반환한다.
- 권한 밖 문서가 답변, 관련 문서, 하이라이트, 뷰어와 평가 케이스 어디에도 노출되지 않는다.

## 최근 완료 작업

최근 완료 작업은 가장 최신 항목부터 **최대 5개만 유지한다**.

1. 첫 RAG 검색 수직 슬라이스의 실제 API·worker·Elasticsearch E2E, smoke와 로컬 실행 인계를 완료했다.
2. newline-terminated TXT와 빈 parse/chunk ingestion 경계를 구현하고 검증했다. 관련 커밋: `b7fbbff`
3. 검증된 자산의 READY 활성화와 RAG handoff 재시도·격리 수명주기를 구현하고 검증했다. 관련 커밋: `f51b3b9`
4. RAG 구성 스튜디오, 평가 비교와 승격 UI의 상태·경쟁 조건을 구현하고 검증했다. 관련 커밋: `5b108e5`
5. 근거 우선 검색, 관련 출처와 원문 뷰어 UI를 구현하고 검증했다. 관련 커밋: `441a76a`

## 다음 작업

1. DOCX 구조 파서와 권한이 적용된 원문 뷰어 지원을 설계·구현한다.
2. DOCX 실측 뒤 스캔 PDF OCR ingestion과 페이지 근거 표시를 계획한다.
3. 검색 precision과 citation 평가 정책을 통과한 뒤에만 LLM 생성 답변을 검토한다.

## 결정이 필요한 항목

- DOCX의 표·목록·각주를 Evidence Unit과 원문 위치로 표현하는 계약을 다음 설계에서 확정해야 한다.

## 차단 요소

- 현재 차단 요소는 없다.

## 작업 인계 메모

- 새 작업을 시작하기 전에 이 파일과 루트 `AGENTS.md`를 읽는다.
- 첫 RAG 검색 수직 슬라이스의 검증 증거와 격리 smoke 상태는 무시된 `.superpowers/sdd/2026-08-30-rag-ai-search-first-vertical-slice/task-14-report.md`에 기록했다.
- 작업 트리의 `.idea/`는 사용자 환경 파일이므로 별도 요청 없이 추적하거나 수정하지 않는다.
- 다음 작업은 DOCX 구조·뷰어 계약을 먼저 확정하고 파서·검색·권한·원문 근거를 한 수직 슬라이스로 검증한다.

## 갱신 규칙

- 작업을 시작할 때 `현재 작업`, `진행 상태`, `다음 작업`을 확인하고 필요한 경우 갱신한다.
- 작업을 끝낼 때 `최근 완료 작업`, `다음 작업`, `결정이 필요한 항목`, `차단 요소`를 갱신한다.
- 최근 완료 작업은 최대 5개만 유지한다. 여섯 번째 항목이 생기면 가장 오래된 항목을 제거한다.
- 장기 작업 이력이 필요해질 때만 제거 대상 기록을 `docs/worklogs/`의 기간별 문서로 옮긴다.
- 완료 항목에는 가능하면 관련 커밋, 설계 문서 또는 검증 결과를 연결한다.
- 실제 검증하지 않은 작업을 완료로 기록하지 않는다.
- 상세 실행 로그를 계속 누적하지 않고, 다음 작업에 필요한 상태와 결정만 남긴다.
- 날짜는 `YYYY-MM-DD` 형식으로 기록한다.
