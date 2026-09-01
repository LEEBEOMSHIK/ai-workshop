# 임시 작업 기록 수명주기

프로젝트 에이전트의 작업별 임시 기록은 반드시 `.local-data/project-agent-work/<task-id>/` 한 디렉터리에만 둔다. `<task-id>`는 하나의 경로 구성 요소이며, 이 경계를 벗어난 경로, junction·reparse point·symlink는 임시 기록이나 정리 대상으로 취급하지 않고 차단한다. 이 기록은 Git에 추가하지 않는다.

## 상태

- `active`: 작업을 수행 중이며 필요한 입력과 진행 기록을 보관한다.
- `validating`: 구현이 끝나 관련 검증과 독립 검토를 수행 중이다.
- `failed`: 작업 또는 검증이 실패했다.
- `blocked`: 외부 권한, 결정 또는 환경 문제로 진행할 수 없다.
- `verified`: 모든 완료·정리 게이트를 통과한 성공 작업이다.

`active`는 `validating`, `failed`, `blocked`로 전이할 수 있다. `validating`은 `verified`, `failed`, `blocked`으로 전이할 수 있다. 재개가 승인된 `failed` 또는 `blocked` 작업은 새 실행 기록을 남기고 `active`로 전이한다. `verified`는 재개하지 않으며, 수정이 다시 필요하면 새 task ID를 만든다.

## 보존과 기록 제한

`failed`와 `blocked`는 재현에 필요한 최소 진단만 보존한다. 허용되는 내용은 승인된 작업 입력의 식별 정보, 실행한 명령의 경계 있는 결과, 실패·차단 상태와 해결되지 않은 문제다. 내부 추론, 비밀값, 개인정보, 원본 문서 본문이나 원본 데이터는 기록하지 않는다.

`active`와 `validating` 기록도 같은 데이터 제한을 따른다. 최종 산출물과 공식 설계·검증 근거는 해당 정본 문서 영역에 두며, 임시 작업 디렉터리를 영구 기록 저장소로 사용하지 않는다.

## verified 게이트와 정리

`verified`가 되려면 구현이 완료되고 관련 검증이 통과했으며, 독립 검토가 명확하고, 해결되지 않은 보안·데이터·migration 문제가 없고, 필요한 정본 문서가 갱신되어야 한다.

자동 정리는 `verified` 게이트를 통과한 뒤 오케스트레이터가 최종 workflow 단계에서 수행하는 후보 작업이다. 정리 전에 `CACHE_POLICY.md`의 적용 가능한 안전 지침과 정확 대상 확인을 다시 수행한다. 대상은 확인된 단일 `.local-data/project-agent-work/<task-id>/` 디렉터리뿐이며, 상위 임시 루트의 일괄 prune, wildcard 삭제, 다른 task ID 또는 저장소 밖 경로 삭제를 허용하지 않는다. junction·reparse point·symlink가 발견되거나 정규화된 대상이 이 경계 밖이면 정리를 중단한다.

정리에는 `CACHE_POLICY.md`의 `destructive_approval: required`가 그대로 적용된다. 따라서 자동 정리 후보라는 상태만으로 파괴적 작업 승인이 대체되지는 않는다.
