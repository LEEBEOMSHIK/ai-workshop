---
schema_version: 1
workflow_id: bug-fix
default_signals:
  - feature-implementation
---

# 버그 수정 흐름

오케스트레이터는 재현 조건과 영향을 고정하고 구현자와 독립 검증자를 분리해 배정한다. 구현 역할은 증상을 재현하는 RED 테스트를 먼저 확인하고 최소 수정 후 GREEN과 회귀 검토를 수행한다. 독립 역할은 구현 결과와 별도로 재현·회귀 증거를 확인하며, 미해결 원인과 위험은 완료 대신 기록한다.
