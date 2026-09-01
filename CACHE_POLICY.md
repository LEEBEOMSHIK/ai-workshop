---
schema_version: 1
project: ai-workshop
scope: repository-local caches, completed worktrees, and project-owned Docker artifacts
destructive_approval: required
---

# AI Workshop 캐시 정책

## 목적

이 정책은 저장소 주변에 생성되는 의존성, 테스트 산출물, 작업용 worktree와 Docker 산출물을 분류하고 안전한 정리 경계를 정의한다. 현재 상태의 조사 결과는 삭제 승인이 아니며, 실제 정리 전에는 정확한 대상과 예상 회수량을 다시 보고한다.

## 기본 원칙

- 보존과 제거 판단이 충돌하면 보존한다.
- 삭제 대상은 정규화된 절대경로 또는 정확한 Docker 식별자로 확정한다.
- 저장소 밖으로 이어지는 junction, reparse point와 symlink는 대상을 확인하기 전까지 차단한다.
- 알 수 없는 미추적 파일, 사용자 환경 파일과 다른 프로젝트 소유 산출물은 정리하지 않는다.
- 정리 직전에 Git 상태, 프로세스 사용, Docker 참조와 mount를 다시 검사한다.
- 승인된 대상만 정리하고 범위가 달라지면 새 조사와 승인을 받는다.

## 파일시스템 분류

| 분류 | 대상 | 정책 |
|---|---|---|
| 영구 보존 | `.git` | 모든 정리에서 제외한다. |
| 사용자 환경 | `.idea` | 사용자의 별도 요청 없이는 변경하거나 제거하지 않는다. |
| 애플리케이션 데이터 | `.local-data/objects` | 업로드 원본과 파생 자산일 수 있으므로 보존한다. |
| 모델 캐시 | `.local-data/models` | 재다운로드 가능성, 사용 중 프로세스와 승인된 모델 출처를 확인한 경우에만 후보로 보고한다. |
| 프론트 의존성 | `frontend/node_modules` | 프론트 독립 lockfile로 복원 가능하고 개발 프로세스가 사용하지 않을 때만 후보로 보고한다. |
| 프론트 패키지 캐시 | `frontend/.pnpm-store` | junction 경계와 복원 가능성을 확인한 경우에만 후보로 보고한다. |
| 레거시 루트 의존성 | `node_modules` | 프론트 독립 구조 전환이 검증된 뒤에만 일회성 제거 후보로 보고한다. |
| 레거시 루트 패키지 캐시 | `.pnpm-store` | 모든 junction 대상과 프론트 설치 검증을 확인한 뒤에만 일회성 제거 후보로 보고한다. |
| 정적 분석 캐시 | `.mypy_cache`, `.ruff_cache`, `backend/.mypy_cache`, `backend/.ruff_cache` | 생성 도구가 실행 중이 아니면 재생성 가능한 후보로 보고한다. |
| 테스트 임시물 | `.local-data/pytest-tmp`, `backend/.pytest-tmp`와 루트의 명시적으로 식별된 pytest 임시 디렉터리 | 실제 테스트 데이터가 아닌지 확인한 뒤 후보로 보고한다. |
| 빌드 산출물 | `frontend/dist`, `backend/build` | 해당 빌드가 재현 가능하고 배포 입력으로 사용 중이지 않을 때 후보로 보고한다. |
| 도구 산출물 | `.superpowers` | 목업, 최종 검증 보고서와 선별 실패 기록을 먼저 보존하고 중간 상태와 재생성 가능한 diff만 후보로 보고한다. |

## worktree 수명주기

- worktree는 임시 작업 공간이며 완료된 기능의 영구 보관소로 사용하지 않는다.
- 기능이 `main`에 반영되고 원격에 푸시되면 worktree 정리를 작업 완료 조건에 포함한다.
- 제거 전에 미추적·무시 파일, 선별 검증 기록, 실행 중 프로세스와 Docker Compose 경로 참조를 확인한다.
- 보존할 기록은 저장소의 공식 문서 영역으로 옮기고 검증한다.
- 실행 중 서비스가 worktree 경로를 참조하면 먼저 `main` 경로로 관리 기준을 이전한다.
- 등록된 worktree는 Git worktree 절차로만 제거한다. 일반 재귀 삭제로 제거하지 않는다.
- 로컬·원격 기능 브랜치 삭제는 worktree 제거와 분리해 결정한다.
- 상세 절차는 `docs/guidelines/codex/worktree-lifecycle.md`를 따른다.

## Docker 분류

### 보존 대상

- 실행 중인 AI Workshop PostgreSQL, Redis와 Elasticsearch 컨테이너 및 참조 이미지를 보존한다.
- `ai-workshop_postgres-data`, `ai-workshop_elasticsearch-data`, `ai-workshop_redis-data`, `ai-workshop_object-data`, `ai-workshop_model-cache`와 `ai-workshop_backend-venv` 볼륨을 보존한다.
- DB, 검색 색인, 업로드 원본, 모델 데이터와 이름 없는 볼륨을 캐시라는 이유로 제거하지 않는다.
- 다른 Compose project 라벨을 가진 컨테이너와 이미지는 공유 리소스로 보고만 한다.

### 제거 후보

- AI Workshop 저장소에서 생성됐음을 증명할 수 있는 미태그 이미지 중 어떤 컨테이너도 참조하지 않는 정확한 이미지 ID를 후보로 보고한다.
- 현재 검증 기준으로 보존할 태그 이미지 한 개와 그 기반 이미지는 후보에서 제외한다.
- 완료된 격리 검증의 중지 컨테이너는 AI Workshop 전용 Compose project와 service 라벨, mount와 종료 상태가 확인된 경우에만 후보로 보고한다.

### 차단 및 공유 리소스

- 프로젝트 단독 소유권을 증명할 수 없는 BuildKit 캐시는 정리하지 않고 사용량만 보고한다.
- 전역 일괄 정리 기능은 다른 프로젝트의 이미지, 컨테이너와 캐시를 포함할 수 있으므로 사용하지 않는다.
- Docker 볼륨은 회수 가능으로 표시되더라도 이 정책의 제거 대상이 아니다.
- 이미지가 다른 이미지의 기반이거나 컨테이너 참조 관계가 불명확하면 보존한다.

## 조사 보고 형식

정리 제안은 다음 순서로 작성한다.

1. 제거 후보: 정확한 경로 또는 Docker ID, 후보가 된 근거와 예상 회수량
2. 보존 대상: 애플리케이션 데이터, 실행 서비스, 현재 기준 이미지와 사용자 환경
3. 차단 대상: 사용 중 상태, 경계 밖 junction, 불명확한 소유권과 정책 충돌
4. 공유 리소스: 다른 프로젝트 이미지와 단독 소유권을 증명할 수 없는 BuildKit 캐시

## 승인과 정리 후 검증

- 파괴적 작업은 위 보고에 대한 명시적 승인 뒤에만 수행한다.
- 정리 후 Git 상태, worktree 목록, 프론트 설치·테스트·타입 검사·린트·빌드와 Docker 서비스 health를 관련 범위에 맞게 확인한다.
- 논리적 제거량과 실제 호스트 여유 공간 변화는 분리해 보고한다.
- 보존 대상이 사라졌거나 서비스 검증이 실패하면 추가 정리를 중단하고 상태를 보고한다.
