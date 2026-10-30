# Gemma 성능 후속: GPU 경로와 ARM CPU 빌드

상태: **원인 조사와 후보 준비 완료, GPU 후보는 Windows 정책 차단으로 보류. 실제 속도 개선은 미완료.** 관련 ISSUE-00038. 사용자의 “개선 진행해봐”에 따라 [직전 스레드 비교](2026-10-28-gemma-runtime-prefill-diagnosis.md)에서 남은 GPU·메모리 원인을 조사했다. 이번 모델 호출은0회이며, 종료된 이전4/4회 예산을 재사용하지 않았다.

## 확인한 런타임 문제

현재 장치의 ARM64 프로세스에서 Windows `IsProcessorFeaturePresent`로 Dot Product(43), NEON INT8 matrix multiply(66), FP16(67) 지원을 확인했다. 모두 true다. [Microsoft API 정의](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-isprocessorfeaturepresent).

반면 현재 설치된 `ggml-cpu.dll`을 실행 없이 읽어 COFF symbol과 PE export table의 함수 위치를 각각 대조하니, 해당 기능의 보고 함수는 모두 정수0을 반환하도록 컴파일돼 있다. Q4_K 8x4/8x8 GEMV·GEMM의 네 진입점도 각각 generic 구현으로 직접 분기한다. NEON/FMA와 llamafile은 포함돼 있으므로 CPU 전체가 scalar로 동작한다는 뜻은 아니다.

| 기능 | 현재 장치의 Windows 보고 | 설치 CPU DLL의 컴파일 지원 |
| --- | --- | --- |
| ARM Dot Product | 지원 | 없음 |
| ARM INT8 matrix multiply | 지원 | 없음 |
| ARM FP16 vector arithmetic | 지원 | 없음 |

설치 DLL SHA256은 `01cc56ca2b44c3c4f0a3bc7362f1c78e51375efbc995b3deabcdaaa2eeee5c4f`다. dotprod·matmul_int8 함수의 파일 offset21468·21484에서 `E0 03 1F 2A C0 03 5F D6`(`mov w0,wzr; ret`)를 확인했다. 같은 upstream 버전의 별도 패키지 CPU DLL에서는 두 기능이1로 컴파일돼 있어 빌드 차이가 실재한다. 이 기능 판정은 DLL 바이트의 정적 분석이며, 해당 함수를 호출해 검증하거나 기존 DLL을 교체한 것은 아니다. 아래의 실패한 장치 열거·버전 확인 과정에서 이 DLL이 로드되지 않았다고 단정하지도 않는다.

