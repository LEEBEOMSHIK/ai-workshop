# Gemma 입력 처리 개선: 서명된 ARM 런타임 후보

> 후속: [비교 실행 연결·실제 시도](2026-10-28-gemma-signed-runtime-comparison.md)에서 최초 후보 요청이360초 시간초과·응답0으로 끝나 미채택했다. 아래는 후보 준비 당시의 기록이며 입력 계약2건 수정·검증과 실제 실패/정리 근거는 후속 문서를 따른다. 속도 향상·품질 보존은 입증되지 않았다.

관련 문제: ISSUE-00038. 사용자 요청은 답변 품질·기존 기능을 유지하는 성능 개선의 다음 수정이다. 이전 [CPU·GPU 조사](2026-10-28-gemma-gpu-memory-improvement.md)에서 확인한 장치의 ARM Dot Product/i8mm 지원과 설치 backend의 지원 부재를 대상으로 실제 공식 배포 파일을 검사했다.

## 현재 판정

**서명과 ARM 가속 컴파일 지원을 함께 갖춘 LM Studio CPU 런타임을 확보했다.** 최신 Ollama ARM 배포본에는 여전히 해당 가속이 없어 단순 업데이트는 이번 후보로 채택하지 않는다. 이는 실행기 후보의 정적 검증 결과이며 모델 호환·입력 처리 시간·답변 품질 개선 완료가 아니다.

설치·서비스·기본 연결·프로파일·모델·문맥/출력 한도를 변경하지 않았다. 이전에 차단된 unsigned OpenCL portable은 다시 실행하지 않았으며 보안 정책도 변경하지 않았다. 종료된 4/4 실제 모델 호출 범위는 재사용하지 않는다.

## 실제 배포 파일 비교

| 조건 | 설치 Ollama 0.40.3 | 공식 Ollama 0.40.12 | LM Studio CPU 2.65.1 |
| --- | --- | --- | --- |
| 검사한 CPU DLL 아키텍처 | ARM64 | ARM64 | ARM64 |
| CPU DLL 서명 | 기존 검증 유지 | Valid / Ollama Inc. | Valid / Element Labs Inc. |
| NEON / ARM FMA | 1 / 1 | 1 / 1 | 1 / 1 |
| DOTPROD / i8mm | 0 / 0 | 0 / 0 | **1 / 1** |
| FP16 vector arithmetic | 0 | 0 | 0 |
| Adreno backend | 없음 | ZIP에 없음 | 해당 CPU 패키지에 없음 |

위 0/1은 PE export의 RVA를 실제 파일 offset으로 변환해 ARM64 함수의 상수 반환 명령을 읽은 결과다. 후보 함수 호출·DLL 로드나 모델 벤치마크로 얻은 수치가 아니다. LM Studio의 DOTPROD offset22084와 i8mm offset22100은 각각 `20 00 80 52 C0 03 5F D6` (`mov w0,1; ret`)다. 독립 담당이 별도 PE 해석으로 같은 결과를 확인했다. Q4_K 내부 함수가 export되지 않아 모든 연산의 실제 최적화 경로·속도 배수까지 증명하지 않는다.

