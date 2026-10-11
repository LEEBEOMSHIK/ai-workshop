# RAG 예산 한 변수 비교의 설계 준비와 독립 검토

- 기준일: 2026-10-07
- 관련 문제: ISSUE-00005
- 상태: 원인·본래 설정 조사, 개선 대안 비교와 작성된 설계 준비 완료. 사용자 설계 검토 전이며 구현 계획·후보 생성·실모델 평가·활성 연결 변경은 미착수다.
- 산출물: [구체적인 비교 설계](../superpowers/specs/2026-10-07-rag-context-budget-isolation-design.md)
- 설계 본문의 검토 시점 SHA-256: `a6c49654d87fc3b3a3090d44e4c8f094c7ba74917b1b9141210140157d6911f4`

## 확인한 원인과 최소 개선 범위

본래 화면에서 확인한33/32·36/32는 작은 PDF font span이 각각 원문 단위로 생성되는 계약과 전체 청크 수용/제외의 결과다. 현재 PDF는 표의 row/column·조건·예외 관계가 미기록이므로 앞32개만 남기거나 bbox로 행을 추정하면 원문 의미를 잃을 수 있다. 다른 질문의 의미 관련성 미달과 생성 실패를 이 예산 원인으로 통합하지 않는다.

검토한 대안은32단위 내 일부 선택, 새 구조 파서와 불변 projection/index, 원문 전체를 보존하는 예산 한 변수 실험이다. 이번 권고는 마지막 대안이다. 현재 selector가 이미 명시적인128후보를 처리하므로 새로운 선택 함수·packet/provider wire·기본값 변경은 필요하지 않다. 이후 구조 선택은 표·조건·예외의 검증된 관계를 필요로 하며 별도 설계·새 색인과 frozen alias의 종료 조건을 갖는다.

## 본래 설정의 독립 READ ONLY 확인

구현 담당과 분리한 검증 담당이2026-10-07 05:55~05:56 UTC에 본래 DB를 READ ONLY/rollback으로 확인했다. 파일 변경·DB/API 쓰기·모델 호출은0이며 원시 config·질문·원문·계정·비밀을 출력하지 않았다.

- 활성 구성은v4/schema2, 예산version1의8그룹·32원문 단위·12000자다.
- 기존pure-v4/128 generation profile은 활성v4와 전체 업무 설정 중 `context_evidence.max_units`만 다르다. 같은 model/deployment binding이다.
- 처리/색인/검색 profile과 업무 설정, 구독 공간은 같지만 **기존128 configuration은 answer policy의 `min_semantic_score`도 다르다.** 해당 configuration을 그대로 비교하면 한 변수 실험이 아니다.
- 따라서 불필요한 generation profile을 복제하지 않고 기존 불변128 profile을 참조하며, 실제 로컬 입력 비교가 통과한 경우에만 활성 answer policy를 고정한 새 pending configuration을 정상 승인·관리 API로 준비하도록 설계했다.
- 기존pure-v4/128의 수동5판정 중1실패, v5의재시도 포함68완료/14실패·수동68판정, v6의64완료/11실패·수동63통과/1실패를 구분했다. 이전 결과·승인·pending/defaultfalse를 수정하지 않는다. run completed가 후보 승격 자격이나 현재 품질의 증거는 아니다.

첫 메타데이터 조회는 deployment binding을 profile 컬럼으로 가정해 실패했고 rollback했다. 실제 binding 테이블 JOIN으로 교정한 읽기 조회가 성공했다. 원시 예외나 SQL parameters는 출력하지 않았다. 실패 조회를 성공 확인으로 포함하지 않는다.

## 독립 설계 검토와 반영

독립 담당은 원문 ID/text/location 보존, 표·예외·충돌, raw-unit 의미, 인용/숫자 검증의 의미 한계와 외부 전송 경계를 검토했다. 수정 후 원문·인용·프라이버시 관점의 설계 차단 의견은0이며, 실행 계획에 필요한 다음 조건을 설계 본문에 반영했다.

1. 기존generation profile 재사용과 활성answer policy 고정 새configuration을 분리한다. 기존configuration·승인·판정을 복사하지 않는다.
2. `select_context`의 두 호출이 각각 embedding/자격을 계산하므로 같은 요청의 `RequestScopedEmbedding`을 재사용하고 두 번째 delegate 호출0·source/모델/추출결과·자격/점수/순서 동일을 확인한다. cache miss/차이가 있으면 중단한다. 반사실 비교와 정상 서비스 E2E를 구별한다.
3. 외부 deployment의configuration 생성 시 필요한 owner 전송 승인과 실생성 연결 검사·매 질문 동의를 분리한다. 새 후보ID에 옛 승인 레코드를 복사하지 않는다.
4. 캐시 재사용의 시간 차이를 전체 지연 개선으로 해석하지 않는다. 실모델 호출 상한에는 readiness/contextualization의 추가 호출도 포함한다.

이는 설계 검토 결과다. 실제 비교 helper·새후보·모델답변·정확성·승격 또는 본래 멀티턴 검증 통과로 보고하지 않는다.

## 실제 실행한 검증과 보존 범위

메인이 본래 backend 가상환경에서 기존 문맥/PDF 회귀를 실행했다.

```powershell
# C:\projects\ai-workshop\backend
.\.venv\Scripts\python.exe -m pytest tests/unit/labs/rag/highlighting/test_context.py tests/unit/labs/rag/highlighting/test_pdf_context_budget.py -q -p no:cacheprovider
```

결과는18통과(exit0)다. 기존32제외/128전체원문 보존, 누적 예산·충돌·미달·출처 무결성·진단 on/off 계약의 회귀이며 새 실모델 품질을 증명하지 않는다. 이번에는 제품 코드·UI·공개 API·DB 스키마를 수정하지 않아 전체 타입/린트·프론트 테스트를 반복하지 않았다. 범위 문서의 로컬 링크·불완전 표기·최근 완료 최대5개와 scoped diff 검사는 마감 시 확인한다.

기존 환경·서버·Docker·원본·별칭 gate·활성 연결을 바꾸는 작업은 하지 않았다. 새 환경/DB/계정/worktree·후보/연결/평가·생성 호출·서버 재시작·commit/push·삭제는0이다. 기존8개 동결 보고서는 수정하지 않았다. 문제 이력 등록은 정상 owner API로 이 보고서 exact 버전과 새 진행 사건만 추가하며 ISSUE-00005의open 및 기존 필드·사건·문서 연결을 보존한다. 그 등록·독립 읽기 증거는 task-local receipt에 별도로 남긴다.

## 다음 인계와 사용자 검토 경계

작성된 설계를 검토한 뒤 구현 계획에서 exact 사례·모델 호출 상한·현재 승인·DB 보존 기준선과 책임을 정한다. active32는 유지하며, 먼저 로컬 입력 포함 비교를 수행하고 통과한 경우에만 새 pending configuration/제한된 생성으로 이어간다. 기존 평가를 새 후보 통과 근거로 복사하거나 미승격128을 기본값으로 바꾸지 않는다.

이번 산출물은 후속 설계 준비다. 근거 부족 수정이나 본래 새답변·성공한 멀티턴·RAG 기능 마감이 완료된 상태가 아니다. 기존 별칭 종료 증거·DLL 재발 방지·권한 철회·첨부/모바일·실모델 실패/timeout·Git 인계도 남아 있으며 SDK·저장소·학습은 기존 RAG 마감 뒤 순서를 유지한다.
