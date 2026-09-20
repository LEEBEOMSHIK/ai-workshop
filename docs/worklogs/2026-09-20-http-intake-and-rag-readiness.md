# HTTP 수신 예약 상세화와 RAG 테스트 준비 상태

- 날짜: 2026-09-20
- 요청: 다음 HTTP 업로드 임시물 작업 진행 및 RAG 테스트 가능 시점 확인
- 확인 코드: `39aa5f7`
- 상세안: [HTTP intake](../superpowers/specs/2026-09-20-http-upload-intake-design.md)

## HTTP 수신 계약 조사

메인은 수신/저장 계약·요구·문서를 정리했고 별도 담당이 인증·multipart·원본 예약과
frontend 호환성을 조사했다. 독립 검토자가 DB/프라이버시/실패 경계를 검토했고 설계 차단 없음으로 판정했다.

설치된 FastAPI는 File/Form route에서 인증 dependency보다 먼저 request.form을 호출한다.
frontend는 신규 문서의 file을 folder_id보다 먼저 보낸다. 따라서 Request-only endpoint로
바꾸고 인증·공간 권한·영속 예약을 끝낸 뒤 bounded incremental parser로 수신한다.
전체 HTTP body를 별도 파일에 저장하지 않고 예약된 payload 하나에만 쓴다.

예정 document/version ID는 원본 예약까지 재사용한다. 실제 source가 없는 실패 업로드는
별도 workspace 목록으로 발견하고, 최종 실제 source와 원본/intake 관계는 함께 확정한다.
기존 문서 pin과 planned version을 구분하며 문서 임시물의 actual-source claim을 위조하지 않는다.

이 단계는 상세 설계다. 제품 코드·실사용 DB·설정·서버·사용자 자료는 변경하지 않았다.
검토의 terminal suffix 별도 검사·callback 누적 한도·명명된 DB 연결 제약·권한 확인 목록 문구를
상세안에 반영했다. 상대 링크·UTF-8·공백 검사와 git diff --check를 통과했다.
상세안 확인 후 구현 계획으로 연결한다.

## RAG 실행 상태 — 2026-09-20 14:55~15:00 KST

RAG 담당이 소켓 연결과 Docker 상태, 설정의 존재 여부만 읽기 전용으로 확인했다.
원본 본문·인증 쿠키·비밀값은 읽어 출력하지 않았고 모델 호출·업로드·migration은 하지 않았다.

| 대상 | 확인 결과 |
| --- | --- |
| API 18000 / frontend 5173 | 연결 실패 |
| PostgreSQL 15432 / Redis 6379 / Elasticsearch 9200 | 연결 실패 |
| 프로젝트 compose 실행 컨테이너 | 없음 |
| 다른 프로젝트 서비스 | 기존 tpmp-db-local만 실행, 변경 없음 |
| 원본/RAG artifact/index/temp binding | `.env`에 미설정 |
| 원본/RAG object root marker | 없음; temporary root도 미설정 |
| DB migration / 기존 색인 / 저장 구성 | 연결 불가로 현재 상태 미확인 |
| Generation Profile/Deployment health | 미확인; `.env`의 endpoint reference map/legacy URL도 없음 |

환경 변수 등 다른 방식의 설정 주입 여부는 확인되지 않았다. 과거 migration0034 기록을
현재 실제 DB 확인 결과로 사용하지 않는다. 접속 불가를 데이터 삭제/유실로 해석하지 않는다.

실행 증거는 canonical compose 파일의 `docker compose ... ps --format json`,
`docker ps`와 `.env`에서 안전하게 추출한 loopback 포트의 소켓 연결 결과다.
전체 `.env`, DB URL, provider secret map 값은 결과에 노출하지 않는다.

## 언제 무엇을 테스트할 수 있는가

HTTP 추적·일반 Jobs·영구 삭제 전체가 끝나야 RAG 검색/답변 테스트를 할 수 있는 것은 아니다.
현재 지연 요인은 실행 환경과 적용/설정 readiness이며 날짜로 완료 시점을 확정할 근거는 없다.

| 테스트 | 시작 조건 |
| --- | --- |
| 기존 색인 문서 검색·근거/원문 | DB·ES·API·frontend 기동, 코드/schema 호환, 로그인 및 search_ready |
| 근거 제한 LLM 답변·인용 | 위 조건과 Generation Profile/Deployment·실제 runtime health·권한/데이터 정책·answer_ready |
| 새 문서 업로드→검색 | 현재 코드 기준 migration0046, 원본/RAG/index/temp binding·marker, 동일 버전 API/worker/beat |
| PDF preview | 새 임시 저장소와 코드/schema 준비; OCR 모델은 preview 자체에 필수가 아님 |
| DOCX 이미지/스캔 PDF OCR | 문서 처리 프로파일과 고정 10개 모델·실제 OCR runtime 준비 |
| 완전 영구 삭제 | HTTP intake/일반 Jobs/전체 참여자·writer 종료·잔존 검증·삭제 실행기 통합 이후 |

권장 검증 순서는 실행 환경 확인·승인된 적용 → 합성 TXT/Markdown 업로드와 검색 →
LLM 답변·인용 → PDF/DOCX/OCR이다. 리랭커는 선택 사항이며 없다고 답변 테스트를 막지 않는다.
OCR writer 종료 미확인 시 임시 파일이 성공 후에도 보존되는 현재 한계를 함께 관찰한다.
구체 적용 명령은 [로컬 실행 정본](../runbooks/local-development.md)을 따른다.

## 자동 검증과 구분

직전 구현의 관련 단위/격리 통합 706건과 독립 검토 통과는 실행 환경 readiness를 대신하지 않는다.
기존 ingestion 통합 fixture는 artifact_binding_missing 8실패/5통과이며 ES 통합은 실행하지 않았다.
실제 전체 업로드→색인→답변을 이미 통과한 것으로 보고하지 않는다.
이 문서 작성 단계에서는 추가 애플리케이션 테스트나 실사용 RAG smoke를 실행하지 않았다.
