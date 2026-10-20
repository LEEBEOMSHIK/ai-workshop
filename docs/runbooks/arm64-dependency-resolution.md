# 종료된 조사 이력: ARM64 의존성 해결 계획과 승인 경계

> 현재 상태(2026-10-12): **AMD64 유지, ARM64 전환 취소 및 실험 환경 정리.**
> 사용자의 명시적 취소에 따라 아래 ARM64 전환·의존성 해결·OCR 분리 제안과 후속 검증은
> 종료된 조사 이력으로 보존하며 진행 중 계획이나 실행 승인 요청으로 취급하지 않는다.
> 기존 AMD64·Gemma 제품 코드·서비스는 유지한다. 정리 결과는 비교 작업 기록의 마지막 절을 따른다.

- 조사일: 2026-10-12. **조사 결과이며 승인된 구조 변경·설치·전환 절차가 아니다.**
- 전체 수용 기준은 [38개 기능 검증표](arm64-feature-parity.md), 기존 실행 정본은
  [로컬 개발 실행서](local-development.md)를 유지한다. AMD64는 그대로 보존한다.
- 이번에는 공식 메타데이터, 기존 로그, 현재 자원만 확인했다. 패키지 설치·빌드·
  native import·모델 다운로드/추론·DB/서비스 변경을 실행하지 않았다.

## 공식 지원과 프로젝트 적용 가능성

| 항목 | 확인한 사실 | 최소 변경과 한계 |
| --- | --- | --- |
| cryptography 50.0.1 / 50.0.2 | 두 버전의 공식 PyPI 파일에 Windows ARM64 wheel이 없다. 50.0.1 sdist는 880,381바이트. Linux aarch64 abi3 wheel은 있다 | 프로젝트 `>=50.0.1,<51`을 유지한 자체 Windows ARM64 소스 빌드가 후보. 상위 버전 재설치만으로 해결되지 않는다 |
| cryptography의 Windows ARM64 지원 | PR14216의 2026-01-27 지원 철회 후 **PR15350이 2026-09-02 지원 복원을 병합**했다. maintainer는51부터 wheel 재개 예정이라고 명시. 이번 PyPI 최신은50.0.2이고51 릴리스 목록은 비어 있다 | 우선51 공식 릴리스와 실제 wheel을 확인하고 현재 `<51` 제약 변경을 검토. 50.x 자체 빌드는 별도 유지보수 책임이 필요. 이전46.x로 내리지 않는다 |
| PaddlePaddle 3.2.2 | Windows ARM64 wheel·PyPI sdist 없음. **cp313-cp313-manylinux2014_aarch64** 공식 wheel은 88,143,036바이트 | Python3.13 및 현재 엔진 pin을 유지하는 Linux ARM64 OCR 실행 후보. Linux에서의 설치·실행은 이번에 검증하지 않았다 |
| PaddlePaddle 3.3.1 | Windows ARM64 wheel 없음. 현재 exact pin 밖 | 업그레이드만으로 Windows ARM64 공백이 해결되지 않는다 |
| Paddle Windows 소스 빌드 | 공식 문서의 Native Tools 및 CMake 예시는 x64. Windows ARM64 빌드 지원을 확인할 수 없다 | CMake `-A ARM64`만 바꾸는 것을 해결 계획으로 간주하지 않는다. 포팅 작업의 성공·용량·일정은 미확정 |
| PaddleOCR3.7.0 / PaddleX3.7.2 | 기존 어댑터는 PPStructureV3의 본문·표·좌표·신뢰도 출력을 사용 | generic Python wheel은 엔진을 공급하지 않는다. 단순 OCR/Paddle Lite/ONNX로 바꾸면 동등성 재설계·모델/품질 검증이 필요 |

