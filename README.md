# AI Workshop

AI Workshop은 AI를 공부한 과정과 실제로 동작하는 기술을 함께 축적하는 개인 작업소다. 내부에서는 메모, 실험, 실패 기록과 민감한 문서를 다루고, 외부에는 검토하고 비식별화한 결과만 공개한다.

첫 번째 기술 연구 영역은 자산운용 전문 문서를 위한 RAG AI 검색이다. 검색은 BM25와 bi-encoder를 결합한 hybrid retrieval을 사용하며, 결과를 권한이 허용된 원본 위치와 함께 보여준다.

## 현재 상태

1단계 작업소 기반과 첫 RAG 검색 수직 슬라이스가 구현됐다. Markdown, TXT와 텍스트 PDF를 비동기로 파싱·색인하고 BM25 기준선과 E5 hybrid 검색, 원문 근거·하이라이트·뷰어, 저장 구성과 평가 비교를 제공한다. 격리 smoke는 runtime이 중지된 상태에서 DB·Redis·RAG index prefix를 안전하게 reset하고, foundation과 RAG E2E를 beat 없이 순서대로 완료한 뒤 beat 구성을 별도로 확인하고 다시 중지·reset한다.

- [현재 작업 대시보드](WORKBOARD.md)
- 검색 화면: `/rag/search`
- RAG 구성·평가 스튜디오: `/rag/configurations`

## 개발 시작

```powershell
pnpm --dir frontend install --frozen-lockfile
Copy-Item .env.example .env
.\scripts\smoke.ps1
```

Elasticsearch와 로컬 모델 cache 준비, 일상 실행, owner 생성, migration, smoke와 장애 복구 절차는 [로컬 개발 실행서](docs/runbooks/local-development.md)를 따른다. 환경 변수와 비밀값은 추적되지 않는 `.env`에 둔다.

## 설계 문서

- [Codex 프로젝트 지침](AGENTS.md)
- [프로젝트 캐시 정책](CACHE_POLICY.md)
- [프로젝트 비전](docs/vision/project-vision.md)
- [전체 시스템 설계](docs/architecture/system-design.md)
- [저장소 구조](docs/architecture/repository-structure.md)
- [개발 및 운영 지침](docs/guidelines/development-guidelines.md)
- [로컬 개발 실행서](docs/runbooks/local-development.md)
- [Codex 참고 문서 구조](docs/guidelines/codex/README.md)
- [완료 worktree 수명주기](docs/guidelines/codex/worktree-lifecycle.md)
- [RAG AI 검색 설계](docs/labs/rag/design.md)
- [ADR-0001: 모듈형 모놀리스](docs/decisions/0001-modular-monolith.md)
- [ADR-0002: 로컬 우선 데이터 경계](docs/decisions/0002-local-first-data-boundary.md)
- [ADR-0003: Hybrid retrieval 기준선](docs/decisions/0003-hybrid-retrieval-baseline.md)

## 핵심 원칙

1. 자유로운 학습 기록과 재현 가능한 실험을 모두 지원한다.
2. 실패를 숨기지 않되 공개할 때는 배운 점이 드러나도록 재구성한다.
3. 공통 작업소 기능과 기술별 연구 영역을 분리한다.
4. 문서와 임베딩은 로컬 우선으로 처리한다.
5. 검색 결과는 항상 권한이 허용된 원문 근거로 돌아갈 수 있어야 한다.
6. 모델은 교체하고 비교할 수 있어야 하며, 검증된 조합만 일반 검색에 사용한다.
