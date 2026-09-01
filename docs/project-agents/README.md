# 프로젝트 개발 에이전트 정본

프로젝트 오케스트레이터는 작업 범위를 분류한 뒤 아래 순서에서 해당 작업에 필요한 문서만 읽는다. 역할 파일의 YAML frontmatter가 역할 메타데이터의 유일한 정본이다.

1. [역할 계약 스키마](governance/role-contract.md)
2. [오케스트레이션](governance/orchestration.md)
3. [활성화 규칙](governance/activation-rules.md)
4. [하드코딩 방지 정책](governance/hardcoding-policy.md)

역할 카테고리는 [리더십](roles/leadership/), [아키텍처](roles/architecture/), [엔지니어링](roles/engineering/), [운영](roles/operations/), [품질](roles/quality/), [문서화](roles/documentation/)로 나뉜다. 현재 도메인 역할은 [RAG](domains/rag/)만 다루며, 시작하지 않은 도메인의 역할이나 폴더를 미리 만들지 않는다.

Codex에서 이 정본을 적용할 때의 호출과 인계 방식은 [Codex 어댑터](../guidelines/codex/project-agent-orchestration.md)를 따른다.

## 작업 흐름

1. governance 진입점 문서를 읽는다.
2. 작업 범위와 위험에서 activation signal을 분류한다.
3. signal의 최소 필수 역할 baseline을 선택한다.
4. 실제 범위에 필요한 contextual specialist만 추가한다.
5. 참여 역할과 제외 역할 및 이유를 사용자에게 고지한다.
6. 구현과 분리된 독립 검증으로 작업을 실행한다.
7. 정본 산출물과 `WORKBOARD.md`를 마무리한다.
8. 모든 게이트를 통과한 verified 임시 기록만 정확한 task 경계에서 정리한다.

문서만 바꾸는 사소한 오탈자는 activation signal이 없으므로 프로젝트 오케스트레이터 단독으로 처리할 수 있다. Workflow의 default signal은 해당 workflow를 선택했을 때의 기준일 뿐이며, 오케스트레이터가 실제 작업 범위에 없는 RAG 또는 다른 도메인 역할을 강제로 호출하지 않는다.
