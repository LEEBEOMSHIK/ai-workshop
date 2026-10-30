# RAG 종료 수정의 본래 API 반영과 저장 상태 확인

2026-10-21. 사용자가 [실행 기한 만료 경합 수정](2026-10-21-rag-expired-turn.md)의 본래 환경 확인을 승인했다. **API 반영·정상 기동·조회한 DB 8개 테이블 보존과 로그인 후 기존 취소 미종료 대화의 안내·상태 새로고침을 확인했다. 입력 보존·새 만료 표식·실모델 종료 수용은 미완료다.** 12B/GPU 성능 개선 보류와 기존 품질 기준을 유지한다.

## 범위와 사전 확인

실행 서버를 교체하는 중간 위험 작업으로 분류했다. 메인은 백엔드·프론트엔드·RAG/AI 런타임과 읽기 전용 DB 관측을 담당하고, 독립 검증 담당자는 조회 도구·재기동 경계와 보존 증거를 검토했다. 제품 코드·DB 스키마·모델 설정 변경, 설치·다운로드와 새 환경·계정은 범위에 포함하지 않았다.

기존 18000 API는 10월 19일 기동된 자동 reload 없는 프로세스였다. 이전 Codex 작업의 기동 기록과 실제 PID·실행 파일·명령·생성 시각·포트 소유자를 대조했다. 5173의 Next 개발 서버와 11434 Ollama는 재시작하지 않았다. 프론트엔드는 HMR을 사용하므로 오래된 기동 시각만으로 수정 미반영이라고 판단하지 않는다.

기존 설정 해석기를 통해 본래 로컬 DB에 연결했다. 접속과 트랜잭션 모두 읽기 전용으로 제한하고, 고정된 8개 테이블의 행 수·지문 및 실행 상태 메타데이터만 조회했다. 질문·답변·문서 본문이나 인증 정보를 추출하지 않았다. DB 내부에서 행 지문을 집계했으며 DB 전체 백업이나 암호학적 무결성 증명은 아니다.

14:16 KST 관측 및 재기동 직전 재확인에서 대화 요청·실행·평가 실행·평가 시도·job의 running은 0이었다. 평가 실행·시도의 pending도 0이었다. Ollama `/api/ps`의 적재 모델은 0이었다. 다음 과거 상태는 유지했다.

- 대화 5개, 요청 23건: 완료 17, 실패 4, 취소 2. 취소 중 종료 미확인 1건이 있다.
- job은 queued 1건이 남아 있다. API 재시작으로 이를 처리하지 않았다.
- 새 `conversation_termination_unconfirmed` 및 `provider_termination_unconfirmed` 표식은 저장 상태에 없다. 해당 경계를 실데이터로 재현했다고 보고하지 않는다.

## 반영과 실제 관측

현재 소스의 정상 startup admission을 먼저 통과했다. 백엔드 Python 소스 484개의 SHA-256을 기록하고 재기동 직전·직후 동일성을 확인했다. API는 현재 작업 공간의 백엔드를 새로 import하므로, 종료 수정 외 import 경로에 포함된 누적 변경도 함께 반영된다. 484개는 소스 집합 동일성 확인 수이며 모든 모듈의 실행·동작 검증 수가 아니다.

14:21:37 KST에 확인한 기존 API PID 118988만 종료하고, 같은 Conda Python·Selector 이벤트 루프·127.0.0.1:18000으로 숨김 프로세스 PID 101960을 기동했다. 실행 창은 사용자에게 새로 띄우지 않았다. 방식은 유휴 상태·정확한 신원 확인 후 `Stop-Process`이며, 새 요청 진입을 막는 장치나 graceful drain을 검증한 것은 아니다. 프로세스 교체를 과거 개별 모델 실행의 종료 증거로 사용하지 않았다.

14:25 KST 확인 결과:

