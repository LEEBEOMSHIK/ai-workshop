# 본래 환경 복구와 RAG 적용

- 날짜: 2026-09-20
- 요청: 별도 환경 성공만으로 완료하지 않고 기존 마스터 계정·자료가 있는 본래 환경에 반영·검증한다.
- 제약: 새 환경·계정·더미 문서를 추가하지 않는다. 필요한 내용 인계·검증 전에 sandbox를 삭제하지 않는다.
- 역할: 메인 실행·통합, DBA migration preflight, RAG 기존 자료 검증, 독립 설정·보존 검토.

## 차이와 전환

원래 `.env`는 PostgreSQL 15432/ai_workshop_local_clean, Redis6379/3, ES9200,
API18000이었다. 원래 인프라 컨테이너는 중지 상태였고 DB는0034였다. sandbox가18000/5173을
사용하며 별도 계정을 요구한 것이 기존 마스터 로그인이 되지 않은 원인이었다.
원래 컨테이너3개를 재시작하고 기존 volume을 그대로 사용했다. 다른 프로젝트는 변경하지 않았다.

원래 API/worker writer 프로세스 부재와 DB 다른 client0, Redis대기작업0을 확인했다.
ES의 실제 cluster UUID와 기존 index7개/alias3개를 확인했다. DB만으로 ES복구까지 검증했다고 주장하지 않는다.
기존 backups 아래 `original-rag-cutover-20260920`에 dump(436013bytes), .env, 원본30개와
해시를 보존했다. 비밀값과 본문은 Git·로그·채팅에 기록하지 않았다.

기존 PostgreSQL 내부의 일시 복원 검증 DB `ai_workshop_restore_rag_20260920`에 백업을 실제
복원하고 명시적 DATABASE_URL override로0034→0048 리허설을 수행했다. API/worker는 연결하지 않았다.
69개 기존 테이블의 기존 열 전체 값이 원본과 동일함을 해시 비교했다. 본래DB도0048적용 후
복원 검증본과95테이블 전체 값을 비교해 일치했다. users·password hash·권한·문서가 보존됐다.
0035/0037 사전검사 issue0과 필요한 unique constraint를 DBA가 독립 확인했다.

원래 `.local-data/objects` 경로와30개 원본의 해시를 유지했다. 부재가 확인된 원본/RAG marker와
새 전용 temporary root marker를 provision하고 실제 ES cluster binding을 설정했다.
legacy 원본·Jobs·RAG를 추정 backfill하지 않았다. 공유 E5 cache와 OCR모델10개를 재사용하며
새 모델 다운로드는 없다. 원래 Codex/provider 설정은 유지하되 검증에서는 외부생성을 호출하지 않는다.

sandbox Jobs3개 성공, artifact attempts6개closed, Redis queue비어있음을 확인했다.
PID·생성시각·명령을 확인한 실행프로세스 트리만 중지했다. DB·파일·volume은 보존했다.
본래API/worker/beat/frontend를 같은18000/5173에 시작하고 direct/proxy health200을 확인했다.
프로세스 기록과 로그는 기존 `.local-data/dev-logs/original-rag-*`다.

## 검증과 남은 경계

독립 감사: 본래0048/95tables, 기존Jobs6개 revisionNULL, marker3종일치, 원본30개 bytes일치 확인.
실제 마스터 암호 로그인은 사용자 확인을 요청했으며 암호 변경·새계정 생성·세션토큰 발급으로 우회하지 않는다.
RAG는 새더미문서 없이 기존문서/명시extractive구성의 application service 검증을 진행한다.
LLM생성·인용 및 OCR품질 실검증은 검색 성공과 구분한다.

## 실제 검색 검증

메인이 읽기 전용 application service 스크립트를 직접 재실행해 exit0/passed=true를 확인했다.
기존 문서2개의 BM25와 기존 extractive 고정 버전의 E5 hybrid1건이 supported,
원문 버전·선택 projection 일치, generation=not_requested였다. 구성 외 공간은 not_found로 차단했다.
기존 원본3개는 DB의 크기·SHA256과 일치했다. HTTP 암호 로그인 검증을 대신한 것으로 보고하지 않는다.
과거 실패1건(chunk_tokenizer_unavailable)은 유지하며 새 추적 소유권 계약을 우회해 강제 재시도하지 않았다.

과거 hybrid 구성 최신 버전은 generative이므로 그 과거 extractive 성공을 현재UI 준비 완료로
보고하지 않는다. 기존 프로파일을 재사용하는 검색 전용 구성1개를 본래 환경에 이관해 최신 경로를 검증한다.
기존 LLM 구성과 기본값은 보존한다. 신규 문서·계정·모델 프로파일은 만들지 않는다.

일시 복원DB는 검증·데이터 비교·시퀀스3개 일치 및 연결0 확인 후 정확한 이름으로 제거했다.
본래DB와 sandboxDB·파일·volume은 보존한다. 복구용 backup은 기존 backups 아래 보존한다.
환경 로더는 .NET 환경 키 열거로 상속 AI_WORKSHOP 값을 제거한 뒤 .env를 적용하도록
문서화하고 실제 실행으로 검증했다(PATH/Path 중복이 있는 PowerShell Env: 열거 문제도 회피한다).

## 검색 구성 이관과 검토

`E5 하이브리드 검색`은 기존 indexing/retrieval/DPP와 공간 구독을 재사용했다.
RagConfigurationService를 통해 구성·버전·answer policy·공간 구독 각1행만 추가하고
문서·버전·profile·Job·dispatch·projection·build·artifact 증가는0임을 commit 전에 검사했다.
일반 최신 configuration_id 경로의 선택 문서 검색도 supported와 정확 원문 출처를 확인했다.
실험 구성으로 유지하며 기존 default/generative 구성을 바꾸지 않았다.

최초 생성 스크립트의 PowerShell 인코딩 때문에 새 구성 표시명이 손상됐다. Unicode escape로
재실행 스크립트를 고쳤다. 불변 row 트리거가 일반 UPDATE를 막으므로, 메인이 방금 생성한
정확한 ID·owner·손상 이름·중복 없음 조건을 확인한 후 ACCESS EXCLUSIVE 잠금의 단일 transaction에서
해당 구성 테이블의 불변 트리거 하나만 잠시 비활성화하고 name1행을 보정했다. commit 전에
트리거가 다시 enabled(O)이고 모든 구성 row가 그 name 외에는 동일함을 확인했다.
기존 사용자 구성·버전·프로파일·권한은 변경하지 않았다. 상시 불변성 규칙이나 코드 변경은 없다.

독립 감사에서 marker·원본·DB보존과 검색구성 생성 경계를 확인했다. 완전 이관 완료로
확대 보고하지 않으며, 실제 마스터 로그인/화면 사용 및 과거 failed legacy문서 문제는 남은 항목이다.

최종 메인 재실행: corrected-name 구성 재사용(created=false), 검사13테이블 증가0,
latest search supported/17 evidence/exact source/generation not_requested, exit0/passed=true.
독립 검토자가 실제 표시명과 immutable trigger O를 다시 확인했다. 문서 링크·AGENTS200줄·
프로젝트 역할 계약·git diff 공백 검사를 통과했다. 제품 소스 변경이 없어 기존 전체 단위 테스트는 반복하지 않았다.
