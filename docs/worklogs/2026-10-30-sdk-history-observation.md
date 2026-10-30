# SDK 고정 평가의 이전 대화 단계 관측 보완

## 범위와 원인

사용자는 기존 SDK 관측 누락 보완을 먼저 마감하도록 요청했다. 다음 실모델 비교의 OpenAI 대상은 Terra라고 확인했으며, 코드 테스트 담당 모델을 뜻하지 않는다.

고정 입력 생성 평가는 일반 대화의 서버 이력 수집을 수행하지 않는다. 기존 흐름에서는 `complete_attempt`가 평가 결과를 저장하면서 DB trigger가 실행을 종료한 뒤, `ExecutionObserver.finish`가 미실행 `history` 단계를 뒤늦게 기록하려 했다. 종료된 실행의 늦은 쓰기 방어에 의해 기록이 남지 않았다. 실행 화면의 ‘이전 대화 준비: 미기록’은 이 관측 순서 문제이며, 입력 문맥이 소실됐다는 증거가 아니다.

`generative_workflow.py`의 기존 조기 보완은 observer 시작과 request 시작 직후, adapter 준비 및 모델 호출 전에 `history=skipped`, `reason=not_executed`를 기록한다. 실제 수행하지 않은 단계의 시작 시각·소요 시간·이력 선택 정보는 만들지 않는다. snapshot에 포함된 history와 후속 문맥화는 기존 파이프라인을 그대로 사용한다. 일반 대화의 실제 history 수집·권한 검사도 바꾸지 않는다. 과거 기록은 소급해 채우지 않는다.

## 책임과 검증 기준

중간 위험의 Python 관측 보완으로 분류했다. 메인은 백엔드 통합·본래 환경 확인·기록, 별도 담당은 DB 테스트 설계, 독립 담당은 코드 검토·회귀·정적 검사를 수행한다. 공개 계약·스키마·UI·검색·모델 입력 변경은 제외한다. 기존 dirty checkout의 미완료 보완을 이어서 검증하며 관련 없는 변경은 보존한다.

- 성공·실패 모두 종료 전에 history 생략 기록이 남고, 실제 recorder/read 경로로 확인한다.
- 늦은 기록은 계속 거절되어 과거 누락을 완료로 위장하지 않는다.
- 관측 저장 실패·취소·provider 종료 미확인의 기존 동작과 입력을 보존한다.
- 본래 DB의 합성 테스트 쓰기는 외부 transaction과 SAVEPOINT 안에 제한하고 전부 rollback한다. 기존 계정·자료·설정·기록의 해시를 비교한다.
- 새 모델 호출 없이 관측 수정 검증을 수행한다. 자동 검사 통과를 실모델 품질 향상으로 보고하지 않는다.

## 진행과 증거

코드와 본래 DB 검증을 완료했다. 원본 DB의 124개 표·162,053행을 시험 전·첫 시험 뒤·최종 시험 뒤 비교해 전부 동일했고, `.env`·migration revision·승격 gate도 보존됐다. pending/running 평가·대화·실행은 없다. API는 본래 Conda/루트/18000으로 실행 중이다. 수정 파일의 마지막 기록은 10월 27일, 현재 API 시작은 10월 29일로 기존 보드의 ‘API 반영 전’ 메모는 이후 재기동 사실을 반영하지 못했다. API/launcher 정체성과 `/api/v1/health`, `/api/v1/ready`의 HTTP200을 확인했으며 이번 불필요한 추가 재기동은 하지 않았다.

| 검증 | 실제 결과 |
| --- | --- |
| 독립 단위 회귀 | 6개 파일 51개 통과, 11.78초. history 유무·준비/인용 실패·취소·종료 미확인·관측 쓰기 실패·입력 보존 포함 |
| 범위 정적 검사 | `generative_workflow.py` Mypy와 제품/단위 테스트 Ruff 통과; 전체 저장소 타입 통과로 확대하지 않음 |
| 본래 DB | `test_history_observation_existing_db.py` 4개 통과, 22.67초. 실제 observer/recorder/complete_attempt/terminal trigger를 사용해 성공·실패 × 조기·종료 뒤 기록 비교 |
| DB 데이터 안전 | COMMIT 차단·SAVEPOINT·외부 transaction rollback·새 UUID 행0·기존 관련 지문 및 전체124표 동일 |
| 실제 기존 화면 | 실행 `8882dbc8-fac6-4275-b7f3-536b4b3f2f40`의 이전 대화 미기록·341.62초·답변/인용2/근거28·품질실패 보존 |
| 문제 이력 | 기존 계정 재로그인 후 ISSUE-00035에 2026-10-30 진행 이력 저장·새로고침 재조회 완료. 큰 이슈의 다른 잔여 검증 때문에 전체 상태는 승격하지 않음 |

첫 DB 검증은 2개 통과·2개 실패였다. 조기 기록과 `complete=True`는 이미 통과했지만 저장 serializer가 선택적 null 필드를 생략해 테스트의 `history['history_selection']`가 실패했다. 제품을 바꾸지 않고 `get`으로 기존 선택 필드 계약을 검사하도록 정정했고 최종4개가 통과했다. 최초 XML을 보존했다. 독립 단위 실행의 Windows sandbox self-pipe 정체·기존 공용 temp 권한 오류는 승인된 실행 및 새 작업 전용 temp로 해결했으며 관련 실패 출력도 보존한다.

실제 모델을 새로 호출하지 않았다. 따라서 새로운 생성 평가가 화면에서 ‘이전 대화 준비 생략’으로 표시되는 최종 실모델 수용은 다음 실행에서 확인한다. 이번 수정은 관측 정확성의 보완이며 속도·답변 품질 향상을 입증한 작업이 아니다.

상세 로컬 증거: `.local-data/project-agent-work/sdk-history-observation-20261030/`.

- `independent-review.md`, `independent-pytest.txt`, `independent-mypy.txt`, `independent-ruff.txt`
- `original-db.xml`(최초 실패), `original-db-final.xml`(최종4개 통과)
- `database-before.json`, `database-after-test.json`, `database-after-runtime.json`, `runtime-verification.json`
- `legacy-execution.png`, `issue-saved.png`

## 다음 비교의 구분

다음 OpenAI 후보는 공식 모델 ID `gpt-6.1-terra`로 준비한다. 기존 비교는 `gpt-6-luna`였으므로 Terra/Gemma 비교는 동일 모델 재현 실험과 구분해 기록해야 한다. 같은 공개 질문·28개 근거·동일 입력을 보존하고 첫 요청과 동일 입력 반복, 실제 답변·인용·일반 규칙/예외 rubric, usage/계산 비용/청구 미확인을 함께 기록한다. Gemma 반복의 입력 재사용을 새 질문 성능으로 일반화하지 않는다. 한 질문의 추가 반복은 재현성 확인이며 전체 질문 정확도나 추론 성능의 통계적 증명이 아니다.

Terra는 Responses API와 구조화 출력을 지원하며 reasoning effort는 명시해야 한다. [공식 모델 문서](https://developers.openai.com/api/docs/models/gpt-6.1-terra), [공식 사용 안내](https://developers.openai.com/api/docs/guides/latest-model#gpt-6-astra-gpt-61-terra)를 확인했다. 이 작업에서는 아직 실모델 비교를 실행하지 않았으며 기존 모델·프로파일·기본값·API 키 파일은 수정하지 않는다.
