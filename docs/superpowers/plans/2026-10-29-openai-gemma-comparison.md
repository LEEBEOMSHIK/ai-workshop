# OpenAI API와 Gemma 비교 및 비용 관측 계획

**목표:** 사용자가 요청한 동일 공개 합성 질문·28근거의 답변/인용 품질·요청 소요 시간과 OpenAI 사용량/비용을 비교한다. 기존 Gemma 기본값·서비스·DB 정책·연결은 유지한다.

**구조:** 제품 기본 연결과 별개인 `.local-data/project-agent-work/openai-gemma-comparison-20261029/` 진단을 사용한다. 원래 계정의 현재 ACL로 기존 고정 실행을 읽고 공개 fixture와 일치하는 본문만 허용한다. 외부 전송은 이번 사용자 지시와 정확한 공개 합성 자료 범위이며 기존 local-only 배포를 외부 배포로 둔갑시키지 않는다. 비용 계측은 독립 ledger와 `monitor.json`/결과 보고서로 제공한다.

**설정:** 비교 전용 Git 제외 파일 `.local-data/openai-comparison.env`에서 키를 읽는다. 기존 `.env`는 변경하지 않는다. OpenAI 후보는 공식 문서의 `gpt-6-luna`, standard tier, reasoning none, temperature0/top_p1, 출력512토큰이다. 모델/가격/한도는 실험 설정 파일에 둔다. 이전 종료 예산과 별개인 이번 사용자 비교 지시 범위에서 OpenAI2회·기존 Ollama Gemma2회, 자동 재시도0·단일 동시 실행·OpenAI 예상 총액 상한$0.05를 사용한다. API 인증·입력/가격 검증이 준비되기 전 실제 모델을 호출하지 않는다.

## 계약과 수용 기준

- 과거 payload SHA·질문·empty history·위임 task·system prompt·근거28개·출처 숫자 메타데이터를 검증한다. body를 로그/Git에 쓰지 않고 기존 입력 문자열을 그대로 OpenAI Responses input으로 전달한다.
- Gemma는 기존 frozen 요청을 그대로 보낸다. OpenAI의 root anyOf 미지원 때문에 출력 shape는 schema2 그대로 두고 객체 스키마로 표현한다. status/claims 조건과 인용은 기존 제품 파서/검증기로 강제하며 표현 차이를 기록한다.
- 답변/인용의 기준선 완전일치와 품질을 구분한다. 공개 지급 규칙 rubric의 일반 T+4 영업일·마감 후 다음 영업일 접수·예시/달력 정보의 한계를 별도로 판정한다. 다른 더 나은 답변을 문자열 불일치만으로 실패시키지 않는다.
- 속도는 동일 non-streaming 완료 요청 시간으로 비교한다. 첫 토큰 시간은 측정하지 않았다고 표시한다. 성공2회만으로 P95나 일반적 우열을 주장하지 않는다. 실패·잘린 출력·거절도 결과로 남기고 자동 재시도하지 않는다.
- 전송 전에 호출 수와 보수적 금액을 예약하고 파일을 flush/fsync한다. 실패/timeout/usage누락은 비용0으로 바꾸지 않고 미확인 예약을 유지한다. 실제 token usage는 품질 판정보다 먼저 기록한다.
- OpenAI 입력·cached input·cache write·출력/추론 토큰을 공식 계약에 맞게 확인한다. 최초 비교는 explicit cache mode와 breakpoints 없음으로 cache 읽기/쓰기를 끈다. 가격 출처/확인 시각·USD 예상 비용·누적액·남은 한도·청구 확인 상태를 기록한다.
- Admin key와 project ID가 있으면 공식 조직 Usage/Costs를 비교 전후 읽어 집계액을 대조한다. 프로젝트의 다른 활동·집계 지연 때문에 계정 차액을 개별 호출 확정 비용으로 표시하지 않는다. 키가 없으면 응답 기반 계산 비용만 제공하고 청구 확인은 미완료로 남긴다. 자동충전·예산·계정 결제 설정은 변경하지 않는다.
- 답변 원문은 승인된 공개 합성 비교 결과만 별도 로컬 보고서에 보존하며 내부 추론·인증키·원시 오류·HTTP 헤더는 저장하지 않는다. 실패 시 고정 오류 분류만 기록한다.

## 담당과 순서

1. AI 담당: 공식 모델/가격/응답 계약 확인, 순수 요청 변환·정규화·품질 비교와 합성 회귀.
2. 비용 담당: Decimal 가격/usage 계산·예약/정산·관측 상태와 합성 회귀. 네트워크·DB·키 접근 없음.
3. root: 현재 공개 자료/권한 읽기, 안전한 secret 로딩, bounded HTTP와 단일 실행 ledger·monitor/report, 비용 집계 조회 연결.
4. 독립 담당: 공개 데이터 경계·비밀 비보존·한도/usage 누락·기존 설정 보존·품질 판정과 실제 결과를 독립 검토.
5. 승인 Conda에서 관련 단위/통합 mock·Ruff·strict mypy와 본래 read-only 준비 후 실제 비교. 최종 WORKBOARD/worklog에 실제 결과·비용·미확인을 구분한다. UI·제품 DB schema·운영 기본값 변경은 제외한다.
