---
schema_version: 1
project: ai-workshop
scope: repository-local caches, explicitly audited project pytest directories in Windows Temp, completed worktrees, and project-owned Docker artifacts
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
| 공개 기록 데이터 | Publishing 설정이 가리키는 공개 SQLite DB와 부속 파일 | 공개 snapshot·철회 순서·멱등 이력이므로 캐시 정리에서 제외한다. DB 파일을 삭제하거나 초기화해 철회·공개 상태를 복구하지 않는다. |
| 공개 준비·승인 자료 | `.local-data/publishing-preparation` | 검토한 편집본, 비공개 출처 목록과 승인 해시를 보존한다. 에이전트 임시 리뷰 diff와 구분하며 공개 DB에 적용됐다는 이유만으로 자동 삭제하지 않는다. |
| 실행 모델 자산 | `.local-data/models/ocr/<model-kind>/<artifact-sha256>` | 매니페스트로 검증·설치된 불변 OCR 실행 의존성이므로 캐시라는 이름만으로 제거하지 않는다. 참조 프로파일, 실행 중 worker와 재프로비저닝 가능성을 모두 확인해야 한다. |
| 모델 준비 산출물 | `.local-data/models/p/<runtime-role>`, `.local-data/models/ocr/staging/<exact-id>` | 최종 불변 경로의 전 파일 크기·SHA-256 검증과 실제 smoke가 끝난 뒤에만 정확한 경로별 정리 후보로 보고한다. |
| 기타 모델 캐시 | `.local-data/models`의 위 분류 외 경로 | 재다운로드 가능성, 사용 중 프로세스와 승인된 모델 출처를 확인한 경우에만 후보로 보고한다. |
| 프론트 의존성 | `frontend/node_modules` | `frontend/pnpm-lock.yaml`로 복원 가능하고 개발 프로세스가 사용하지 않을 때만 후보로 보고한다. 루트 `node_modules`는 만들지 않는다. |
| 프론트 패키지 캐시 | `frontend/.pnpm-store` | junction 경계와 복원 가능성을 확인한 경우에만 후보로 보고한다. |
| 레거시 루트 의존성 | `node_modules` | 프론트 독립 구조 전환이 검증된 뒤에만 일회성 제거 후보로 보고한다. |
| 레거시 루트 패키지 캐시 | `.pnpm-store` | 모든 junction 대상과 프론트 설치 검증을 확인한 뒤에만 일회성 제거 후보로 보고한다. |
| 정적 분석 캐시 | `.mypy_cache`, `.ruff_cache`, `backend/.mypy_cache`, `backend/.ruff_cache` | 생성 도구가 실행 중이 아니면 재생성 가능한 후보로 보고한다. |
| 테스트 임시물 | `.local-data/pytest-tmp`, `backend/.pytest-tmp`, `backend/.pytest-<task-id>`와 루트의 명시적으로 식별된 pytest 임시 디렉터리 | 실제 테스트 데이터가 아닌지 확인한 뒤 후보로 보고한다. 작업별 경로는 고정 문자열로 확인하며 와일드카드로 삭제하지 않는다. |
| 프로젝트 에이전트 임시 기록 | `.local-data/project-agent-work/<task-id>/` | 미해결 작업은 보존한다. `verified` 작업만 정확한 task 경로 정리 후보이며, reparse point 또는 임시 루트 밖 경로는 차단한다. |
| 빌드 산출물 | `frontend/.next`, `frontend/tsconfig.tsbuildinfo`, `backend/build` | 해당 빌드가 재현 가능하고 배포 입력으로 사용 중이지 않을 때 후보로 보고한다. `.next`가 실행 중인 Next.js 프로세스에 사용되는지 먼저 확인한다. |
| 제거된 Vite 산출물 | `frontend/dist` | Next.js 전환 뒤에는 생성하지 않는다. 남아 있다면 경로와 Vite 프로세스 부재를 확인한 뒤 일회성 제거 후보로 보고한다. |
| 도구 산출물 | `.superpowers` | 목업, 최종 검증 보고서와 선별 실패 기록을 먼저 보존하고 중간 상태와 재생성 가능한 diff만 후보로 보고한다. |

프로젝트 에이전트 임시 기록의 상태 전이와 정리 게이트는 [temporary work lifecycle](docs/project-agents/governance/temporary-work-lifecycle.md)를 정본으로 사용한다.

### 저장소 밖 pytest 산출물

- Windows Temp 전체나 `pytest-of-<사용자>` 부모 디렉터리는 정리하지 않는다.
- 당시 후보는 `<사용자 Temp>/pytest-of-<사용자>/pytest-41`, `pytest-42`, `pytest-43`으로 한정했다.
  공개 문서의 경로는 비식별 표기이며 실행 대상 경로가 아니다. 재정리 시 절대경로를 새로 확인하고 승인받는다.
- 프로젝트의 합성 fixture 생성 코드와 경로·파일 목록을 대조하고, reparse point 부재와
  테스트 프로세스 종료를 다시 확인한 뒤 새 조사 보고에 대한 명시적 승인을 받는다.
- 다른 번호의 디렉터리는 자동 포함하지 않는다. 회귀 테스트 소스와 사용자 원본은 보존한다.
- 앱 DB에 남은 합성 테스트 레코드 정리는 캐시 삭제가 아닌 별도 데이터 복구 작업이다.
  DB 자체·DB 파일·Docker 볼륨은 삭제하지 않는다.

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
- BuildKit cache는 커밋된 AI Workshop Dockerfile의 고유 명령 또는 그 전용 build chain으로 소유권을 증명하고, `private`, `reclaimable`, 현재 이미지와 비공유 상태를 모두 확인한 정확한 cache ID만 후보로 보고한다.

### 차단 및 공유 리소스

- 프로젝트 단독 소유권을 증명할 수 없는 BuildKit 캐시는 정리하지 않고 사용량만 보고한다.
- 현재 이미지 또는 다른 리소스와 `shared` 상태인 BuildKit cache는 제거하지 않는다.
- 전역 일괄 정리 기능은 다른 프로젝트의 이미지, 컨테이너와 캐시를 포함할 수 있으므로 사용하지 않는다.
- Docker 볼륨은 회수 가능으로 표시되더라도 이 정책의 제거 대상이 아니다.
- 이미지가 다른 이미지의 기반이거나 컨테이너 참조 관계가 불명확하면 보존한다.

### Docker Desktop 저장소 회수

- BuildKit과 image의 논리 삭제량, Docker Desktop 가상 디스크의 실제 할당량과 Windows host 여유 공간을 각각 측정한다.
- 가상 디스크 압축은 논리 정리 뒤 자동 회수가 실패한 경우에만 별도 후보로 보고한다.
- 압축 전에 모든 AI Workshop 서비스를 정상 종료하고 Docker Desktop과 WSL이 가상 디스크를 사용하지 않는지 확인한다.
- 정확한 `docker_data.vhdx` 한 개만 대상으로 하며 Docker Desktop의 data reset, volume 삭제 또는 광범위한 WSL 정리는 사용하지 않는다.
- 서비스 중단과 가상 디스크 압축은 BuildKit cache 삭제 승인과 분리해 별도 승인을 받는다.

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
