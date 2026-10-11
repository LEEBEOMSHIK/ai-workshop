# GitHub 기본 브랜치 main 전환 — 2026-09-30

사용자가 원격 기본 브랜치가 main이 아닌 점을 보고하고, main 변경과 영향 점검을 승인했다. 원격 설정과 로컬 origin/HEAD만 변경했다.

## 변경 전 영향 점검

- 원격 HEAD: `feature/rag-ai-search-first-slice`, 커밋 `47cba3ac6c0749ba992b3983cf3fea90f809668d`.
- 원격 main: `2ea1396a8dfb4f717650d2c6a64a52f9cba75947`. 로컬 origin refs와 원격 SHA 일치 확인.
- `git rev-list --left-right --count origin/feature/rag-ai-search-first-slice...origin/main`: `0 188`. 기존 기본 브랜치의 모든 커밋이 main에 포함되며 main에만 후속 188개가 있다. 이력 누락이나 분기 충돌이 없다.
- GitHub 열린 PR 0건. 양쪽 브랜치에 `.github` 자동화 파일 없음.
- GitHub Pages 비활성, 등록 웹훅 없음, 설치 GitHub App 없음.
- Ruleset과 classic branch protection 미설정. 이 변경이 기존 보호를 없애는 상황은 아니다. main 보호 정책 설정은 별도 관리 과제로 남는다.
- 외부 서비스에서 저장소 기본 브랜치를 직접 읽는 연동은 GitHub 화면만으로 모두 확인할 수 없다. 위에 확인한 저장소 자동화 범위에서 차단 사항은 발견하지 않았다.

## 반영과 검증

GitHub General 설정에서 main 선택 후 기본 브랜치 변경을 확정했다. `git ls-remote --symref origin HEAD refs/heads/main refs/heads/feature/rag-ai-search-first-slice`에서 `HEAD → refs/heads/main`, 커밋 `2ea1396...`을 확인했다. 기존 feature 브랜치 SHA도 그대로다.

`git remote set-head origin -a` 실행 후 `git symbolic-ref refs/remotes/origin/HEAD`가 `refs/remotes/origin/main`인 것을 확인했다. GitHub 설정 화면에서도 Default branch main을 확인했다. 캡처는 `.local-data/project-agent-work/default-branch-20260930/main-default.png`다.

변경 후 새 clone·저장소 기본 화면·새 PR의 기본 대상은 main이다. 다른 기존 clone에서도 필요하면 `git remote set-head origin -a`로 로컬 별칭을 갱신한다. 기존 브랜치 이름·커밋·작업 파일을 변경하는 작업은 수행하지 않았다. 실행 중 로컬 서버는 이 원격 설정 변경으로 재시작되지 않는다.

애플리케이션 코드 변경이 없으므로 앱 테스트 대신 원격 HEAD·브랜치 SHA·로컬 별칭·GitHub 설정을 검증했다.

## 문제 이력 연결

본래 관리자 DB에 ISSUE-00012(`38dac7f8-fe1a-47d9-ac7c-795e05af1b50`)를 검증 완료로 등록했다. 문서 `05079e38-a35d-492f-96a7-066ca54bc9f7` 버전 1 연결을 화면에서 확인했다. DB 본문은 이 연결 확인 문단 추가 전의 불변 스냅샷이다. 기존 main 보호 미설정과 다른 clone 갱신 안내, 외부 서비스 전체 미확인은 남은 관리 항목으로 기록했다.
