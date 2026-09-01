---
schema_version: 1
workflow_id: feature-development
default_signals:
  - requirements-or-behavior
  - feature-implementation
---

# 기능 개발 흐름

오케스트레이터는 요구와 영향 범위를 분류하고 설계를 승인받은 뒤 필요한 구현 역할을 배정한다. 구현 전에는 수용·경계 테스트를 RED로 확인하고, 최소 변경으로 GREEN을 만든 뒤 관련 통합 검증과 구현자와 독립된 검증을 완료한다. 선택된 역할과 제외 이유, 설정·권한·문서 영향 및 실제 검증 결과를 사용자에게 고지한다.
