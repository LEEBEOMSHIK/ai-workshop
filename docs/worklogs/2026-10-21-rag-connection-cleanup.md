# RAG 연결 후보 정리와 저장 구성 모델 표시 수정

2026-10-21. 사용자의 연결 상태 정리·후속 진행 요청에 따라 본래 로그인 환경을 확인했다. **Gemma 비활성 후보 연결 3과 비추론 연결 확인을 완료하고, 저장 구성의 모델 표시 결함을 수정했다. 일반 대화 연결 전환·답변 품질 통과·실모델 종료 수용은 미완료다.**

## 원인과 정상 연결 경로

기존 자산운용 도메인의 활성 포인터는 연결 2 → RAG-TEST 구성 v4 → 지원 종료된 Codex CLI 배포였다. 로컬 Gemma로 평가했던 구성과 일반 대화의 활성 연결은 서로 달랐다. 서버 장애나 브라우저 미연결로 판단하지 않는다.

본래 API health/ready가 정상이고 Ollama 0.40.3의 모델 목록에 기존 E2B가 있음을 비추론 GET으로 확인했다. 적재 모델은 0이었다. 등록된 Gemma 구성들은 모두 pending·비기본이며, 최신 저장 후보는 `Gemma E2B 범용 v5 비교 2026-10-19`의 구성 v1이다. E 입력 배치 실험을 운영 serializer로 반영한 구성이라는 뜻은 아니다.

도메인 비활성화는 데이터 삭제는 아니지만 현재 `resolve_library` 계약상 도메인 파일함을 404로 만든다. 파일함 접근 경로를 보존하기 위해 기존 활성 포인터를 유지하고, 동일 지식 공간의 비활성 후보만 정상 관리자 UI로 추가했다. 기존 Codex 실행을 복구하거나 다시 허용하지 않았다. [독립 계약 검토](../../.local-data/project-agent-work/rag-connection-cleanup-20261021/independent/connection-contract-review.md).

| 항목 | 확인·변경 결과 |
|---|---|
| 기존 활성 연결 | 연결 2 `baa19d13-09e2-466b-a410-8a844d0a65a3`, 변경 없음 |
| 새 비활성 후보 | 연결 3 `f8ae65ec-f52e-4100-a5fd-de5b7ab3a6cf`, 14:58:23 KST 생성 |
| 후보 구성 버전 | `4d603cb6-cd3f-40a5-8e91-974b5cf1f8fb`, pending·비기본 유지 |
| 생성 프로파일 | `10bb5ed9-dc04-4b1b-bc29-4358c859c425`, 기존 v5 입력 비교 |
| 배포 버전 | `97327b16-30e3-41b4-88a3-9f64a55056db`, 로컬 Ollama E2B·360초·재시도 0 |
| 자료 범위 | 기존 RAG 합성 참조 자료 1개, 범위 변경 없음 |
| 정식 상태 확인 | 해당 배포만 1회, 14:59:28 KST 정상·72ms |

정식 health-check는 어댑터의 `GET /v1/models`로 정확한 모델 ID 존재를 확인하고 health 이력 1건을 저장한다. 72ms는 이 조회의 시간이며 질문 응답 지연·품질 지표가 아니다. 새 연결 생성과 상태 확인은 생성·임베딩·일반 큐·재색인을 실행하지 않는다. 연결 생성은 중복 제거가 없으므로 1회 저장 후 UI와 DB에서 후보가 정확히 1개 늘었는지 대조했다.

## 발견한 표시 결함과 수정

Gemma 구성의 검색·답변 준비가 완료되어 있어도 LLM이 ‘연결된 모델 정보 없음’으로 표시됐다. 저장 구성 화면이 예전 `profile.bindings`의 직접 LLM 연결만 읽고, 배포에 연결된 최신 프로파일의 서버 `generation_execution_preview`를 사용하지 않았기 때문이다.

[SavedConfigurationList](../../frontend/src/features/rag/configurations/SavedConfigurationList.tsx)는 생성형 구성에서 서버 preview의 등록 모델명·버전을 우선 표시한다. 요청 모델 ID가 있으면 ‘요청 모델’이라고 구분하며 실제 실행 모델을 추정하지 않는다. preview가 없으면 기존 직접 연결을 사용하고, 생성 프로파일 메타데이터가 누락돼도 추출식으로 표시하지 않는다. 추출식 표시와 실행·평가·기본값·활성화 규칙은 유지했다. 특정 업체나 모델명 분기는 없다.

