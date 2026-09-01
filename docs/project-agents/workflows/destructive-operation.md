---
schema_version: 1
workflow_id: destructive-operation
default_signals:
  - significant-change-or-merge
---

# 파괴적 작업 흐름

오케스트레이터는 정확한 대상·영향·복구 가능성·보존 대상을 확인하고 해당 정책의 사전 검사를 수행한 뒤 사용자 승인을 받는다. `CACHE_POLICY.md` 같은 도메인별 정책은 계속 정본이며, 이 workflow를 선택해도 삭제·초기화·덮어쓰기 권한이 생기지 않는다. 승인된 범위만 실행하고 실제 대상, 결과, 복구 가능성 및 사후 검증을 독립적으로 기록한다.
