# 일반 규칙 누락 후속: 원문을 함께 표시하는 E 입력 후보

- 날짜: 2026-10-20
- 관련 문제: ISSUE-00005. 운영 DB 이력 반영은 기존 인증 실패 이후 미완료이며 이번 작업에서 DB를 직접 수정하지 않았다.
- 시작점: `c707178` 인계 이후 사용자의 “다음 보강작업이지? 진행해” 요청.
- 범위: 저장된 공개 합성 입력의 오프라인 후보 구현·검증. 새 생성·임베딩·검색 호출은 0이다.
- 후속 실제 검증: 아래 별도 승인 평가에서 E 생성4회를 완료했다. 정상 품질0/2·적절한 거절2/2로 개선 미확인, 생성 P95는163.022초다. 위 호출0은 최초 준비 작업의 기록이다.

## 관측과 가설

[실제 A/D 비교](2026-10-19-rag-relation-improvement.md#2026-10-20-실제-ad-비교-검증)에서 정상 답변은 A·D 각각 0/2, 적절한 거절은 각각 2/2였다. D는 예시 휴일 조건과 관련 인용을 보존했지만 일반 지급 규칙을 두 번 모두 누락했다. 기존 v5 지침은 이미 일반 규칙을 먼저 답하도록 요구하며 정상 입력 28조각에는 일반 규칙·T 정의·마감 이후 조건이 들어 있다. 검색 결과에 규칙이 전혀 없었던 실패로 해석하지 않는다.

D의 `layout_hints.grids[*].rows`는 인용 UUID만 담는다. 사람이 보는 보고서에는 같은 셀의 원문이 표시되지만 모델 입력에서는 원문 조각 목록과 ID 배열을 대조해야 한다. 이 표현이 관계 활용에 부담을 줄 가능성을 검토했다. **확인된 실패는 일반 규칙 누락이며, 모델 내부의 원인은 미확인이다.** 이미 실패한 단순 지침 강조를 반복하거나 특정 질문의 정답을 삽입하지 않는다.

메인이 요구·RAG·AI·테스트 설계·문서를 맡고 별도 검토자가 원인 검토와 독립 검증을 맡는다. 범위가 제한된 중간 위험 작업이다. UI·DB·배포 변경 역할은 포함하지 않는다.

## 구현 경계

새 `offline_readable_layout.py`는 검증된 원본 Capture에서 기존 D를 계산하고 각 격자에 다음 필드만 추가한다.

```text
readable_rows = [[{evidence_id: 기존 인용 ID, text: 해당 조각의 원문 그대로}, …], …]
```

질문·업체·원문 표현으로 셀을 고르지 않는다. D가 관측한 모든 행·열의 텍스트를 ID로 찾아 그대로 반복하며 원래 행렬과 안내문을 유지한다. 첫 행을 헤더로 정하거나 일반 규칙·예외 등의 의미 역할을 추론하지 않는다. 근거 블록·출처·순서·좌표·system·옵션은 그대로다. D가 모호한 좌표/출처 때문에 격자를 보류하면 E도 보류하고 원본 바이트를 유지한다.

검증 함수는 원본에서 D와 E를 다시 계산하여 후보 전체를 대조한다. 본문을 변조하고 해시를 다시 만든 경우도 거절한다. 보고서와 CLI에 선택형 `--readable`만 추가했으며 기본 D 경로와 운영 serializer·프로파일은 바꾸지 않았다. 실제 생성 코드나 자동 실행 경로도 추가하지 않았다.

원문 중복·입력 길이·강조가 함께 바뀐다. 향후 E가 나아져도 ID 대조 부담이 단독 원인이었다고 결론 내리지 않는다. 원문 내 지시문도 그대로인 비신뢰 근거 텍스트이며 새 지침으로 승격하지 않는다.

## 실제 저장 입력에 적용한 준비 결과

| 저장 사례 | A 원본 | D | E | E가 반복한 텍스트 |
| --- | ---: | ---: | ---: | --- |
| 정상 2건, 건당 | 11,318bytes | 12,346bytes | 13,280bytes | 5행×2열, 10조각·174 UTF-8 bytes |
| 근거 부족 2건, 건당 | 11,587bytes | 11,587bytes | 11,587bytes | 0, 원본 바이트 동일 |

정상 입력의 D→E 증가량은 934bytes다. 원문 텍스트 외에 인용 ID·JSON 구조도 반복되므로 텍스트 174bytes보다 크다. 실제 토큰 수·지연·답변 품질은 아직 측정하지 않았다. E 후보 4건은 모두 `not_run`이다.

- [E 원문 배열·보존 지침·D 대비 차이](../../.local-data/project-agent-work/rag-readable-layout-20261020/candidate-e/index.html)
- [미실행 후보 JSON](../../.local-data/project-agent-work/rag-readable-layout-20261020/candidate-e/candidates.json)
- [준비 검사와 보존 해시](../../.local-data/project-agent-work/rag-readable-layout-20261020/preparation-check.json)

보고서는 생성 답변을 넣지 않으며, HTML escaping과 CSP를 유지한다. 실제 브라우저 배치 확인은 이번 범위에 포함하지 않았다. 현재 원문 접근 권한을 재조회한 결과도 아니다. 기존 v5 입력/결과·D 후보·A/D 실행 증거·사용자 이미지 등 44개 파일의 SHA와 크기가 작업 전과 같다.

최초 후보 준비 명령에서 `--readable`을 누락하여 D가 생성됐으며 버전·condition·통계 검사에서 발견했다. 이번 작업의 잘못 생성한 두 파일만 제거하고 옵션을 명시해 E를 재생성했다. 실제 모델 호출은 없었으며 D/E를 구분하는 최종 산출물 검사를 다시 수행했다.

## 검증

- 테스트 우선: 핵심 미구현 23실패 → 구현 후 23통과. 보고서 기능 추가 전 1실패/24통과 → 구현 후 신규 25개 통과.
- 관련 입력 진단·산출물·D·rubric 회귀를 포함해 116개 통과.
- 변경 Python 4파일 Ruff·strict Mypy 통과. Mypy의 첫 실행은 테스트 helper 검색 경로가 없어 실패했고 `MYPYPATH=backend;backend/src`로 실제 경로를 지정해 통과했다. 타입 검사를 완화하지 않았다.
- 기본 D의 HTML/JSON 두 파일은 수정 전후 바이트 동일하다.
- 다른 업체·수치·명령형 원문·반복 문구, 복수 제품/3열/출처별 예외, 부분 표, 누락/겹침/역순 좌표, 출처 재등장, 원문·ID·옵션 변조를 검사했다. 텍스트 중복만으로 다른 셀이나 출처를 합치지 않는다.

별도 검토자가 네트워크 연결을 차단한 관련 116개 테스트를 모두 통과했다. 실제 CLI의 기본 D와 `--readable` E 재생성, 원본 44개 SHA, 최종 HTML의 원문/지침/차이 16개 표시 블록과 후보 불변조건 등 100개 검사도 통과했다. 차단 결함은 발견하지 않았다. 전체 backend/UI 회귀나 실제 RAG 수용 통과로 확대하지 않는다.

[독립 리뷰](../../.local-data/project-agent-work/rag-readable-layout-20261020/independent/review.md), [독립 산출물 검사](../../.local-data/project-agent-work/rag-readable-layout-20261020/independent/artifact-review.json), [독립 테스트](../../.local-data/project-agent-work/rag-readable-layout-20261020/independent/unit.xml)를 보존했다.

최종 문서 3개의 로컬 파일 링크 129개·코드 블록 경계·최근 완료 5개 제한과 `git diff --check`를 확인했다. 독립 검토한 코드 4파일과 기존 보존 44파일의 해시도 다시 일치했다. 문서 검사 첫 실행은 PowerShell 표준입력의 한글 리터럴 인코딩으로 보드 제목을 찾지 못했고, 검사 코드의 제목을 Unicode escape로 전달해 통과했다. 문서 본문과 제품 코드는 바꾸어 우회하지 않았다.

## 재현과 다음 경계

기존 Conda 환경과 `PYTHONPATH=backend/src`를 준비한 저장소 루트에서 실행한다. 출력 경로가 이미 있으면 덮어쓰지 않고 거절한다.

```powershell
& $workshopPython -X utf8 -B scripts/prepare_rag_layout_candidate.py --captures .local-data/project-agent-work/rag-v5-evaluation-20261019/actual-v5-inputs.json --results .local-data/project-agent-work/rag-v5-evaluation-20261019/evaluation-results.json --classification public_synthetic --readable --output .local-data/project-agent-work/rag-readable-layout-20261020/candidate-e
& $workshopPython -X utf8 -B -m pytest -c backend/pyproject.toml backend/tests/unit/labs/rag/evaluation/test_offline_readable_layout.py backend/tests/unit/labs/rag/evaluation/test_offline_layout_candidate.py backend/tests/unit/labs/rag/evaluation/test_offline_input_diagnosis.py backend/tests/unit/labs/rag/evaluation/test_offline_input_artifacts.py backend/tests/unit/labs/rag/evaluation/test_offline_rubric.py -q
```

이전 A/B/C 12회와 A/D 8회 예산은 소진 상태다. 다음 제안은 원래 두 사례의 E 입력을 각각 2회, 총 최대 4회 로컬 생성으로 확인하는 것이다. 실패·timeout도 횟수에 포함하고 재시도·새 검색·임베딩·예열·일반 큐 실행은 포함하지 않는다. 이 4회는 기존 D 결과와의 후속 비교이며 같은 시간에 D를 재실행하는 대조 실험은 아니다. 실행 허용과 현재 모델/프로필·권한·상태를 확인한 뒤 새 예산 기록으로 진행해야 한다. 실행 가드는 폴더명 대신 후보 version·condition E·readable_rows와 해시/원본 재계산을 검증하여 CLI 옵션 누락이 실제 전송으로 이어지지 않도록 해야 한다.

기존 correctness/context coverage/refusal accuracy 각 1, 인용 유효성, ACL 누출 0, 전체 RAG P95≤120초 기준은 유지한다. E의 실제 품질, 운영 반영, 전체 RAG 수용, 도메인 활성화 및 최종 확인용 추가 1회는 미완료다. 이번 변경은 커밋·푸시하지 않았다.

## 승인된 E 실제 평가

사용자가 위 최대4회 제안에 “진행해”로 동의했다. 정상E1→거절E1→거절E2→정상E2 순서로 각 사례 2회만 실행한다. 이전 12회/8회 예산은 재사용하지 않으며 실패·timeout도 소진하고 보충 호출하지 않는다. 실행 전후와 각 전송 전에 기존 정상 입장·모델/프로필·현재 원문 접근을 검사한다. 이번은 저장 근거의 생성 단계 확인이며 새 검색·임베딩·예열·일반 큐·운영 승격을 포함하지 않는다.

메인이 AI/RAG 실행·분석을 맡고 별도 검토자가 실행 경계와 결과를 독립 검증한다. 중간 위험의 제한된 실험이며 UI·DB 구조·배포 역할은 제외한다. 기존 입력 후보·미커밋 변경·과거 실행 증거는 보존하고 새 기록은 별도 작업 경로에 둔다.

### 실행 경계와 사전 확인

기존 A/D 실행 경로의 현재 권한·프로필·모델 확인, 전송 전 배타적 예약과 재실행 금지를 재사용한 E 전용 실행기를 준비했다. E artifact version·condition·원본 재계산을 확인하므로 폴더명만 보고 E라고 판단하지 않는다. 명세는4회·retry0·timeout360초이며 입력·관련 코드103파일을 고정했다.

실행기 미구현 상태의 수집 실패를 확인한 뒤 신규8개·재사용8개, 합계16개 경계 검사를 통과했다. 독립 사전 검토는149개 검사와 신규 가드8개를 통과했으며 모델·네트워크·DB 호출을 하지 않았다. [실행 전 독립 검토](../../.local-data/project-agent-work/rag-e-experiment-20261020/independent/pre-execution-review.md)를 보존했다.

읽기 전용 사전 확인에서 원본 v5 실행 `9f1df330-4d92-49bf-8186-eca8861b6160`, 현재 프로필/배포·원문 권한, pending/running 평가0과 기존6개 DB 테이블 해시를 확인했다. 기존 `gemma4:e2b-it-q4_K_M`와 모델 digest `b37049369adfe3d2b653af0ab301a062ca5cbe96ace6aa0d3f2559ee9b563fc2`가 일치했다. 실제 입력은 기존 HTTP 어댑터로 한 번만 전송하며 지침을 다시 붙이지 않는다.

### 실제 4회 결과

2026-10-20 16:12:52~16:18:44 KST에4개 생성을 마쳤고16:19:01에 최종 보존 확인을 완료했다. 실행 프로세스는 exit0이며4/4 완료·오류0·재시도0이다. 전송 예약4개와 응답4개를 확인했고 원래 E 입력 SHA와 실제 wire SHA를 각각 재계산했다.

| 확인 항목 | 과거 D | 이번 E |
| --- | ---: | ---: |
| 정상 답변 품질 통과 | 0/2 | 0/2 |
| 일반 지급 규칙 포함 | 0/2 | 0/2 |
| 예시 휴일 조건·앞뒤 원문 인용 보존 | 2/2 | 2/2 |
| 정상 인용 검사 통과 | 2/2 | 2/2 |
| 근거 부족 질문의 적절한 거절 | 2/2 | 2/2 |
| 정상 입력/출력 토큰 | 5,044 / 172 | 5,526 / 174 |
| 생성4회 평균 | 37.754초 | 73.146초 |
| 생성4회 P95 (nearest rank) | 98.990초 | 163.022초 |

D는 이전 실행 결과이며 이번과 같은 시간대의 대조군이 아니다. 원문 반복으로 정상 입력은482토큰 늘었다. 지연은 E 정상163.022/8.582초, 거절119.735/1.247초로 편차가 크며 로드·캐시 영향을 분리하지 못했다. 따라서 D 대비 지연 변화의 원인을 E 입력 증가 하나로 확정하지 않는다. 이번 생성 단계 P95부터120초 목표를 넘었고, 전체 검색을 포함한 RAG P95를 새로 측정한 것은 아니다.

정상 두 답변은 아래와 같이 동일했다.

> AM-SYN-101을 2026-09-07 월요일 15:10에 신청하면 09-08 화요일이 접수일이다. 예시 기간에 휴일이 없으며, 이 경우 기준가격 적용일은 09-10, 대금 지급일은 09-14이다.

원문에는 일반 지급 규칙 `접수일 T+4 영업일`과 T의 정의가 있지만 두 답변 모두 이를 설명하지 않았다. 같은 rubric의 실패 사유는 `required_rule_missing`이다. 문자열 점검뿐 아니라 원문과 질문을 대조해도 일반적인 지급 시점을 묻는 질문에 특정 날짜 예시만 제시하므로 품질 기준을 충족하지 못한다. 과거 D의 답변과 비교하면 “이 경우”만 추가됐고 핵심 누락은 그대로다.

거절 두 답변은 `{"schema_version":2,"status":"insufficient_evidence","claims":[]}`였고 제공 답변은 null이다. 선택 자료에는 다음 달 확정 수익률이 없으므로 이번 두 건의 거절은 적절하다. 모든 응답은 `finish_reason=stop`, 출력174/19토큰으로512한도 이하였다. 실행 중 GET으로 관측한 문맥 길이는16,384이며 출력 제한에 의한 절단은 관측되지 않았다. 내부 입력 처리나 주의 배분까지 확인한 것은 아니다.

### 실패 지점과 결론

1. **검색 근거:** 새 검색 없이 기존 근거를 재사용했다. 정상28조각에 필요한 일반 규칙·조건·정의가 존재하며 검색 전반의 품질을 새로 평가하지 않았다.
2. **LLM 전달 입력:** 원문과 지침을 보존했고, E에는 항목·값의 원문까지 추가로 함께 전달했다. 실제 wire 확인으로 전송 누락이나 준비 옵션 누락은 배제했다.
3. **생성 답변:** 일반 규칙을 쓰라는 지침과 원문이 있어도 두 번 모두 예시만 답했다. 이번 표본에서는 인용 ID 옆 원문 반복이 누락을 해결하지 못했다. 모델 내부에서 예시를 선택한 이유는 미확인이다.
4. **검증기:** 인용한 예시의 수치·출처 지원은2/2 통과했지만 질문을 충분히 충족하는지와는 별개다. 기존 rubric과 의미 검토에서는0/2를 유지한다.

E를 기본값으로 승격할 근거가 없고 도메인을 READY/활성으로 바꾸지 않는다. 이번4회 예산은 소진했으며 추가 생성·검색·임베딩·후속1회 호출은 수행하지 않았다. 제품 코드와 기존 미커밋 변경, 이전 실행/준비 산출물235개 및103개 고정 파일을 보존했다. 확인한 DB6개 테이블 해시는 전후 동일하다. 이는 선택 근거의 현재 권한과 인용 범위를 확인한 것이며 전역 ACL 누출0의 별도 공격/권한 회귀 시험을 대체하지 않는다.

### 설명 자료와 독립 확인

- [실제 질문 → 근거 → system/user → 생성 답변 전체](assets/rag-e-20261020/actual-comparison.html)
- [실제 결과 설명 이미지](assets/rag-e-20261020/actual-rag-flow.png)
- [자동 재계산](../../.local-data/project-agent-work/rag-e-experiment-20261020/analysis.json), [원문 대조 의미 검토](../../.local-data/project-agent-work/rag-e-experiment-20261020/semantic-review.json), [완료·DB 보존](../../.local-data/project-agent-work/rag-e-experiment-20261020/completion.json)

설명 자료는 실제 저장 입력·출력만 사용했다. 로컬 결과와 문서 자산의 SHA가 일치하며 PNG를 직접 열어 잘림·겹침과 표시 값을 확인했다. HTML의 실제 브라우저 배치는 미검증이며 제품 UI의 신규 평가 이력 등록이나 전체 업무 E2E를 수행한 결과가 아니다.

독립 실행 후 검토317개가 통과했다. 4예약/4응답, wire SHA·크기·순서, strict 응답 schema, 현재 인용 검사와 동일 rubric, 원문 대조 의미 판정, DB6해시, 과거235파일과 고정103파일을 재확인했다. 정상0/2·거절2/2와 P95 재계산이 일치한다. 추가 표현 검사24개에서도 HTML의 실제32개 표시 블록과 의미 검토·이미지가 원본에 일치하고 잘림·겹침이 없음을 확인했다. 검토 중 모델·네트워크·DB 호출은0이다.

[독립 실행 검증](../../.local-data/project-agent-work/rag-e-experiment-20261020/independent/final-review.json), [표현 자료 검증](../../.local-data/project-agent-work/rag-e-experiment-20261020/independent/presentation-review.json), [최종 작업 범위·보존 확인](../../.local-data/project-agent-work/rag-e-experiment-20261020/final-verification.json)을 남겼다. 기존 작업 파일2,022개 중 이번 실행으로 바뀐 파일은 WORKBOARD와 이 기록뿐이며 새 문서 자산은 위 HTML/PNG 두 개다.

ISSUE-00005 운영 이력 DB 반영은 미완료 상태를 유지한다. 로컬 후속 초안을 남기며 DB를 직접 고치거나 저장 성공을 주장하지 않는다. 새 결과는 이 기록과 설명 자료에 반영했고 커밋·푸시는 하지 않았다.

## 상위 모델 비교 준비

사용자가 더 강한 모델과의 비교 및 중단된 조사 재개를 요청했다. 이번 단계는 낮은 위험의 읽기 전용 후보·환경 조사이며 메인이 AI 엔지니어와 RAG 리드 역할을 맡는다. 제품 구현·UI·DB 구조 변경은 없어 해당 구현 역할을 배정하지 않았다. 실제 실행기가 필요해지면 실행 범위와 독립 검증 역할을 다시 고지한다.

중단 전 Ollama GET에서 설치 모델은 기존 `gemma4:e2b-it-q4_K_M` 한 개, 로드 모델은 0개, 런타임은 `0.40.3`이었다. 새 후보 모델은 설치되지 않았다. 재개 후 Windows 읽기 전용 CIM으로 총 가용 물리 메모리 24,646,392KiB(약23.50GiB), 여유 3,452,264KiB(약3.29GiB), C 드라이브 여유127,326,785,536bytes(약118.58GiB)를 확인했다. 여유 공간은 시점 관측값이며 메모리 확보나 모델 로드 성공을 뜻하지 않는다. 일반 샌드박스의 드라이브 조회는 값이 비어 있어 이 CIM 관측값을 사용한다.

비교 후보는 `gemma4:12b-it-q4_K_M`이다. [Ollama 공식 배포 정보](https://ollama.com/library/gemma4:12b-it-q4_K_M)는 약8.0GB, Q4_K_M, digest 접두사 `6114515d63c1`을 제시한다. 실제 다운로드 이후에는 전체 digest·template·기본 옵션과 런타임 호환성을 다시 확인해야 한다. 모델 파일 크기는 실행 메모리 요구량과 같지 않으며 현재 여유 메모리로 즉시 실행할 수 있다고 판정하지 않는다.

[Google 공식 모델 카드](https://ai.google.dev/gemma/docs/core/model_card_4)의 MMLU Pro는 E2B60.0%/12B77.2%, GPQA Diamond는43.4%/78.8%로 상위 후보 선정 근거가 된다. 해당 벤치마크는 이번 Q4_K_M·reasoning 없음·RAG 입력에서의 성공 보장이 아니다. 같은 계열·양자화 종류를 택해 차이를 줄이되 모델 구조·배포 template·draft 모델과 기본 설정까지 동일하다고 주장하지 않는다.

외부 실행 경로도 조사했다. 연결 도구 검색에서 직접 추론을 수행할 적합한 플러그인은 확인하지 못했으며 설치하지 않았다. [Ollama Cloud 문서](https://docs.ollama.com/cloud)는 대형 모델 원격 실행을 제공하지만, [구조화 출력 문서](https://docs.ollama.com/capabilities/structured-outputs)는 현재 Cloud에서 이를 지원하지 않는다고 명시한다. 저장된 E 요청에 `response_format.type=json_schema`가 있으므로 Cloud로 단순 교체하면서 같은 조건이라고 보고할 수 없다. 보유한 GPU 서버의 호환 Ollama를 쓰는 경로는 주소·권한·모델과 기능을 확인하기 전에는 미확정이다.

제안한 비교 범위는 다음과 같다. 아직 실행 승인·신규 예산을 부여한 기록은 아니다.

- 원래 E의 system/user 메시지, 원문·순서·인용 ID, 응답 schema와 평가 기준을 보존한다. 모델 선택은 버전이 있는 별도 실험 설정으로 관리하고 업무 코드나 기존 운영 프로필을 바꾸지 않는다.
- 정상/근거 부족 각2회, 총 최대4회 신규 생성이다. 실패·시간 초과도 소진하고 retry0, timeout360초, 출력512, temperature0, reasoning 없음으로 비교한다. 새 검색·임베딩·예열 생성·일반 큐 실행은 포함하지 않는다.
- 비교 기준은 이미 저장된 E2B 실제4회 결과다. 동시 대조 실험이나 모델 크기만의 인과 검증으로 확대하지 않으며, 다른 시점·자원·캐시 조건의 지연을 구분해 보고한다.
- 필요한 일반 규칙과 조건 포함, 정확성·근거 포괄성·거절 정확도 각1, 유효 인용, ACL 누출0 및 전체 RAG P95≤120초 기준을 유지한다. 이 생성 단계 비교만으로 전체 RAG 성능·전역 ACL 검증이나 운영 승격을 완료하지 않는다.
- 실행 전 현재 원문 접근·모델/프로필·입력 해시, 전체 모델 digest와 호환성·메모리 여유를 확인한다. 기존 소진 실행기·manifest를 고치거나 재사용 실행하지 않고 별도 예산과 독립 검증을 준비한다.

기존 사용자 지시의 신규 다운로드 금지 범위를 변경해야 하므로 약8GB 로컬 다운로드와 메모리 확인 후 최대4회 생성 허용 여부를 질문했다. 대안은 사용자가 지정한 GPU 서버다. 선택 전에는 후보 다운로드·외부 본문 전송·생성·서비스 종료를 진행하지 않는다. 이번 조사에서 추가 생성·설치·다운로드·DB 변경은0이며 기존 E 예산은4/4 소진 상태로 남는다.

### 12B 다운로드 승인과 실행 준비

위 제안에 사용자가 “그래 진행해봐”로 동의했다. 이번 승인에는 `gemma4:12b-it-q4_K_M` 다운로드와 메모리 확인 후 최대4회 비교가 포함된다. 다른 모델·패키지 설치나 추가 호출로 확대하지 않는다. 새 실험 경로는 `.local-data/project-agent-work/rag-12b-comparison-20261020/`이며 메인이 AI/RAG 실행을, 별도 검토자가 경계·결과 검증을 맡는다. UI·DB 구조·운영 배포 역할은 변경이 없어 제외한다.

기존 Ollama의 `/api/pull`로 다운로드를 완료했다. 2026-10-20 17:00:35 KST에 설치된 모델 크기는8,021,618,941bytes(약7.47GiB), full digest는 `6114515d63c17436a7c0417d82820ac65ad643e2806c5a3c89cb62846436ed0b`다. 기존 E2B 이름·digest는 보존했고 두 모델 모두 로드하지 않은 상태를 확인했다. 모델 파일은 기존 저장소에 두었으며 프로젝트나 Git에 복사하지 않았다. [다운로드 결과](../../.local-data/project-agent-work/rag-12b-comparison-20261020/download-complete.json)

저장한 E의 system/user·근거·schema·옵션은 그대로 재사용하고 최종 요청의 model만 바꾸는 실행기를 준비했다. 원본 admission으로 원문 접근·프로필·기존6개 DB 테이블 해시를 확인하고, 새 실험 identity의 typed deployment/profile도 기존 정책·런타임 resolver를 통과시킨다. 이번 profile은 로컬 실험 기록이며 애플리케이션에 등록되거나 기존 운영 프로필로 대체된 것이 아니다. 실제 읽기 전용 사전 검사에서 이 경로가 통과했고 DB6해시는 이전 E와 같았다. [사전 관측](../../.local-data/project-agent-work/rag-12b-comparison-20261020/preflight-inspection.json)

모델 metadata 조회에서 두 모델의 표시 template `{{ .Prompt }}`와 기본 draft3·temperature1·top_k64·top_p0.95는 같았다. 실제 요청은 기존과 같이 temperature0·출력512·reasoning 없음으로 덮어쓴다. 모델 내부 구조·draft 가중치·실행 토큰 수나 지연까지 같다는 의미는 아니다.

메모리 사전조건은 미적재 모델 크기에 여유2GiB를 더한 약9.47GiB다. 이는 실측 peak가 아닌 보수적인 진입 기준이며 실제 성공 보장이 아니다. 정확한 이름·full digest의 대상이 이미 적재돼 있으면 `/api/ps`의 적재 크기를 중복 계산하지 않지만, 이것도 OS working set 실측값은 아니다. 실행 전과 각 슬롯 전에 물리·commit 여유를 다시 검사하며 다른 모델 적재·메모리 부족이면 생성 전에 멈춘다. 17:03:40 KST 관측은 물리 여유3,954,622,464bytes(약3.68GiB), commit 여유10,145,280,000bytes로 기준을 충족하지 않았다.

저장하지 않은 사용자 작업을 잃을 수 있어 앱을 강제 종료하지 않고, 사용 중이 아닌 IDEA·Unity·Blender 등의 작업 저장 후 종료를 요청했다. 메모리 확보를 기다리는 동안 생성0/4·임베딩0을 유지했다. 실제 모델 로드·4회 품질 비교·새 답변/이미지는 아직 생성하지 않았다. 기존 E2B의 품질 실패를 12B 결과로 옮겨 적지 않는다.

실행기 검사는 새9개+기존E8개가 통과했다. 최초 미구현 수집 실패 후 구현했으며, 이후 pytest의 작업 경로 미포함으로 수집이 한 번 더 실패해 명시적 `PYTHONPATH`로 해결했다. 독립 검토의 새 deployment 정책 경로·로드 digest 확인 지적을 반영했고, 프로세스별 frozenset 문자열 순서 차이가 profile 비교를 오탐시키는 재현에 따라 snapshot을 정렬 배열로 정규화했다. 과거 관측 JSON은 덮어쓰지 않아 초기 snapshot 문자열 표현이 남아 있으며 실제 freeze/execute는 수정한 정규화를 함께 사용한다.

최종 독립 검증은 네트워크를 차단한27개 검사와133개 산출물 검사를 통과했다. hashseed1~4에서 정규화 결과가 같고, 과거E의103개 고정파일·4개 실제 E 입력과 model 외 동일성·DB6개 저장해시·별도 실험 identity를 확인했다. 메인의 최종17개 테스트와 Ruff F도 통과했다. 이는 실행 준비 검사이며 실제 12B 응답 검증이 아니다. [독립 검토](../../.local-data/project-agent-work/rag-12b-comparison-20261020/independent/review.md), [산출물 검사](../../.local-data/project-agent-work/rag-12b-comparison-20261020/independent/final-artifact-review.json)

17:07:36 KST의 [최종 준비 상태](../../.local-data/project-agent-work/rag-12b-comparison-20261020/preparation-status.json)는 물리 여유3,378,946,048bytes(약3.15GiB), commit 여유9,747,861,504bytes(약9.08GiB)로 여전히 미달이다. 실행 manifest·started·예약은 없으며 새 생성 예산0/4다. 기존 승인은 유효하므로 메모리가 확보되면 현재 상태 재확인→manifest 고정·독립 확인→최대4회 실행→실제 답변 평가 순서로 이어간다. 앱 강제 종료, 새 품질 판정, 운영 승격, 커밋·푸시는 하지 않았다.

### 12B 실제 시도와 시간 초과

이 절은 위 준비 시점 이후의 실제 실행 결과다. 사용자가 “일단 더 뺼게 없어. 일단 진행해봐”라고 요청해 보수적인 물리 메모리 진입 기준 미달을 명시적으로 허용했다. 물리 여유는 계속 기록하되 commit 여유 검사, 정확한 모델 이름·digest, 최대4회·재시도0·첫 오류/시간 초과 시 중단을 유지했다. 입력·출력 한도나 품질 기준은 변경하지 않았다. 메인이 AI/RAG 실행을, 기존 독립 검토자가 준비와 결과 검증을 맡았고 제품 UI·DB 구조·운영 배포 변경 역할은 제외했다.

[승인 범위](../../.local-data/project-agent-work/rag-12b-comparison-20261020/memory-trial-authorization.json)를 설정 version2에 고정했다. 예외는 기본 검사 동작을 바꾸지 않고 이번 명시 설정에서 물리 기준만 허용한다. 메인18개 테스트·Ruff F, 네트워크를 차단한 독립34개 테스트와137개 산출물 검사가 통과했다. 이전 준비본3파일과 기존 E의103개 고정파일을 보존했으며 최종 [manifest](../../.local-data/project-agent-work/rag-12b-comparison-20261020/manifest.json)는111개 파일, SHA256 `85aa05091bccdff237418a31f3c50dc8a97f972f93de0139ac7b0e59d3400687`이다. [실행 전 독립 확인](../../.local-data/project-agent-work/rag-12b-comparison-20261020/independent/approved-memory-trial/review.md)

| 항목 | 실제 관측 |
| --- | --- |
| 모델 | `gemma4:12b-it-q4_K_M`, 위 다운로드와 같은 full digest |
| 첫 슬롯 | `01-normal-E-1`, 저장된 E 정상 사례 |
| 전송 시각 | 2026-10-20 21:59:17.886898 KST |
| 종료 시각 | 2026-10-20 22:05:17.912008 KST |
| 결과 | `TimeoutError`, 전송부터 오류 기록까지360.02511초 |
| 호출 집계 | 예약·전송 시도1회, 반환 응답0회, 남은3회 미실행 |
| 추가 처리 | 재시도0, 새 검색·임베딩0, 정상 큐 실행0 |
| 원문·메시지 | 기존 E와 동일, 외부 model 지정만 교체 |
| 생성 설정 | 출력512, temperature0, reasoning 없음, timeout360초 |
| 전송 기록 | 13,311bytes, SHA256 `bb38622c176c395c6571b3686a66d3320818231a6a70680054f74c890bddfd18` |

[예약](../../.local-data/project-agent-work/rag-12b-comparison-20261020/01-normal-E-1-reserved.json)과 [실패 기록](../../.local-data/project-agent-work/rag-12b-comparison-20261020/01-normal-E-1-error.json)을 보존했다. 클라이언트 프로세스는 종료 코드1로 끝났으며 그 뒤 슬롯은 보내지 않았다. 성공 `result.json`이나 `completion.json`은 없고, 실패 후 보존 확인을 성공 완료로 표시하지 않는다. 남은3회는 자동 재개하지 않으며 한 번 사용한 시작 표식을 우회하거나 새 예산으로 재시도하지 않았다.

**확인한 범위와 남은 원인:** 전송 직전 물리 여유는약6.99GiB, commit 여유는약39.82GiB였다. 요청 약34초 후부터 정확한12B digest의 적재를 관측했고 `size_vram=0`, `context_length=16384`, runner `llamacpp`였다. 응답 대기 중4개 관측의 물리 여유는약2.95→2.25GiB였다. [런타임 관측](../../.local-data/project-agent-work/rag-12b-comparison-20261020/runtime-observations.jsonl)

이는 모델 적재와 응답 대기 시간 초과를 보여준다. 입력 처리·답변 생성·페이징 등 세부 단계의 시간이나 page fault를 측정한 기록은 없어 RAM만을 원인으로 확정할 수 없다. `/api/ps`의 size 값도 전체 OS 상주 메모리 실측으로 해석하지 않는다. 비스트리밍 요청에서 HTTP 응답·본문·usage를 받지 못했으므로 실제 내부 생성 토큰 수는 미확인이다. 요청별 서버 로그는 확보하지 못했다. 클라이언트 종료나 적재 목록만으로 서버 내부 요청 종료를 입증하지 않는다.

**품질 판정:** 이번12B는 검토할 답변이 없어 정확성·근거 포괄성·인용 유효성·거절 정확도를 판정할 수 없다. 기존 E2B의 정상0/2·적절한 거절2/2를12B에 적용하지 않는다. 첫 요청은120초 내 답을 제공하지 못했지만 반환 응답0개로 평균이나 P95를 계산하지도 않는다. 이번 결과는12B가 규칙을 잘못 판단했다는 증거가 아니며, 전체 RAG 품질 또는 상위 모델 우위 검증은 미완료다.

실패 후 읽기 전용으로 원문 접근과6개 DB 테이블의 행 수·SHA를 재확인했다. 모두 사전값과 같고 고정111개 파일도 보존됐다. [실패 후 검증](../../.local-data/project-agent-work/rag-12b-comparison-20261020/failure-finalization.json)에는 `workflow_completed=false`, `quality=not_evaluable_no_response`를 명시했다. 운영 프로필·평가 이력·도메인 READY·연결 활성화는 바꾸지 않았다.

### 12B 실제 시도 설명 자료

- [실제 질문 → 원문 근거 → system/user → 시간 초과 기록](assets/rag-12b-20261020/actual-comparison.html)
- [실제 비교 설명 이미지](assets/rag-12b-20261020/actual-model-comparison.png)
- [자동 재계산](../../.local-data/project-agent-work/rag-12b-comparison-20261020/analysis.json), [SHA에 연결한 결과 해석](../../.local-data/project-agent-work/rag-12b-comparison-20261020/semantic-review.json)

HTML에는 실제 실패한 요청의 전체 지침·메시지·검색 원문과 전송 SHA를 넣었다. 이미지는 실제 E 원문과 지침을 발췌하고 과거 E2B 답변과 이번12B 응답 없음을 구분한다. 없는 답변이나 예시 출력을 생성해 실제 결과로 제시하지 않았다. 생성한 PNG를 열어 잘림·겹침을 확인했고, 로컬 보고서와 문서 자산의 SHA가 일치한다. 문서 자산2개는 합계351,236bytes다. HTML 브라우저 배치와 제품 UI E2E는 이번 검증 범위가 아니다.

실행 후 [독립 확인182개](../../.local-data/project-agent-work/rag-12b-comparison-20261020/independent/post-timeout/verification.json)가 통과했다. 고정111개 파일, 실제 요청과 예약의 SHA·크기·모델,360.02511초 산술,1예약/1오류/0응답, DB6개 저장해시, 의미 검토와 표시 자료를 대조했다. 네트워크를 차단하고 분석기를 별도 검토 폴더에서 재계산해 원본과 일치함을 확인했으며 추가 모델·네트워크·DB 호출은0이다.

[메인 최종 확인](../../.local-data/project-agent-work/rag-12b-comparison-20261020/final-verification.json)에서도 기존 작업 파일2,022개를 보존했고 변경은 WORKBOARD와 이 기록2개뿐이었다. 문서 링크112개·코드 블록·`git diff --check`, 보고서 SHA와 준비 테스트 결과18개/독립34개의 실패0을 확인했다. 이 최종 기록 링크 추가 후에도 로컬 링크와 diff 검사를 다시 확인했다.

ISSUE-00005 운영 이력 DB 반영은 기존과 같이 미완료다. 이번 실행의 시간 초과와 답변 부재는 이 기록에 남겼으며 인증된 관리 경로를 우회하거나 DB를 직접 수정하지 않았다. 기존 사용자 파일과 미커밋 구현을 보존했으며 커밋·푸시는 하지 않았다.

후속2026-10-21 [동일 입력 단일 진단](2026-10-21-rag-12b-timeout-diagnosis.md)에서 CPU 경로의 입력 처리 완료 전360초 제한 도달을 관측했다. 전일 실행에 없던 단계 관측을 추가한 재현이며 전일 원시 기록을 소급 변경한 것이 아니다. 두 시도 합산2/최대4회, 응답0·재시도0이며 나머지2회는 실행하지 않았다.
