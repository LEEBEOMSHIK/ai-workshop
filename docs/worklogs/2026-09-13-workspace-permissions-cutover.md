# 구성원 권한 로컬 적용

## 범위

사용자 승인으로 기존 로컬 DB0032를 백업·복원 검증한 뒤0033에 적용했다.
호스트 API18000·Celery solo worker·beat만 중지/재시작했다. 프론트5173과 기존 Docker 인프라는 유지했다.
새 사용자·샘플 업로드·모델 호출·실사용 구성원 권한 편집은 수행하지 않았다.

## 검증

- 모든 프로젝트 Python writer를 확인하고 beat 중지, active/reserved/scheduled 각각0 확인 후 worker 정상 종료, API 중지.
- 다른 DB client0 확인. 백업 archive 읽기, 크기·SHA-256, 전후 스냅샷 동일 검증.
- 별도 복원 DB에서0032 전체 테이블/컬럼 데이터·시퀀스가 원본과 정확히 같은지 확인 후0033 예행.
- 실제 적용 직전 dump 해시·복원 DB·원본 불변 재검사.
- 실제0033 및 복원 DB 독립 읽기 전용 검증: 기존68테이블 데이터·전체3시퀀스 보존, 변경 후70테이블 전체 스냅샷 일치.
- 기존 구성원 권한 매핑·신규 기본값·제약·불변 감사 trigger 및 비어 있는 감사 테이블 확인.
- 재시작 후 직접/proxy health 정상, OpenAPI capabilities/members/개별 member 경로 확인, worker pong.
- 프론트 관련3파일54테스트 통과(30.61초), typecheck exit0. 최초 exec vitest 명령은 실행 파일을 찾지 못해 실패했고 기존 test 스크립트로 재실행했다.
- 전체 프론트 lint와 git diff --check 통과.

## 보존 자료와 남은 확인

백업은 Git 제외 `.local-data/backups/workspace-permissions-20260913`에 보존한다.
복원 DB `ai_workshop_permissions_restore_20260913`는 사후 검증용으로 남아 있다. 실사용 DB가 아니며 정리 시 정확한 대상을 확인해야 한다.
브라우저에서 `/workshop/workspaces`의 로그인 화면까지 확인했다. 인증 후 실제 패널·화면 폭 확인은 사용자 로그인 대기다.
사용자는 현재1명이다. 소유자 행은 편집 불가가 정상이며 다른 구성원 저장·충돌·권한 철회는 격리 테스트 범위다.
전체 RAG 사용 준비 완료를 뜻하지 않는다. 도메인 활성 연결·실제 PDF/OCR 및 LLM 답변 검증은 별도로 남아 있다.