본래 Chrome 화면은 첫 확인에서 이전 표시가 남아 있었고 명시적인 페이지 새로고침 뒤 최신 표시를 확인했다. 실제 Gemma v5 카드에 `Gemma 4 E2B Ollama v1`과 ‘평가 대기’가 함께 표시된다. 이 HTTP preview에는 요청 모델 ID가 없으므로 실제 화면에서 ID까지 표시됐다고 주장하지 않는다. ‘서비스 사용 가능’은 실행 준비 상태이고 품질 통과나 도메인 활성화가 아니다.

[실제 로그인 화면](../../.local-data/project-agent-work/rag-connection-cleanup-20261021/configuration-model-verified.jpg)을 보존했다. 캡처 도구의 clip 좌표로 만든 초기 PNG들은 다른 위치를 담아 검증 증거에서 제외하고, 현재 뷰포트를 직접 캡처한 위 JPG만 사용한다. 합성 화면이나 생성 이미지가 아니다.

## 검증과 보존

- 신규 회귀 3개가 수정 전 실제로 실패했다: 배포 모델 표시 2개와 누락된 생성 메타데이터의 추출식 오표시 1개.
- 수정 후 관련 4파일 38개 통과: 구성 스튜디오, 패키지 요약, 도메인 관리, 배포 목록.
- `pnpm --dir frontend exec tsc --noEmit --pretty false --incremental false`와 변경 2파일 ESLint 통과.
- [독립 표시 검토](../../.local-data/project-agent-work/rag-connection-cleanup-20261021/independent/model-display-review.md): 신규 3개 독립 통과, 실제 JPG·코드·사후 DB 결과 대조. 실행/품질 gate 변경 없음.

수정 책임은 메인이 맡고 독립 통합·보안 검증 역할을 분리했다. 초기 RAG·AI·백엔드·DB 역할에서 표시 결함이 드러난 뒤 프론트엔드·테스트 설계 역할을 추가했다. 새 의존성·환경·계정·모델은 만들지 않았다. 기존 작업 공간의 사용자 변경을 보존하며 관련 파일만 수정했다.

[읽기 전용 이전](../../.local-data/project-agent-work/rag-connection-cleanup-20261021/database-before.json)·[이후](../../.local-data/project-agent-work/rag-connection-cleanup-20261021/database-after.json)와 [변경 대조](../../.local-data/project-agent-work/rag-connection-cleanup-20261021/operation-check.json)에서 RAG 8개 테이블의 행 수·집계 지문, 대화 revision·상태, 구성·기존 연결 2개·활성 포인터가 같다. 새 후보 연결과 health 기록은 승인된 관리 변경으로 구분한다. 전체 DB 불변이나 암호학적 무결성 증명으로 확대하지 않는다. 기본 RAG 상태와 추가 연결 조회는 별도 읽기 전용 트랜잭션 관측이다.

기존 취소·종료 미확인 1건과 queued job 1건은 그대로다. 추가 생성·임베딩 0, 활성화·강제 READY·평가 기준 완화 0, DB 직접 변경 0, 서비스 재기동·설치·모델 다운로드·커밋·푸시 0이다.

## 문제 이력과 남은 경계

- [ISSUE-00006](http://127.0.0.1:5173/admin/system/issues?issue=cd247e57-2c12-542f-bbbb-ea138771ddb2): 기존 Codex 지원 종료로 일반 대화 준비가 막힌 현재 상태를 진행 중으로 갱신하고, 과거 검증·커밋·문서와 사건을 보존한 채 이번 진행 이력·남은 작업을 추가했다.
- [ISSUE-00031](http://127.0.0.1:5173/admin/system/issues?issue=cf2ad1e6-4eb0-4e83-ae14-be904fffad9f): 다른 원인인 저장 구성 모델 표시 결함을 별도로 등록했다. 해당 표시 수정·본래 화면 확인 범위만 검증 완료다.
- 문서의 정확한 등록 버전과 연결 결과는 [관리 UI 영수증](../../.local-data/project-agent-work/rag-connection-cleanup-20261021/issue-record.json)에 둔다. 이전 등록 문서를 덮어쓰지 않는다.

일반 대화는 아직 사용할 수 없다. 최신 실제 E2B 품질 결과의 정상 0/2·적절한 거절 2/2와 지연 미통과를 유지한다. 기존 실험 호출 예산이 소진돼 이번에 같은 조건의 생성을 반복하지 않았다. 품질 기준을 충족한 구성의 정상 전환 전에 대화 종료·다음 질문의 실모델 수용 완료를 주장할 수 없다. 12B/GPU 성능 개선 보류, 기존 종료 증거의 정식 복구와 별칭·첨부 복구 순서는 유지한다. [현재 작업 순서](../../WORKBOARD.md#다음-작업-순서).