고정 소스의 [기능 조건](https://github.com/ggml-org/llama.cpp/blob/631109b34da437a3c4a5ebd75091d677671392e3/ggml/src/ggml-cpu/ggml-cpu.c)과 [Q4_K repack 선택](https://github.com/ggml-org/llama.cpp/blob/631109b34da437a3c4a5ebd75091d677671392e3/ggml/src/ggml-cpu/repack.cpp)은 이 두 기능에 따라 최적화 경로를 선택한다. **현재 CPU 빌드의 가속 기능 누락은 확인됐지만, 입력 처리131초 중 정확히 몇 초를 설명하는지는 미측정**이다. 실제 tensor별 호출 경로도 프로파일링하지 않았다.

Ollama v0.40.3의 Windows ARM preset은 NATIVE/ALL_VARIANTS를 끈 MinGW 빌드다. 조사 시점 최신 v0.40.12의 [고정 preset](https://github.com/ollama/ollama/blob/v0.40.12/llama/server/CMakePresets.json)도 이 부분이 같아서 버전만 올리면 해결된다고 볼 근거가 없다. 최신 배포 DLL 자체는 검사하지 않았고 업데이트하지 않았다.

## GPU 후보 준비와 실제 차단

OS의 Vulkan 장치 열거는 Qualcomm Adreno X2-45 네이티브 장치를 확인했다. 그러나 설치된 Ollama runner의 `--list-devices` 결과는 `(none)`이며, 설치 트리에는 해당 GPU용 GGML OpenCL/Vulkan backend가 없다. OS loader나 GPU가 존재하는 것과 모델 실행기가 가속할 수 있는 것은 구분한다. [Ollama v0.40.3 Windows ARM 지원 범위](https://github.com/ollama/ollama/blob/v0.40.3/docs/development.md).

같은 소스 commit `631109b34da437a3c4a5ebd75091d677671392e3`의 [공식 b11351 ARM64 OpenCL Adreno ZIP](https://github.com/ggml-org/llama.cpp/releases/expanded_assets/b11351)을 작업 폴더에만 준비했다.

- 다운로드12,935,302bytes, SHA256 `d1e9939f20d304018f143b442b1d4d128fd386ea6db23b12c8ee45877400900b` 일치.
- `gh attestation verify`에 공식 repo·release workflow·source commit·self-hosted 금지를 지정한 검증 명령 종료코드0. [공식 attestation](https://github.com/ggml-org/llama.cpp/attestations/52254232).
- 새 폴더에39파일29,861,661bytes를 배타적으로 추출하고 경로 이탈·덮어쓰기·링크·파일 해시를 검사했다. PE38개 모두 ARM64다.
- 기존 runner에 외부 OpenCL DLL을 새 진단 프로세스에서만 지정한 장치 열거는 종료0이나 출력이 비었다. **GPU 인식·ABI 호환 성공으로 판정하지 않는다.**
- upstream portable의 장치 열거와 후속 버전 확인은 `0xC0E90002`로 실패했다. 모델·서버를 실행하는 인자는 사용하지 않았다.

이번 후보 경로에 정확히 일치하는 Windows Code Integrity3033/3077 이벤트에서09:37:33UTC의 `llama-server-impl.dll`,09:38:13UTC의 `llama-common.dll` 차단을 확인했다. Smart App Control 상태는1이다. 후보 exe/OpenCL DLL의 Authenticode는NotSigned, 기존 Ollama runner는Valid다. GitHub 출처 검증과 Windows 실행 허용 서명은 다른 검사다.

보안 정책 변경, 예외 등록, DLL 덮어쓰기, 드라이버 설치, 서비스 교체 또는 다른 경로를 통한 차단 우회는 하지 않았다. 해당 후보의 추가 실행을 중단하고 진단 진입점에 종료 기록 검사를 넣었다. **현재 필요한 것은 정책을 통과하는 서명된 ARM 최적화 런타임과 Ollama/Gemma4 호환성 검증**이다. upstream runner는 Ollama의 Gemma4 tokenizer/projector compatibility 처리를 그대로 제공한다고 가정할 수 없다. [호환성 구현](https://github.com/ollama/ollama/blob/v0.40.3/llama/compat/README.md).

## 메모리 조사와 보류한 대안

유휴 가용 메모리는 당시 약2.71GiB였다. 프로젝트 컨테이너는 Elasticsearch1.605GiB, PostgreSQL118MiB, Redis9.98MiB였으며 큰 상주 native embedding 프로세스는 관측하지 못했다. 코드에서도 생성 전 임베딩 모델 참조 해제를 확인했다. 참조 해제가 OS working set의 즉시 반환을 보장하지는 않는다.

GGUF 헤더의35층 중 shared-KV20층과 attention 차원을 확인했다. FP16·독립 full-attention 층 수 가정에 따라16K→8K의 해당 KV 절감 계산은48~112MiB다. 이는 **전체 할당 절감의 측정값이나 상한이 아니며**, 관측 private memory 약6GiB가 절반이 된다는 뜻도 아니다. 과거11,017토큰 입력 때문에16K를 선택한 기록이 있어 일반 기본값을8K로 낮추지 않는다. 이번에는 효과 근거가 약한 문맥 축소·추가 스레드 숫자 실험을 수행하지 않았다.

다른 앱 종료, WSL/Elasticsearch 메모리 설정 변경, 모델·프로젝터 제거, 원문·출력 한도 축소도 수행하지 않았다. 메모리 압박은 관측됐으나 개별 원인 비중은 여전히 분리되지 않았다.

## 검증·보존·남은 경계

AI·인프라 조사와 독립 리뷰/프라이버시 검토를 분리했다. 독립 검토에서 ZIP 추출의 오프라인14항목, 실제 archive/manifest/PE와 기존 설치13파일 해시 보존을 확인했다. 장치 probe는 리뷰 완료 전에 실행됐다. 이후 발견된 출력 상한의 사후 검사·원문 줄 기반 로그 정제 문제는 기록을 지우지 않고 보강했으며, 원래 실행의 두 stdout은 모두 비어 유출 증거가 없었다. 보강본의 실제 native 실행은 하지 않는다.

보강본의 독립 mock11개는 출력 상한·시간 초과·자식 종료/회수·오류 정제·구조화된 장치 필드·종료 gate를 확인했고 최종 코드에서도 통과했다. 진단2파일 Ruff·범위 Mypy 통과, CPU 정적13항목도 독립 대조했다. 기존 Ollama PID29096과 원래 시작 시각, .env와 이전 두 실측 ledger SHA를 재확인했다. 제품 코드가 바뀌지 않아 제품 전체 회귀나 실제 모델 품질 검증으로 확대하지 않는다.

제품·프로파일·기본 연결·모델·원문·입출력 예산·기존 서비스·보안 정책을 변경하지 않았다. 따라서 이번 작업으로 답변 품질을 새로 통과했거나 속도를 개선했다고 보고하지 않는다. 기존 일반 지급 규칙 누락·정답0/2는 그대로다. 운영 정본 ISSUE-00038 DB 갱신은 미완료이며 로컬 기록만 저장했다.

후속 순서는 서명된 ARM Dot Product/i8mm 또는 Adreno backend 확보 → Ollama/Gemma4 호환성·원문 입력 동등 확인 → 별도 승인된 제한 호출로 입력 처리·메모리·답변·인용 비교다. 이 조건 전에는 현재 후보를 운영에 적용하거나 실모델 호출을 재개하지 않는다.

상세 자료는 `.local-data/project-agent-work/gemma-gpu-memory-20261028/`의 `gpu-findings.md`, `memory-findings.md`, `cpu-os-features.json`, `portable-manifest.json`, `backend-device-probe.json`, `backend-blocked.json`, `review-notes.md`다. 모델 입력·출력 원문과 전체 환경/명령은 이 자료에 저장하지 않는다.