- 새 PID가 18000을 소유하며 `Application startup complete.`가 기록됐다.
- `/api/v1/health`는 `ok`, `/api/v1/ready`는 `ready`다. 서버 기동 확인이며 RAG 품질 통과를 뜻하지 않는다.
- Ollama 적재 모델은 0이다. 이번 작업에서 생성·임베딩 요청이나 worker/큐 실행은 하지 않았다.
- 재기동 전후 아래 8개 테이블의 행 수와 집계 지문이 모두 같다. 대화 revision과 실행 상태 집계도 동일하다.

| 테이블 | 행 수 |
|---|---:|
| 대화 | 5 |
| 대화 요청 | 23 |
| RAG 실행 | 477 |
| 생성형 평가 실행 | 11 |
| 생성형 평가 시도 | 539 |
| 생성 실행 감사 | 495 |
| job | 16 |
| RAG 도메인 | 1 |

실행 증거는 [재기동 영수증](../../.local-data/project-agent-work/rag-terminal-live-check-20261021/api-restart.json), [기동·health/ready·포트 확인](../../.local-data/project-agent-work/rag-terminal-live-check-20261021/runtime-after.json), [DB 이전](../../.local-data/project-agent-work/rag-terminal-live-check-20261021/database-before.json)·[이후](../../.local-data/project-agent-work/rag-terminal-live-check-20261021/database-after.json), [사전 소스·상태 관측](../../.local-data/project-agent-work/rag-terminal-live-check-20261021/restart-preflight.json)에 보존했다. 원시 로그와 식별 메타데이터는 로컬 작업 경로에만 두며 Git에 추가하지 않는다.

## 브라우저 경계와 남은 작업

첫 확인 때 Chrome 연결은 정상이었지만 기존 AI Workshop 탭은 로그인 화면이었다. 사용자에게 기존 계정 로그인을 요청한 뒤 아래 후속 확인을 진행했다. 자격 증명·쿠키를 추출하거나 인증을 우회하지 않았다.

`detail` GET은 만료 요청을 복구·저장할 수 있고, 빈 대화 선택은 draft 복원 POST를 유발하므로 단순 조회라고 단정하지 않는다. 로그인 후 직전 읽기 전용 관측으로 기존 5개 대화 모두 요청이 있고 running은 없음을 재확인했다. 대화별 상태를 추가 조회해 실제 취소 미종료 1건이 속한 대화를 선택했으며, 전역 집계를 임의의 대화에 연결하지 않았다. 기본 상태와 대화별 추가 집계는 별도의 읽기 전용 트랜잭션 관측이며 단일 원자적 스냅샷으로 표현하지 않는다.

### 로그인 후 실제 화면 확인

사용자의 로그인 완료 알림 후 기존 Chrome 인증 화면을 확인했다. 현재 계정이 정상 UI에서 접근할 수 있는 기존 합성 자료 대화 1개를 열고, 질문 전송 없이 다음을 확인했다.

| 확인 항목 | 실제 결과 |
|---|---|
| 기존 저장 상태 | 요청 1건, cancelled·execution_terminated=false·conversation_cancelled, 대화 revision 3 |
| 종료 안내 | ‘취소를 요청했습니다. 실행 종료 확인 중입니다.’ 표시 |
| 상태 새로고침 | 버튼을 1회 눌렀고 이후 동일 안내·미종료 상태·revision 유지 |
| 질문·전송 | 모두 비활성화. 종료 미확인 외 도메인 준비 미완료와 Codex CLI 지원 종료 안내도 동시에 표시 |
| 현재 처리 안내 | 요청 모델 gpt-5.5·실제 모델 미확인. 평가에 사용한 로컬 Gemma의 일반 대화 연결 완료로 해석하지 않음 |
| 입력 보존 | 질문 입력이 비활성화되어 시험하지 못함. 임의 DOM·설정 변경 없이 미검증 유지 |
| 새 만료 표식·다음 질문 | 해당 저장 사례와 신규 실행이 없어 실제 수용 미검증. 버튼 비활성화만으로 종료 상태에 의한 차단을 독립 입증하지 않음 |

