# 프로젝트 개발 에이전트 정본

프로젝트 오케스트레이터는 작업 범위를 분류한 뒤 아래 순서에서 해당 작업에 필요한 문서만 읽는다. 역할 파일의 YAML frontmatter가 역할 메타데이터의 유일한 정본이다.

1. [역할 계약 스키마](governance/role-contract.md)
2. [오케스트레이션](governance/orchestration.md)
3. [활성화 규칙](governance/activation-rules.md)
4. [하드코딩 방지 정책](governance/hardcoding-policy.md)

역할 카테고리는 [리더십](roles/leadership/), [아키텍처](roles/architecture/), [엔지니어링](roles/engineering/), [운영](roles/operations/), [품질](roles/quality/), [문서화](roles/documentation/)로 나뉜다. 현재 도메인 역할은 [RAG](domains/rag/)만 다루며, 시작하지 않은 도메인의 역할이나 폴더를 미리 만들지 않는다.

Codex에서 이 정본을 적용할 때의 호출과 인계 방식은 [Codex 어댑터](../guidelines/codex/project-agent-orchestration.md)를 따른다.
