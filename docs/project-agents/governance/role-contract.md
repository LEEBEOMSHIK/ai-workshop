# 역할 계약 스키마

각 역할 문서는 YAML frontmatter로 시작하며, 다른 목록이나 코드에 역할 메타데이터를 중복하지 않는다. 필수 필드는 `role_id`, `name`, `category`, `scope`, `activation`, `independent_from`이다. `role_id`는 저장소 전체에서 유일한 kebab-case 식별자이고, `name`은 비어 있지 않은 역할명이다. `independent_from`은 존재하는 역할 ID만 담는 목록이다. 구현 역할과 RAG 전문 역할은 `integration-e2e-verifier` 및 `independent-code-reviewer`와의 독립 관계를 모두 선언한다. 독립 통합·보안·privacy 검증자와 독립 코드 리뷰어는 `prohibits_same_change_implementation: true`를 선언해 자신이 승인하는 같은 변경을 구현할 수 없음을 계약으로 표현한다.

허용 `category` 값은 `leadership`, `architecture`, `engineering`, `operations`, `quality`, `documentation`, `domain-leadership`, `domain-specialist`이다. 허용 `scope` 값은 `project`, `rag`이고, 허용 `activation` 값은 `always`, `conditional`이다. 프로젝트 오케스트레이터만 `always`를 사용하며 나머지 역할은 실제 신호와 범위가 있을 때 `conditional`이다.

모든 역할 본문은 아래 15개 제목을 정확히 한 번씩 포함하고, 각 절에는 해당 역할의 구체적인 판단 기준과 인계 정보를 쓴다.

```text
## 목적
## 담당 범위
## 호출 조건
## 비호출 조건
## 작업 전 필수 문서
## 필수 입력
## 책임
## 권한
## 금지 사항
## 산출물
## 인계
## 설정·하드코딩 점검
## 필수 검증
## 완료 조건
## 중단·에스컬레이션
```

검증기는 frontmatter 형식, enum, 중복 ID, 독립성 참조, 활성화 규칙 참조와 빈 절을 검사한다. 역할 본문에는 `TODO` 또는 `TBD` 같은 미완성 표식을 남기지 않는다.