버전/파일 근거: [cryptography50.0.1](https://pypi.org/pypi/cryptography/50.0.1/json),
[50.0.2](https://pypi.org/pypi/cryptography/50.0.2/json),
[Paddle3.2.2](https://pypi.org/pypi/paddlepaddle/3.2.2/json),
[3.3.1](https://pypi.org/pypi/paddlepaddle/3.3.1/json).
지원 판단: [cryptography 지원 철회](https://github.com/pyca/cryptography/pull/14216),
[지원 복원·51 배포 계획](https://github.com/pyca/cryptography/pull/15350),
[현재 PyPI 릴리스](https://pypi.org/pypi/cryptography/json),
[버전별 소스 빌드 지침](https://cryptography.io/en/50.0.1/installation/),
[Paddle Windows 빌드](https://www.paddlepaddle.org.cn/documentation/docs/en/install/compile/windows-compile_en.html).
파일 목록과 크기는 이번에 다시 조회해 보존했다. 오래된 이슈의 closed 상태만으로
현재 지원을 판단하지 않았다. 모델 파일 크기는 조사·다운로드하지 않았다.

## 종료된 조사 당시 제안: Windows ARM64 본체 + 로컬 Linux ARM64 OCR

현재 공식 배포만으로 **순수 Windows ARM64 전체 기능 경로는 확인되지 않았다.**
전체 기능을 유지하며 진행하려면 Windows 보호 기능을 유지하는 본체와, 공식 엔진이
있는 Linux ARM64 OCR 실행을 분리하는 경로를 우선 설계·검증하는 것을 추천한다.
이는 확정 설계가 아니라 다음 승인 대상이며, 단계별 실패 시 AMD64 운영을 유지한다.
모든 구성요소가 ARM64여도 Windows 단일 OS 구성과는 다르므로 수용 범위 합의가 필요하다.

1. **정책 판정 선행:** 차단된 sklearn은 같은 파일·환경에서 정책 소유자의 정상 신뢰
   검토를 먼저 받는다. 다른 환경으로 sklearn/Gemma를 옮겨 정책 차단을 피하지 않는다.
   부적합 판정이면 해당 실행은 중단 상태를 유지한다.
2. **cryptography 공급 검증:** 우선51의 공식 릴리스·win_arm64 wheel 존재, Python3.13
   ABI·보안 변경·X.509/API 호환성을 확인한 뒤 `>=50.0.1,<51` 제약과 lock 변경을
   별도로 승인받는다. 아직 배포되지 않아 설치할 수 없고 출시일도 확정하지 않는다.
   개발 branch/비공식 wheel을 대신 설치하지 않는다. **지금 시스템 빌드 도구 설치는
   추천하지 않는다.** 출시를 기다릴 수 없는 경우에만 50.x 자체 빌드 실험을 별도로
   승인받을 수 있으며, 기존50.0.1을 대상으로 MSVC ARM64 C++/Windows SDK,
   Rust(해당 버전 문서 최소1.83), ARM64 OpenSSL 및 빌드 도구를 갖춘 승인된 빌더에서
   재현 가능한 wheel을 만든다. 공식 소스 hash·도구 버전·OpenSSL 버전·wheel hash·
   PE 아키텍처·의존 DLL을 기록한다. `OPENSSL_DIR` 등은 자식 빌드 환경에만 지정한다.
   공식 OpenSSL의 `VC-WIN64-ARM` 경로에는 MSVC와 Perl 등이 필요하다. 실제 선택한
   OpenSSL 태그의 도구 요구를 고정하고 빌더 안에서만 설치한다.
   빌드 성공 후에도 조직의 산출물 신뢰 검토를 통과해야 실행한다. X.509/서명/해시,
   프로젝트 보호 경계 테스트와 전체 API/worker import를 통과해야 사용할 수 있다.
   50.x 자체 빌드의 유지보수나51의 제약 변경이 승인되지 않으면 이 단계에서 멈춘다.
3. **OCR 경계 설계:** `PaddleStructureV3Adapter`의 입력·출력 계약을 유지하며 OCR 계산만
   로컬 Linux ARM64의 Python3.13/Paddle3.2.2로 전달하는 어댑터를 설계한다. DB, 사용자
   계정, 권한 판정, 원본 보관, DPAPI/DACL, Windows Job·복구 기능은 Windows에 남긴다.
   별도 마이크로서비스 전환을 기본값으로 삼지 않고 로컬 수명주기 관리 프로세스로 제한한다.
   승인 전에 ADR·시스템 설계·RAG 설계에 전달 범위, 인증, 요청 한도, 임시 파일 권한,
   취소/timeout 시 Linux 자식 종료 증거, 재시도·부분 실패를 구체화한다. Windows Job만으로
   Linux 자식 종료가 보장된다고 가정하지 않는다. 새 DB/계정과 운영 데이터 복제는 금지한다.
4. **격리 증명 후 통합:** 승인된 로컬 ARM64 Linux 대상에서 모델 없는 의존성 검증부터
   수행한다. WSL이 존재하더라도 배포판·CPU·자원·보호 상태를 확인하지 않고 사용하지 않는다.
   기존 Docker/WSL 설정 및 공유 자원을 바꾸지 않는다. 이후 별도 승인된 모델·공개 합성
   PDF/DOCX로 본문·표·좌표·신뢰도·실패·취소를 비교한다. OCR 구현 생략은 허용하지 않는다.
5. **전체 검증·인계:** libpq와 나머지 native 패키지, frontend build/start, 전체 기능표의
   API/worker/DB/Redis/ES·권한·취소·복구를 검증한다. 기존 RAG 미완료와 이식 회귀를
   따로 기록한다. 본래 환경 반영·rollback 검증 이전에는 AMD64를 삭제하지 않는다.

취소 전 조사에서 제안했던 승인 단위는 **A의 정상 신뢰 검토와 B의 구조 설계**다. C의
설치·소스 빌드는51 공식 wheel 경로가 불가능하고 자체 유지보수를 수용할 때에만
검토한다. D의 실제 환경 생성·설치는 B 승인 후 정확한 대상·용량을 확정해 승인받는다.

전체 backend를 Linux로 옮기는 대안은 Windows DPAPI/DACL/Job 및 복구 경계를 다시
구현해야 하므로 최소 변경이 아니다. Windows Paddle 자체 포팅은 지원 근거가 부족하여
우선 경로로 선택하지 않았다. 추천 경로도 crypto·정책·OCR 경계 중 하나라도 통과하지
못하면 전체 전환을 완료할 수 없다.

OCR 경계의 상세 계약과 다음 실행 승인 단위는 [로컬 ARM64 OCR 설계 초안](../superpowers/specs/2026-10-12-local-arm64-ocr-design.md)을 정본으로 참조한다. 2026-10-12 사용자 승인은 **설계 작성**까지이며 B의 구조 구현·C/D 설치·E 통합 승인은 아니다. Docker 읽기 접근 거부로 실제 Linux 환경은 확정하지 않았다.

## 정확한 승인 대상, 자원과 영향

아래 예상치는 **설계 예산**이며 설치 측정치나 제품 최소 요구사항이 아니다.
현재 C: 여유는 조회 시 약113GiB였으며, 충분한 디스크가 여유 RAM을 대체하지 않는다.

| 승인 단위 | 구체적 범위 | 자원·권한·영향 |
| --- | --- | --- |
| A. 신뢰 검토 | 정확한 sklearn 파일/wheel hash와 기존3033/3077·Policy ID를 정책 소유자가 판정 | 로그 읽기와 검토. 이번 요청은 허용 규칙 추가/정책 완화 승인이 아님. 후속 조치는 관리자 소유 변경 절차 필요 |
| B. 구조/유지보수 합의 | Windows ARM64 본체 + 로컬 Linux ARM64 OCR 수용. crypto51 공식 배포 후 제약/lock 호환성 검토; 자체50.x 빌드는 예외 승인 | 먼저 ADR와 어댑터 계약 작성·리뷰. 제품 코드·OS·런타임 변경 승인은 별도. 순수 Windows만 요구하면 전환 보류 |
| C. 조건부 전용 crypto 빌더(현재 비추천) | MSVC ARM64 C++/Windows SDK + Rust + OpenSSL/Perl, hash 고정 source build·테스트·산출물 신뢰 검토 | 우선 기존 승인 빌더 사용. 없으면 도구 설치 관리자 승인 필요. **디스크30GiB, 여유RAM8GiB**를 임시 예산으로 잡고 정확한 설치 구성/다운로드 크기 확정 후 실행 승인. 기존 서비스 머신 전역 PATH/공유 Python 수정 제외 |
| D. 로컬 OCR 검증 환경 | 승인된 ARM64 Linux에서 Python3.13와 현재 OCR exact pin의 모델 없는 의존성 확인 | **추가 디스크10GiB·RAM4GiB·2CPU** 초기 예산, 모델 제외. 실제 전체 의존성/이미지 크기 사전 산정. WSL 설치/기능 활성화/재부팅, Docker 설정 변경은 이번에 승인·실행하지 않음 |
| E. 실제 통합 | 기존 권한·자료를 보존한 합성 OCR/서비스 왕복·취소·복구 및 운영 반영 | 모델·DB/Redis/ES 연결·service lifecycle·rollback 대상을 지정한 별도 승인 필요. C/D만 승인해도 운영 전환은 불가 |

MSVC 제품군의 설치 크기는 선택 구성에 따라 크게 달라진다. Microsoft 일반 안내의
20–50GB는 위 최소 C++ 구성의 실측이 아니다. 관리자 설치 요구와 지원 OS는
[Microsoft 시스템 요구사항](https://learn.microsoft.com/en-us/visualstudio/releases/2022/system-requirements),
OpenSSL ARM 빌드 대상은 [공식 소스 지침](https://raw.githubusercontent.com/openssl/openssl/openssl-3.5/NOTES-WINDOWS.md)을 참고한다.

## DLL 정책: 확인한 범위와 관리 절차

기존 로그의3033와3077는 같은 `_cyutility.cp313-win_arm64.pyd` 및 Python 프로세스에
대해 Enterprise signing level / Code Integrity 정책 위반을 기록한다. Policy ID는
`{0283ac0f-fff1-49ae-ada1-8a933130cad6}`다. Microsoft 정의상3077는 enforced App Control
차단이며3033만으로 특정 원인이나 제품을 단정할 수 없다. 이것만으로 조직 WDAC,
Smart App Control, 정책 배포 주체나 승인 가능 여부를 확정하지 않는다.
이번3099 정책 로드 이벤트 조회는 해당 ID 필터를 적용하기 전부터 일치 이벤트가 없어
추가 식별 근거를 얻지 못했다. 로그 부재는 정책 부재를 뜻하지 않는다.

정책 소유자에게 기존 이벤트·시간·정확한 파일/프로세스 경로·공식 wheel/파일 hash를
인계하고, 정상 관리 도구에서 정책 ID와 배포 주체를 확인하도록 한다. 필요 시 같은
Correlation ActivityID의3089 서명 근거를 관리자가 확인한다. 프로젝트가 임의로
서명/허용 규칙을 추가하거나 정책·ISG·보호 기능을 끄는 조치는 포함하지 않는다.
[Microsoft 이벤트 정의](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/operations/event-id-explanations).

## 프론트 OOM 재시도 판단

이전 빌드는 V8 old-space512MiB, Job 메모리768MiB 설정에서26.543초 만에 OOM 실패했다.
Job peak917,667,840바이트는 설정 상한과 다르며 완벽한 hard-cap 증거로 쓰지 않는다.
Vitest 종료 후 빌드했으므로 해당 테스트와 빌드의 동시 실행이 원인이라는 근거는 없다.
당시 전체 프로세스 메모리 시계열은 없으므로 다른 앱의 기여량도 소급 확정할 수 없다.

이번 실제 조회: 물리 메모리24,646,392KiB 중 여유1,715,524KiB(약1.64GiB),
가상 메모리 여유6,666,648KiB. 현재 동시 앱에는 IDE·ChatGPT/Codex·Unity·vmmemWSL이
있지만 이 순간의 working set을 과거 실패 원인이나 종료 허가로 해석하지 않는다.
**지금 재시도하지 않는다.** 동일 제한 반복은 정보가 적고, 상한 증대는 여유 RAM에 비해 크다.

사용자가 작업을 마친 뒤 자연스럽게 자원이 확보된 별도 시간에, 예를 들어 여유 물리
RAM6GiB 이상·여유 commit8GiB 이상을 확인하고 단일 build를 고려한다. 이는 보수적인
시작 기준이지 성공 보장이 아니다. V8 old-space2GiB·소유 Job3GiB·600초의 1회 예산과
전체 메모리 감시(여유2GiB 미만이면 해당 빌드만 종료)를 먼저 정하고, wrapper의 Job
할당·제한·측정을 검증한다. 기존 앱/서비스 종료, pagefile 변경은 포함하지 않는다.
원본과 같은 Next/Turbopack 설정을 유지하고 실패하면 상한을 반복 증대하지 않는다.

## 실행 증거

이번 공식 PyPI JSON 조회, 기존 Code Integrity 로그 판독, 현재 RAM/프로세스 working
set/디스크 조회를 수행했다. sandbox의 네트워크/CIM 읽기 제한은 승인된 좁은 읽기
요청으로 처리했으며 Windows DLL 차단은 재실행하지 않았다. 제품 테스트 신규 실행0.
과거 프론트968/백엔드126 통과는 [기존 기록](../worklogs/2026-10-12-arm64-environment-comparison.md)을 그대로 유지한다.
원자료: `.local-data/project-agent-work/arm64-resolution-20261012/`.