- 공식 Ollama ZIP: 215,776,808bytes, SHA256 `e64ab13a21bde937abcec5c3d2b5bf8b1a152f325a018077a6767df07c7f7391`. CPU/runner/core 7개만 추출해 ARM64와 유효 서명을 확인했다. CPU DLL SHA256은 `4e63ca0b622ee576e234c45fb5633335efa9ceed45562db5aff8cc523e0ef11c`다. 공식 릴리스의 Gemma4 prefill 개선 문구는 Apple silicon에 해당하며 Windows ARM 개선 근거로 사용하지 않는다. [배포 파일·SHA](https://github.com/ollama/ollama/releases/expanded_assets/v0.40.12), [릴리스 설명](https://github.com/ollama/ollama/releases/tag/v0.40.12).
- LM Studio runtime: 8,429,801bytes, SHA256 `25acd443163beb90d6bf4439736c152800b806192263e5ec160a051f643c183d`; vendor: 478,763bytes, SHA256 `33ce2326c999396cd7489749d3d2953d5e768a642e49615334eeab5468247244`. 두 공식 카탈로그 값과 실제 파일 SHA를 대조했다. CPU DLL SHA256은 `a19e79c8f1d4ea31a6c90f868750127e8f0479fa43e03315b923e6eaf00fe9a8`이다. [공식 stable 카탈로그](https://extensions.lmstudio.ai/master-lists-v2/backends-master-list-stable.json), [runtime](https://extensions.lmstudio.ai/backend-llama.cpp-win-arm64-2.65.1.tar.gz), [vendor](https://extensions.lmstudio.ai/vendor-win-llama-cpu-arm-vendor-v1.tar.gz).

LM Studio 두 패키지는 총18파일·23,922,967bytes다. PE16개 모두 Authenticode Valid이며 runtime12개는 Element Labs Inc., vendor4개는 Microsoft 서명이다. runtime은 전부 ARM64다. vendor의 `VCRUNTIME140_1.dll` 하나는 x64이지만 전체 정적·delay import에서 참조되지 않았다. manifest가 지정한 standalone server8파일과 필요한 ARM64 vendor2파일로 의존 관계를 확인했다. 동적 로딩 가능성까지 정적 검사만으로 배제하지 않는다.

전체 LM Studio 앱을 설치하거나 다른 회사 DLL을 기존 Ollama에 섞지 않았다. 패키지 자체가 `llama-server.exe`와 engine protocol entrypoint를 제공한다. [동일 upstream tag의 옵션 처리](https://github.com/ggml-org/llama.cpp/blob/b11908/common/arg.cpp)는 `--version`이 버전 출력 후 종료한다고 명시하지만, 실제 배포 실행 검증은 별도 기록한다.

## 답변 조건 보존에 필요한 확인

현재 main GGUF는 `tokenizer.ggml.model=gemma4`, BOS2/EOS1, `add_bos_token=true`이며601개 텐서에 legacy projector prefix가 없다. 따라서 이 파일은 [Ollama 0.40.3의 legacy Gemma4 변환 조건](https://github.com/ollama/ollama/blob/v0.40.3/llama/compat/llama-ollama-compat.cpp)에 해당하지 않는다고 정적으로 추론한다. 다른 런타임에서 실제 로드가 된다는 증명은 아니다. main/projector/draft의 내용 주소·크기를 확인했지만 다중 GiB 가중치를 새로 전체 해시한 검사는 아니다.

모델의 작은 manifest template은 `{{ .Prompt }}`지만 실제로는 Ollama 전용 `gemma4` renderer/parser가 적용된다. main GGUF에는18,569bytes의 별도 Jinja template이 있다. 모델 이름과 질문 문자열만 같다고 최종 입력 토큰이 같다고 보고하지 않는다. 명시적 BOS와 자동 BOS, 역할 구분·공백·생성 prefix·thinking 비활성·stop 토큰을 대조해야 한다.

기존 요청은 temperature0·top_p1·출력512·think=false·schema2를 지정한다. 모델 기본값에는 요청에 없는 **top_k64·draft_num_predict3**도 있다. draft GGUF가 존재한다는 사실과 실제 speculative decoding 사용은 구분한다. 현재 draft 사용 여부는 미관측이므로 비교에서 확인하거나 변수 차이로 명시해야 한다. Ollama 0.40.3→0.40.12의 Gemma4 parser는 동일하나 renderer에는 변경이 있어, 최신 Ollama도 자동 동등 후보로 보지 않는다.

28개 근거·좌표·원문 관계·eN→UUID 매핑과 현재 소유자/출처 ACL을 유지한다. 기존 strict schema2 해석·숫자/인용 검증을 그대로 사용한다. 입력/출력 원문·내부 추론을 진단 파일이나 Git에 저장하지 않는다. 새 런타임의 schema-constrained 출력과 thinking 제어, 로그/보관 설정을 확인하고 기존 endpoint에 이름만 바꿔 연결하지 않는다.

기존 일반 지급 규칙 누락·정답0/2는 미해결이다. 동일 공개 질문의 답변·인용 일치가 확인되더라도 이 사례의 추가 퇴행 없음만 뜻하며 전체 품질 통과로 확대하지 않는다.

## 입력 변환 보강

비기본 비교용 순수 함수 `signed-runtime/signed_replay_input.py`를 구현했다. 모델·HTTP·DB·파일 입출력 없이 기존 native payload의 system1개/user1개·빈 history·v6 구조·think=false·출력512·정확 schema2만 받아 후보의 `/completion` 입력으로 변환한다. 도구·멀티모달·추가 옵션·다른 schema·중복 JSON 키 등 지원하지 않는 조건은 버리지 않고 거부한다. 이는 일반 대화용 제품 adapter가 아니다.

Ollama 0.40.3의 실제 처리처럼 renderer가 만든 선행 `<bos>` 하나를 제거한 prompt를 준비한다. 해당 GGUF tokenizer가 BOS를 자동 추가하기 때문이다. 메시지 안의 JSON을 다시 직렬화하지 않고 원래 바이트 표현을 유지하며, 양끝 공백은 Python의 넓은 `strip()` 대신 Go `unicode.IsSpace`와 같은 집합으로 처리한다. 기본 sampler의 top_k64, repeat_penalty1.0/last_n64, frequency/presence0, seed-1, n_keep4, cache_prompt와 보존 토큰6개도 명시한다. [원래 renderer](https://github.com/ollama/ollama/blob/v0.40.3/model/renderers/gemma4.go), [원래 completionPrompt/전송](https://github.com/ollama/ollama/blob/v0.40.3/llm/llama_server.go), [원래 기본값](https://github.com/ollama/ollama/blob/v0.40.3/api/types.go).

합성 입력3가지의 공식 Go 단순 렌더 식과 GGUF Jinja 결과를 오프라인으로 대조했고 mapper 회귀13개·Ruff2파일·strict Mypy1파일을 root도 재실행해 통과했다. 실제 저장 질문·28근거를 새 런타임으로 보내거나 tokenizer를 실행한 검증은 아니다. 최종 토큰 ID 동등성·schema grammar 동작·최종 응답 parser는 아직 검증하지 않았다.

독립 mapper 검증6개도 root 재실행에서 통과했다. 현재 제품 schema SHA를 직접 대조하고, 신규 합성28행의 순서·좌표·분해 Unicode·본문 `<bos>` 보존, Go 공백31경계, 중복 키·schema 오류의 입력 비노출, 함수 실행 중 파일/socket/프로세스/환경 접근 부재를 확인했다. 최종 mapper SHA256은 `ffa5570a9b2b14e3d786c44ad81d0e51127003fc0a0303e78c712382738271ff`다. 현재 GGUF의 generation metadata는 top_k64/top_p0.95/temp1뿐임을 별도로 읽고 옵션 우선순위와 대조했다. 나머지 sampler 기본값이 추가 override로 바뀌지 않음을 정적으로 확인했으며 후보 upstream의 `preserved_tokens` 입력 지원도 확인했다. 실제 후보의 실효 설정을 관측한 검증과는 구분한다.

완전한 비교 실행 도구는 아직 없다. 현재 ACL/고정 snapshot 재확인, 후보 server 수명·로그 제어, 실제 context/batch/threads/draft 관측, 원본 Gemma4 parser/인용 검증, 호출 수 제한을 연결해야 한다. 이 순수 함수만으로 기존 종료된 호출 예산을 다시 열거나 임의 후보를 운영 기본값으로 승격하지 않는다.

## 실행 검증 상태

서명된 standalone 후보의 모델 없는 `--version` 1회 probe를 준비하고 독립 리뷰 후 실행했다. 새 고정 경로·검토된 manifest/signature SHA·정확18파일/16PE 집합·파일 해시·reparse 거절을 검사했다. process-local 환경에는 후보 bundle/vendor/System32만 두고 모델·backend·proxy 환경을 상속하지 않았다. 10초·64KiB 상한, 전용 receipt, 자동 재시도0, 자기 소유 프로세스 kill/wait, 버전 숫자/commit·출력 해시만 보관하는 조건이었다.

2026-10-28T11:57:37Z에 native exit0·0.401799초·출력89bytes를 확인했다. 출력 SHA256은 `c132b03e598e3e53b8ffcea94fa7be2df228dad6728454eb44f9da5c2dc8fcb7`이다. 엄격한 버전 정규식에 맞는 줄이 없어 `versions=[]`이며 원문 출력은 저장하지 않았다. 따라서 **새 signed 실행 파일이 해당 명령에서 정상 종료한 것**만 확인됐고, 실제 build/commit 문자열·모델 로드·모든 동적 DLL의 허용·속도/품질은 미확인이다. 버전 정보를 더 얻기 위해 명령을 반복하지 않았다.

실행 후 정확 후보 경로의 잔여 프로세스0을 확인했다. 본래 Ollama serve PID29096과 시작 시각2026-10-15T00:25:40.2641220Z도 유지됐다. 새 모델·HTTP 서버는 시작하지 않았다.

## 검증·보존과 다음 작업

AI/인프라 후보 취득과 독립 호환성/프라이버시 검토를 분리했다. 최신 Ollama archive/PE 정적 일관성42항목, LM Studio 추출 경계19항목을 확인했다. 독립 리뷰의 ancestor 검사 지적은 `lstat`으로 수정하고 실제 조상을 다시 검사했다. 실제 취득에서 초기 네트워크 실패와 Ollama 다운로드 helper의 EOF 후 오류는 별도 영수증에 남겼다. 완전히 받은 Ollama ZIP의 전체 공식 SHA 일치를 확인한 뒤 파일 확정만 수행했으며 재다운로드·실행으로 대체하지 않았다.

버전 probe의 독립 mock17개는 정상·비0 종료, 출력 상한, timeout, pipe/프로세스/reader 시작 실패의 회수, clean environment, 로그 정제, 변조·중복 manifest, 재실행 차단을 검증했고 root 재실행도 통과했다. 실행 직전 코드 SHA256은 `24cc8d1c00c41eee1e357436271263da33531e4a417b6c96bfab0177ff766bfd`이며 Ruff·strict Mypy를 통과했다. 이 검증은 제품 RAG 회귀나 실제 답변 품질 검증이 아니다.

기존 설치13파일과 `.env`는 이전 SHA와 일치한다. 제품 코드·DB·프로파일 변경과 모델 호출은0이다. ISSUE-00038의 운영 정본 DB 갱신은 미완료이며 이 문서만으로 DB 저장을 주장하지 않는다.

상세 자료: `.local-data/project-agent-work/gemma-signed-runtime-20261028/`의 `candidate-findings.md`, `compat-review.md`, `compatibility-plan.md`, `preservation.json`, `version-probe-result.json`, `signed-runtime/`의 mapper/회귀, `review_mapper_tests.py`, `lmstudio-static/`의 취득/서명/PE manifest, `ollama-static/findings.md`. 성공·미확인·차단 기록을 구분해 보존하며 기존 차단 후보·4/4 ledger를 대체하지 않는다.

다음은 기존 직접 답변 입력의 template/설정 매핑과 비교 도구 검증 → 새로 승인된 제한 호출 안에서 첫 입력·반복·답변/인용 비교다. 비교 전까지 기본값 승격이나 속도 개선 완료를 선언하지 않는다.
