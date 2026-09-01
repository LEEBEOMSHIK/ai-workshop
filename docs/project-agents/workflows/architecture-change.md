---
schema_version: 1
workflow_id: architecture-change
default_signals:
  - requirements-or-behavior
  - cross-module-or-public-contract
  - significant-change-or-merge
  - design-adr-or-document-structure
---

# 아키텍처 변경 흐름

오케스트레이터는 영향 모듈·공개 계약·데이터 경계를 분류하고 승인된 설계와 필요 시 ADR을 먼저 확정한다. 설계자와 구현자, 독립 리뷰어를 같은 책임으로 합치지 않으며 변경 후 계약·통합·회귀 검증과 독립 리뷰를 수행한다. 정본 문서와 구현이 충돌하면 통합을 중단하고 변경 의도를 확인한다.
