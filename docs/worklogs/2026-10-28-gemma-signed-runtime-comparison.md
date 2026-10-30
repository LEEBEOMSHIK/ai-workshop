# Gemma 서명 ARM 후보의 비교 실행 연결

> 실제 비교 결과: 사용자 승인 최대4회 중 후보 첫1회가360초 시간 초과·완료 응답0으로 종료됐다. 남은3회·자동 재시도는 실행하지 않았으며 후보를 채택하지 않는다. 아래 실제 실행 결과를 따른다.

관련 문제: ISSUE-00038. [서명 후보·입력 변환 준비](2026-10-28-gemma-signed-runtime-candidate.md) 다음 작업이며, [수행 계획](../superpowers/plans/2026-10-28-signed-runtime-comparison.md)에 따라 비기본 비교 도구를 연결했다. 기존 답변·인용과 동일한 조건에서 입력 처리 시간을 비교하는 것이 목적이다.

## 수정 내용과 범위

`.local-data/project-agent-work/gemma-signed-comparison-20261028/`에 후보 서버 수명 관리, native 응답 검증, 예산·결과 기록과 비교 coordinator를 구현했다. 기존 main GGUF·공개 합성 질문·28개 근거·schema2·출력512·문맥16384·batch/ubatch1024를 유지한다. 실제 호출 직전 현재 원문 권한과 고정 입력을 다시 읽으며, 제품의 기존 schema 해석과 CitationValidator로 답변·인용을 확인한다.

예정 실행은 **후보2회 → 소유 후보 종료 확인 → 기존 Ollama2회**, 합계 최대4회·자동 재시도0이다. 첫 실행과 반복 실행의 캐시 효과를 구분한다. 기존 사용자 모델을 강제 unload하거나 기존 Ollama 서버를 재시작하지 않는다. 후보가 종료되지 않거나 품질·입력 검증이 실패하면 후속 호출을 중단한다. 실패·전송 불확실도 소비한 호출로 기록한다.

후보는 인증된 loopback에서 실행하고 자체 Windows Job에 속한 프로세스만 회수한다. 임시 인증 파일은 owner/SYSTEM 권한으로 제한하고 종료 시 자체 파일만 제거한다. 입력·응답 원문·내부 추론·토큰 배열·네이티브 로그를 저장하지 않으며 시간·토큰 수·해시·품질 판정만 남긴다. HTTP origin·응답 크기·전체 기한을 제한하고 프록시·redirect·자동 재시도를 사용하지 않는다.

현재 작업은 비교 진단 도구이며 제품 코드·일반 연결·프로파일·DB schema·운영 기본값을 바꾸지 않는다. UI·DB schema 역할은 제외하고 AI 구현, 인프라 수명 관리, 독립 코드/프라이버시 검토를 분리했다. root가 통합·문서를 담당했다.

## 실제 사전 검사에서 찾은 입력 계약 결함

첫 읽기 전용 준비에서 기존 서비스 식별자·유휴 상태·현재 ACL·고정 자료를 읽은 뒤 mapper가 `ValueError`로 중단됐다. 후보 서버·모델·생성 호출은 시작되지 않았다. 예외 원문 대신 파일/함수/행 위치만 조사했다.

제품의 `http_generation_input()`은 항상 `schema_version: 2`를 포함하지만 이전 mapper의 정확 필드 허용 목록과 수작업 합성 fixture가 함께 이 필드를 빠뜨렸다. 앞선 순수 mapper 테스트가 실제 제품 직렬화 계약을 확인하지 못했던 결함이다. 필수 정수2만 허용하고 누락·bool·float·문자열은 거절하도록 수정했다. 질문·근거·직렬화된 본문은 변경하지 않는다.

해당 수정 뒤에도 실제 준비는 같은 필드 집합 검사에서 중단됐다. 현재 ACL로 조회한 고정 입력의 필드명·자료형만 조사해, 일반 직렬화8필드에 SDK direct 실행이 붙이는 `delegated_task: str`가 추가된9필드임을 확인했다. 따라서 최초 실패를 schema 필드 하나만의 문제로 본 진단은 불완전했다. SDK는 `openai_agents.py`의 `specialist_input()`에서 원 질문을 이 필드로도 전달한다. 고정 비교 입력을 바꾸지 않도록 해당 문자열을 보존하는 지원과 실제 SDK 경로 회귀를 추가했다. 다른 임의 확장 필드는 계속 거절한다.

기존 mapper 원문5,644bytes/SHA256 `ffa5570a9b2b14e3d786c44ad81d0e51127003fc0a0303e78c712382738271ff`를 `signed_replay_input.before-schema-fix.txt`로 보존했다. schema만 수정한 중간본5,748bytes/SHA256은 `d404a988396e547cdc163276c6ed5f0090a9bc557bca989ccec19ce771fa7f38`이다. 실제 제품 직렬화기를 사용하는 신규 공개 합성 회귀로 수정 전 같은 실패와 수정 후 일반8필드 통과를 확인했다. 앞선 worklog의 해시는 당시 실행 이력으로 유지한다.