상태 새로고침 계약은 같은 대화의 해당 버튼 동작이다. 브라우저 전체 reload나 다른 대화 재선택에서 입력 보존을 확인한 것으로 바꾸지 않는다. 두 새 종료 표식 분기의 오프라인 통과와 이번 기존 cancelled/false 분기의 실제 관측을 구분한다.

14:32 KST 이전 관측과 14:36 KST 이후 관측의 RAG 8개 테이블 행 수·지문, 대화별 상태·revision, 작업 상태 집계가 모두 같다. 생성 감사와 평가 시도도 늘지 않았으며 질문·취소·재시도·첨부 POST를 실행하지 않았다. 새 브라우저 검증을 위해 서버를 다시 시작하거나 프로파일을 바꾸지 않았다.

[브라우저 관측](../../.local-data/project-agent-work/rag-terminal-live-check-20261021/browser-check/ui-observation.json), [실제 화면 캡처](../../.local-data/project-agent-work/rag-terminal-live-check-20261021/browser-check/terminal-after-refresh.jpg), [DB 이전](../../.local-data/project-agent-work/rag-terminal-live-check-20261021/browser-check/database-before.json)·[이후](../../.local-data/project-agent-work/rag-terminal-live-check-20261021/browser-check/database-after.json), [독립 브라우저 증거 검토](../../.local-data/project-agent-work/rag-terminal-live-check-20261021/browser-check/independent/final-browser-review.md)를 보존했다. 캡처는 실제 화면의 계정 표시를 제외한 대화 영역이며 합성 화면이나 예시 결과가 아니다.

새 만료 표식에 대한 실제 생성·취소·종료 저장·다음 질문 수용은 실행 범위와 호출 수를 정한 뒤 검증한다. 기존 취소 미종료 1건을 DB 보정이나 강제 종료 확인으로 해제하지 않는다. 종료 증거를 생성할 정상 복구 경로와 별칭·첨부 복구는 별도 미완료다.

## 검증과 보존

제품·테스트 코드는 이번에 수정하지 않았다. 이전 작업의 서버 390개·화면 157개·독립 서버 25개/화면 9개·타입·린트 통과는 [당시 기록](2026-10-21-rag-expired-turn.md)의 오프라인 결과다. 이번 서버 기동 검증과 합쳐 실모델 수용 완료로 표현하지 않는다.

[독립 런타임 리뷰](../../.local-data/project-agent-work/rag-terminal-live-check-20261021/independent/final-runtime-review.md)에서도 기동·소스 동일성·DB 보존을 대조했다. 작업 시작 시 변경·미추적 파일 25개 중 이번에 갱신한 WORKBOARD를 제외한 24개는 SHA-256이 같다. 최근 완료 목록은 5개를 유지하고 문서의 로컬 링크 대상과 `git diff --check`를 확인했다.

[문제 이력 규칙](../issues/README.md)에 따라 이번 기존 취소 미종료 관측은 정상 로그인 관리 UI로 기존 [ISSUE-00018](http://127.0.0.1:5173/admin/system/issues?issue=1f096dc4-c484-466c-93e3-150b7424a9ce)에 진행 이력을 추가했다. 상태는 ‘구현됨·검증 남음’으로 유지하며 과거 사건·관련 문서를 보존했다. 정확한 등록 문서와 연결 버전은 [이번 문서 등록 영수증](../../.local-data/project-agent-work/rag-terminal-live-check-20261021/browser-check/issue-record.json)에서 확인한다. 과거 모든 미등록 작업의 DB 반영을 완료했다는 의미는 아니다. 관리 이력의 정상 쓰기와 RAG 업무 상태의 보존을 구분하며 임의 문제 번호나 대체 JSON을 만들지 않았다. 추가 생성·임베딩 0, 도메인 활성화 0, 커밋·푸시 0이다. 기존 미커밋 자료는 보존했다.
