# RAG 기능 우선순위와 본래 환경 반영 — 2026-09-30

사용자 요청에 따라 RAG 기능·오류 처리·본래 사용 검증을 지속 품질 튜닝보다 먼저 처리한다. 이번 단위는 `2ea1396`의 인용 실패 진단·실패 이전 측정값 보존 반영이며, 모델·검색 구성·활성 연결을 바꾸지 않았다.

## 실제 수행과 증거

- infrastructure-docker-engineer가 본래 설정·프로세스·활성 요청을 읽기 전용으로 점검했다. integration-e2e-verifier는 재시작 담당과 독립적으로 기존 DB·실제 브라우저를 검증했다.
- beat 중지 후 drain 재확인: 실행/평가/작업/모델 슬롯/queue/unacked 모두 0. 원본 DB·계정·파일을 보존하고 기존 `.env`로 API·worker·beat만 재시작했다. migration·bootstrap·새 환경 생성·큐 삭제는 하지 않았다.
- API launcher42540/actual39672, worker29040/21840, beat8056/74296. frontend5173과 Docker는 유지했다. 로그는 `.local-data/dev-logs/original-rag-{api,worker}-functional-20260930-161515.*.log`, beat `161608`이다.
- 직접 API와 localhost 프론트 경유 health200, worker ready. 무인증 모니터링 API는401을 유지하고 새 API 로그에서500/Traceback은 관측하지 않았다.
- 인용 실패·실패 측정값 회귀22개 통과(1.88초). 최초 테스트 프로세스의 합성 secret 길이 부족은 설정 최소길이를 맞춘 뒤 재실행했다. 본래 `.env`는 변경하지 않았다.
- 독립 실제 화면: 과거 인용 실패의 일반 사유와 실패 단계 시간, 유사도10후보, 원문 PDF2쪽, 비교 실패 지표의 ‘확인 불가’ 표시를 확인했다. 과거 미기록을0%나 신규 세부 사유로 표시하지 않았다.
- 생성형 평가195시도 상태·result digest fingerprint가 반영 전후 동일하다. 실행192건(완료163/실패28/중단1), 신규 모델 호출·평가 재시도·backfill 없음.
- ISSUE-00005에 인용 진단 문서 `192c8b2b-44e0-4b59-b5ab-7f842fb36399` 버전1 및 측정값 문서 `6b220cbd-9d46-4033-88d1-e764c6b6756a` 버전1을 정상 관리자 UI로 연결했다.
- 별칭 복구는 다른 원인의 결함으로 ISSUE-00013(`d297b5d8-c059-4eee-8f30-59a33a9ee195`)을 등록했다. ISSUE-00005의 진행 이력과 남은 작업도 기능 검증/지속 품질로 현행화했다. 문서 연결 뒤 최초 입력 양식의 revision이 오래돼409로 보호 거절됐으며 최신 내용을 다시 열어 저장했다. 충돌 검사를 우회하거나 이력을 덮어쓰지 않았다.

신규 실패의 실제 DB 저장 E2E는 아직 수행하지 않았다. 새 코드의 실패 수집·직렬화는 오프라인 회귀로 검증했으며 실제 과거 기록 읽기 성공과 구분한다. 전체 RAG 기능 완료 또는 답변 품질 해결을 주장하지 않는다.

## 기능 우선 작업

1. 첫 질문 기준 대화 생성·첨부 초안: 현재 `ConversationPage.ensureSession()`은 `createConversation()`을 호출하고 첨부에 그대로 전달된다. 화면 방문 자체는 생성하지 않지만 파일 첨부/첫 전송 중간 실패는 빈 세션을 남길 수 있다. [승인된 흐름](../superpowers/specs/2026-09-27-first-question-conversation-design.md)의 구현 계약 검토·원자적 접수·멱등성·초안 수명주기 구현이 남아 있다.
2. 미종료 별칭 요청의 정상 복구: 새 worker에서도 별도 profile `1d4eff32-d337-4210-b649-a3a90b697a93`의 parity 점검이 `rag_index_attempt_busy`로 반복 실패한다. open index attempt는0이지만 `rag_alias_operations`에 open operation `f61a8fde-5a88-4690-be51-56e8f14ae696`이 존재한다. `AliasJournal.reserve`의 같은 cluster/alias 예약 충돌과 일치한다. [실행서](../runbooks/local-development.md)의 종료 증거 없는 원장 해제 금지 규칙을 지키며, 원격 writer 종료 증거와 exact operation/target 검증을 포함한 정식 복구 설계가 필요하다. 현재 사용 중인 E5와 다른 프로파일이며 전체 검색 불가로 확대 해석하지 않는다.
3. 본래 계정에서 세션 저장·재개·문서 선택·실제 파일 드롭·첨부 상태와 원문 접근의 미완료 검증, 신규 실패 저장·표시 및 최신/누적 실행 이력 구분을 마감한다.

답변 정답률, Q09 비교 결론, 새 문서 일반화, 문맥 선택 튜닝과 생성 속도는 지속 품질 작업이다. 선택형 v5는 코드가 로드됐지만 실제 프로파일 생성·승인·평가·승격은 수행하지 않았다.

로컬 독립 근거: `.local-data/project-agent-work/rag-functional-rollout-20260930/infra/rollout-audit.md`, `review/independent-review.md`. 질문/문서 본문·계정·비밀값·원시 로그를 이 문서에 포함하지 않았다.

DB 연결 확인: 이 보고서의 본문 스냅샷을 문서 `c3a4cffd-8427-4d0b-9df9-6b714d81f0d1` 버전1로 등록해 ISSUE-00013에 연결했다. 이 확인 문장은 등록 후 로컬 기록이며 불변 DB 버전1에는 추가하지 않았다.
