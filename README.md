# AI Workshop

AI Workshop은 AI를 공부한 과정과 실제로 동작하는 기술을 함께 축적하는 개인 작업소다. 내부에서는 메모, 실험, 실패 기록과 민감한 문서를 다루고, 외부에는 검토하고 비식별화한 결과만 공개한다.

첫 번째 기술 연구 영역은 자산운용 전문 문서를 위한 RAG AI 검색이다. 검색은 BM25와 bi-encoder를 결합한 hybrid retrieval을 사용하며, 결과를 권한이 허용된 원본 위치와 함께 보여준다.

## 현재 상태

작업소 기반과 RAG 검색·대화 코드가 구현됐다. Markdown·TXT·PDF·DOCX 처리와 스캔/혼합 PDF·DOCX 이미지 OCR, BM25+dense+RRF 검색, 근거·하이라이트·원문 뷰어, 근거 제한 답변·인용 검증, 저장 구성과 평가 비교를 포함한다. 별칭 복구·첨부 색인과 실제 모델의 실패·취소 등 본래 환경의 기능 마감은 진행 중이며, 구현된 기능 전체가 운영 검증을 마쳤다는 뜻은 아니다.

로컬 Gemma용 `local_transformers`는 코드·mock 검증을 마쳤지만 모델 활성화·실추론은 미완료다. AMD64 환경을 유지하며 ARM64 전환 조사는 취소했다. 현재 미완료 범위와 다음 순서는 [WORKBOARD](WORKBOARD.md)를 따른다.

- [현재 작업 대시보드](WORKBOARD.md)
- 검색 화면: `/workshop/rag/search`
- RAG 구성·평가 스튜디오: `/admin/rag/configurations`
- 관리자 모델 레지스트리: `/admin/rag/models`

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