중간본도 `signed_replay_input.before-delegated-task-fix.txt`로 보존했다. 최종 mapper6,047bytes/SHA256은 `e66d8ac01430f454ccf3999da48f7f7988bcbfe882c695cf703e98f09dd9f2c8`이다. 구현 담당은 실제 중첩 `specialist_input()`을 호출해 SDK 입력을 캡처했고, 독립 담당은 실제 `generate()`→Runner→ObservedLocalTransport→native 요청까지 mock 전송으로 실행했다. 두 경로 모두 중간본의 실패와 최종본의 입력 보존을 확인했다.

## 오프라인 검증

root가 기존 저장소 Conda Python으로 최종 통합 pytest를 실행해 **198개·114 subtests 통과(5.57초)**를 확인했다. guard8·coordinator8·응답97·수명28·독립 리뷰39·수정 mapper18개다. 전체 비교 폴더와 mapper의 Ruff, 구현5파일 strict mypy도 통과했다. 이는 외부 모델·네트워크 없는 mock/합성 검증이며 실제 모델 품질을 뜻하지 않는다. 앞선187개 및 추가 일반 계약6개 검증을 SDK 경로까지 보강해 다시 실행한 결과다.

검증은 예산 순서/상한, 중복 JSON·비정상 Unicode·schema/인용·토큰 한도, 품질 불일치 기록 후 중단, 재전송 방지, 현재 ACL 변경, 응답 후 환경 변동, 후보 회수 불확실성과 runtime 식별/실행 인자 검증을 포함한다. 독립 검토로 발견한 종료 확인 누락, 마지막 환경 변동의 성공 처리, BOS 누락, 시간 제한 없는 이전 metadata 호출, 관측 수치 미보존을 수정하고 회귀 검증했다.

Windows asyncio의 loopback/socketpair 초기화는 제한된 실행 환경에서 멈췄다. 해당 테스트 프로세스를 중단하고, 모델·DB·HTTP가 모두 mock인 회귀만 호스트에서 실행했다. 독립 최초31개 중 coordinator10개는 OS 루프를 사용하지 않고 즉시 완료되는 mock await로 제어 흐름을 검증했다. 추가 SDK 독립2개를 포함한 최종 suite는 실제 루프와 mock 전송을 사용하며 외부 connect·DNS·DB engine·프로세스 실행에는 실패용 tripwire를 적용했다. 실제 비동기 전송·모델 실행 성공으로 확대하지 않는다.

독립 상세 검토는 로컬 `review_final.md`, 응답 계약의 공식 upstream 근거는 `completion-result-notes.md`에 보존한다.

## 본래 환경 준비 및 다음 경계

2026-10-28T13:33:46Z에 본래 환경의 `run_comparison.py prepare`가 exit0으로 완료됐다. 원래 계정의 현재 원문 권한, 공개 합성 질문·28근거·고정 payload, 원래 Ollama 식별자/버전/유휴 상태, 서명 bundle과 전체 main GGUF 해시를 확인했다. DB transaction은 읽기 전용이며 후보 서버·모델 적재·생성·DB 쓰기는0이다.

| 준비 결과 | 값 |
| --- | --- |
| 비교 범위 | `gemma-signed-arm-candidate2-baseline2-v1` |
| 코드 해시 | `c6ed1c38431f6f339757a05dd0aa77c5a935222422955ad3139065472eb28c7b` |
| 기존 `.env` 해시 | `44fc0ddb25fc98bfde714b05687afc57fb4a460fb8c7603a375c9ed832bdcb33` |
| main GGUF 전체 해시 | `6dd7ac24fe13a238898e16e253ebc7a72fa27fb83f2658c2f6c241df3af5937d` |
| 기존 입력 해시 | `4b7ffa1e49303fcb8a554efac79ee83cca445c8c7fae3cd1cbcced26e5b69380` |
| 후보 입력 해시 | `14bc30c3e25cda875670638b5808329038730c59fa81e95b3921a5d1c4c090f5` |
| 현재 권한·28근거·기존 유휴·이전 ledger 보존 | 모두 확인 |

준비 시점에는 로컬 `preparation.json`과 `approved: false`인 `approval-template.json`만 저장했다. 당시 이전 실제 생성4/4 범위는 종료 상태이며 새 승인 파일과 생성 ledger가 없었다. 이후 새 승인과 실제 실행은 아래 절을 따른다. 준비 성공을 속도 개선으로 보고하지 않는다.

이 비교는 런타임·컴파일·초안 생성 설정 차이가 있는 전체 실행기 비교다. 차이가 나더라도 DOTPROD/i8mm 한 요소의 효과로 단정하지 않는다. 실제 thread 인자가 없으면 자동 실효 스레드는 미확인으로 남긴다. 현재 후보의 모델 로드·토큰화·schema 출력·입력 시간·답변/인용은 실제 실행 전까지 미확인이다.

