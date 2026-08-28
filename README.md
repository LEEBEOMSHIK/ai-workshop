# AI Workshop

AI Workshop은 AI를 공부한 과정과 실제로 동작하는 기술을 함께 축적하는 개인 작업소다. 내부에서는 메모, 실험, 실패 기록과 민감한 문서를 다루고, 외부에는 검토하고 비식별화한 결과만 공개한다.

첫 번째 기술 연구 영역은 자산운용 전문 문서를 위한 RAG AI 검색이다. 검색은 BM25와 bi-encoder를 결합한 hybrid retrieval을 사용하며, 결과를 원본 문서의 의미상 관련된 위치와 함께 보여주는 것을 목표로 한다.

## 현재 상태

현재 저장소는 설계 단계다. 구현 코드는 아직 없으며, 승인된 프로젝트 방향과 기술 경계를 문서로 먼저 관리한다.

- [현재 작업 대시보드](WORKBOARD.md)

## 설계 문서

- [Codex 프로젝트 지침](AGENTS.md)
- [프로젝트 비전](docs/vision/project-vision.md)
- [전체 시스템 설계](docs/architecture/system-design.md)
- [저장소 구조](docs/architecture/repository-structure.md)
- [개발 및 운영 지침](docs/guidelines/development-guidelines.md)
- [Codex 참고 문서 구조](docs/guidelines/codex/README.md)
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
