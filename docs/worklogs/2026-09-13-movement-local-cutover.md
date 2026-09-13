# 파일함 이동 로컬 적용과 커밋

## 사용자 요청과 적용 범위

사용자는 커밋·푸시와 테스트 가능한 로컬 서버 재시작을 요청했다.
기능 커밋은 `29817ba`이며 main에서 기존 기본 관리·트리·이동 서버/UI·RAG 정합성 관련70파일을 묶었다.
references, 원본 문서, 환경 비밀값, 캐시와 백업은 제외했다.

GitHub origin/main 푸시는 실행 전 안전 검토에서 대상별 명시 승인 부족으로 차단됐다.
원격 대상 확인 승인을 요청했으며, 이를 우회하지 않고 로컬 적용을 진행했다. 푸시 결과는 승인 후 별도 기록한다.

## DB0034 의미

`0034_asset_metadata_revision`은 별도 DB가 아니라 Alembic 스키마 변경 번호다.
folders/documents에 양의 정수 metadata_revision을 기본값1로 추가한다. 파일 이동 시 요청한
revision과 현재 값을 비교해 동시 변경 덮어쓰기를 막는다. 파일 내용 버전·임베딩 버전과 다르다.
기존 문서/폴더 위치, 원본, 색인과 생성 모델 설정은 변경하지 않는다.

## 데이터 보존과 실제 적용

- 기존 로컬 PostgreSQL `127.0.0.1:15432/ai_workshop_local_clean`,0033→0034.
- DB system identifier를 비교해 기존 프로젝트 PostgreSQL 컨테이너와 같은 인스턴스임을 확인했다.
- beat 중지, worker active/reserved/scheduled 모두0 확인과 정상 종료, API/프론트 중지.
- 다른 DB client0을 확인하고 새 custom-format 백업을 만들었다(435,714bytes).
- 별도 `ai_workshop_movement_restore_20260913`에 복원 후 전체 snapshot 일치 및0034 예행 검증.
- 실제 적용 직전 백업 해시·예행 결과·원본 snapshot 일치를 재확인했다.
- 실제0034 적용과 재검사에서 기존69개 업무 테이블의 기존 컬럼 데이터 및 모든 시퀀스 보존.
- 새 컬럼2개의 기본값1·NOT NULL·양수 check constraint를 확인했다.

백업은 `.local-data/backups/movement-release-20260913`에 보존한다. 복원 DB도 보존한다.
원본 bytes를 다시 해시한 검사는 아니며, DB에 저장된 원본 해시·식별자·버전 등 기존 컬럼의 불변을 검증했다.
기존 파일을 이동하거나 샘플을 업로드하지 않았고 downgrade·삭제·재색인은 하지 않았다.

## 재검증과 실행 상태

- 기존 backend 환경의 관련 단위311건 통과. 기존 Starlette/httpx deprecation 경고1건.
- 프론트 assets/domain cabinet/selection panel/conversation12파일152건 통과(284.17초).
- 후보 파일 독립 release/privacy 검토, maintenance helper 독립 안전 검토, staged scope/check 통과.
- 호스트 API18000, Next.js5173, Celery solo worker와 beat를 기존 설정으로 시작했다.
- API health200, 프론트 API proxy health200, 로그인 화면200 및 문서/폴더 move 경로 등록 확인.
- 재시작 worker pong, 실제 포트 소유 프로세스, 기존 인프라3개 healthy 확인.
- 앱 컨테이너를 추가하지 않았다. PostgreSQL·Redis·Elasticsearch 인프라를 유지했다.

## 사용자 확인과 남은 항목

`http://127.0.0.1:5173/workshop/workspaces`에서 로그인 후 전사/개인 공간의 파일함을 연다.
이동 버튼 또는 내부 드래그로 목적지를 선택하고 확인한 뒤 새 위치·미리보기·새로고침을 확인한다.
도메인 파일함/대화 패널에서도 선택한 문서가 이동 후 올바른 범위에 남는지 확인한다.
인증된 실제 자료 이동·외부 LLM 응답까지 자동으로 검증했다고 주장하지 않는다.

복구 중 기존 뷰어를 닫을 때의 키보드 초점 Minor는 이전 기록대로 후속 보완이다.