기존 일반 지급 규칙 누락·정답0/2는 미해결이다. 같은 질문의 답변·인용 일치는 추가 퇴행 없음만 뜻하며 전체 품질 통과가 아니다. ISSUE-00038의 운영 정본 DB 갱신도 미완료다. 이 파일은 상세 작업 기록이며 DB 저장 완료를 대신하지 않는다.

## 승인 후 실제 실행 결과

사용자가 후보2회·기존Ollama2회, 최대4회·자동재시도0 실측을 승인했다. 준비된 코드/환경/입력 해시와 일치하는 새 `approved-comparison.json`을 생성하고 `run_comparison.py run`을 한 번 실행했다. 최초 후보 요청의 시간 초과로 중단 조건이 적용돼 **후보1회 사용·기존0회·남은3회 미사용 종료**다. 승인·실패 ledger는 덮어쓰지 않는다.

| 실제 관측 | 결과 |
| --- | --- |
| 후보 실행 시작 | 2026-10-28T14:21:08Z |
| 후보 준비 완료 | 48.190334초 |
| 실제 실행 인자 | CPU·batch1024·ubatch1024·context16384·parallel1 |
| thread / batch-thread | 명시 인자 없음, 자동 실효값 미확인 |
| speculation | 명시 인자 없음, 효과 추론하지 않음 |
| 사전 토큰화 | 3,549토큰, 선행 BOS 검사 통과 |
| 최초 후보 전송 예약 | 2026-10-28T14:22:00.357244Z |
| 실패 기록 | 2026-10-28T14:28:00.578071Z, `TimeoutError`, 프로세스 exit1 |
| 예약부터 실패 기록까지 | 360.220827초 |
| 완료 응답·답변/인용 판정 | 0건·미검증 |
| native 입력/출력 시간·반복/기준 비교 | 미수집·미실행 |
| 채택 | **미채택** |

360.220827초는 전송 예약부터 실패 기록까지의 간격이며 cleanup/전송 경계를 포함한다. native prefill 시간이 아니고 과거 입력131.222초와 같은 항목으로 비교할 수 없다. 이번 실행에서는 응답이 돌아오지 않아 입력 처리와 출력 생성 중 어느 단계에 머물렀는지 확인할 수 없다. 서명·ARM 가속 지원·실제 모델 로드/토큰화가 확인돼도 성능 향상이나 답변 품질 보존을 보장하지 않는다는 결과다.

실행 중 정확한 후보 프로세스1개/PID191124를 읽기 전용으로 한 번 확인했다. 당시 working set2,942,910,464bytes, CPU 누적569.421875초였으나 연속 표본·시작 대비 차분이 아니므로 CPU 사용률이나 메모리 병목의 기여도로 해석하지 않는다. 이 후보에서 자동 스레드, 계산 단계 진행, 시스템 가용 메모리/페이지 폴트의 동시 관측이 부족해 시간 초과 원인은 미확인이다. 다음 수정은 이 관측 공백을 먼저 보강하는 것이다. 근거 없이 스레드·batch·문맥·근거 수를 다시 바꾸지 않는다.

실행 후 `post-runtime-check.json`에서 정확 후보 경로·PID·자식·18089 listener·private session 디렉터리가 모두0임을 확인했다. `post-preservation-check.json`에서 코드·`.env`·기존 종료 ledger2개·서명 bundle·원래 Ollama 식별자/유휴 상태·현재 원문 권한/고정28근거·main GGUF 전체 해시 보존을 확인했다. 제품/연결/프로파일 변경·기존 서비스 재시작·DB 쓰기·추가 생성은0이다.

`comparison.events.jsonl` 최종 SHA256은 `a18b28189a8e9e34eb2e09429dbb2adaa9028e2b6323c8bb5cb763b906bfa52e`다. `scope-closure.json`은 승인4/사용1/미사용3·종료·재시도0·품질 미확인·미채택을 기록한다. 독립 담당이 실제7행 ledger·승인/준비/보존 해시·종료 범위를 대조했고 `actual-comparison-review.md`에 검토를 완료했다. 독립 보고서 SHA256은 `6055b0265c2cd856a369c867443fba5bfcf4aaf3391336d93f128fcbcb71fd2c`다. 실패 경로에는 정상 완료용 `candidate_closed` 이벤트가 없으므로 프로세스 회수는 별도 사후 관측 근거로 구분한다.

## 운영 문제 이력 반영 상태

Chrome 연결은 복구된 상태여서 기존 AI Workshop 탭에서 관리자 문제 이력으로 이동했다. `/admin/system/issues`가 `REQUEST FAILED` / 화면을 불러오지 못했습니다 / 진단참조3227098399를 표시했고 한 번 재조회해도 같았다. 인증정보 추출·다른 계정·직접 DB 쓰기·서비스 재시작으로 우회하지 않았다. **ISSUE-00038의 DB 갱신은 여전히 미완료**이며 현재 결과는 이 worklog와 WORKBOARD/로컬 실행 ledger에 남긴다. 화면 실패의 서버 원인은 이번 실측 범위에서 확인하지 않았다.
