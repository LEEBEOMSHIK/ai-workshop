# Codex OS 격리 1차 실행기 검증

- 상태: 실행 차단된 초안 보존 승인 / 전체 Phase 1 미완료
- 설계: [OS 격리 대안](../superpowers/specs/2026-09-07-codex-os-isolation-design.md)
- 계획: [1차 실행기 구현](../superpowers/plans/2026-09-07-codex-os-isolation-probe.md)

## 범위와 승인

사용자는 전용 Windows 격리 프로필과 실험 폴더의 접근 권한 변경을 승인했다.
기존 사용자 계정, 개인 Codex 설정·인증, 방화벽, 인증서, Docker와 WSL은 변경하지 않는다.
실제 문서·질문·인증정보·모델 요청은 사용하지 않는다. 이 작업은 제품 Provider 연결이 아니다.

## 구현 환경

현재 main 작업 디렉터리에서 작업하며 기존 미커밋 기능·문서를 보존한다.
Windows에 설치된 .NET Framework C# 컴파일러를 발견했다. 별도 SDK나 런타임을 설치하지 않는다.
합성 실행 파일과 계약 테스트는 프로젝트 전용 임시 작업 디렉터리에서 빌드한다.
부모 디렉터리를 포함한 초기 조사에서 reparse point는 발견되지 않았으며 실제 변경 직전에 다시 검증한다.

## 확인된 실행 차단

계약 테스트의 수정 후 실행 파일 `ContractTests.exe`를 Windows가 실행 전에 차단했다.
일반 도구 실행과 별도 승인된 도구 샌드박스 밖 실행에서 동일하게 거부됐다.
2026-09-07 13:19–13:20 KST의 해당 실험 파일 Code Integrity 이벤트 3033·3077은
서명 수준 또는 코드 무결성 정책 위반을 명시한다. 앱의 테스트 실패나 LPAC 거부 결과가 아니다.
Smart App Control 관련 읽기 전용 레지스트리 값 `VerifiedAndReputablePolicyState`는 1이었다.
이벤트의 일반적인 Enterprise 서명 표현만으로 회사가 관리하는 PC라고 판단하지 않는다.

보안 정책을 끄거나, 인증서를 전역 등록하거나, 다른 로더로 차단을 우회하지 않았다.
AppContainer 생성·실험 폴더 ACL 변경은 아직 수행하지 않았다. 실제 Codex·모델 요청도 0건이다.
후속 실행에는 현재 코드 실행 정책이 승인하는 서명·실행 경로가 필요하다. 이 조건은 사용자가
승인한 전용 프로필·실험 폴더 권한 범위와 다르므로 임의로 변경하지 않는다.
서명된 코드에 관한 기준은 [Microsoft 공식 안내](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)를 참고한다.

## 판정 기준

| 검사 | 필요한 증거 | 현재 결과 |
|---|---|---|
| 입력·실행 파일 | 잘못된 hash, 경로, timeout을 실행 전에 거부 | 소스·계약 테스트 작성, GREEN 실행 차단 |
| LPAC·Job | 정지 상태에서 토큰·자식 제한·Job 검증 후 재개 | 컴파일만 확인, native 미실행 |
| 파일 | scratch 읽기·쓰기 성공과 별도 합성 보호 파일 거부 | label 소스 보완, 생성 직후 객체 소유권 문제 미해결 |
| 프로세스 | 자식 생성·외부 권한 handle·Job 이탈 거부 | 권한별 독립 검사 소스 보완, native 미실행 |
| 네트워크 | 호스트 양성 대조군, IPv4·IPv6·loopback의 명시적 거부 | loopback 소스만 작성, 비-loopback 미구현 |
| 수명주기 | timeout·취소·supervisor 종료 뒤 해당 프로세스 잔존 없음 | 종료 처리 소스 작성, 독립 lifecycle 실험 미구현 |
| 복구 | 이번 실행 소유 프로필·추가 ACE만 제거, 기존 권한 보존 | 원래 handle 기반 처리 보완, 생성 시점 소유권은 미해결 |
| CLI | 모든 합성 게이트 성공 후 인증 없는 호환성 검사 | 실행 금지 상태 |

프로그램이 시작되지 않거나 대조군이 실패하면 격리 성공으로 판단하지 않는다.
지원되지 않거나 수행하지 못한 검사는 미검증으로 남기며 RAG 생성 활성화 조건을 충족하지 않는다.

## 코드와 빌드 검증

소스는 [scripts/windows-isolation](../../scripts/windows-isolation/README.md)에 둔다.
앱 API·DB·화면에 연결하지 않으며 CLI 실행 모드를 제공하지 않는다.
실행기는 `run` 진입 직후 `native_run_disabled_ownership_lifecycle_unverified`로 차단된다.
프로필·ACL·label·작업 폴더·listener 생성 전에 멈추며 이 차단을 해제하는 옵션은 없다.
읽기 전용 `preflight` 소스는 유지한다. Canary도 합성 파일 접근 전에 자체 LPAC 상태와 경로를 검사한다.

구현 담당은 16개 계약의 의도한 실패(RED)를 관찰했다. 구현 후 GREEN 실행은 위 정책에 차단됐다.
메인 오케스트레이터도 아래 명령으로 세 실행 파일의 컴파일을 확인했다. 종료 코드 0이며
`/warnaserror+`를 사용했다. 이는 실행 검증이 아니다.

```powershell
./scripts/windows-isolation/build.ps1 `
  -ArtifactRoot C:/projects/ai-workshop/.local-data/project-agent-work/codex-os-isolation-probe `
  -BuildId mainfinal01 `
  -Compiler C:/Windows/Microsoft.NET/FrameworkArm64/v4.0.30319/csc.exe
```

초기 독립 리뷰는 Critical 0건, Important 3건을 보고했다. scratch의 Low integrity label,
ACL 변경·복구의 pinned 객체 동일성, 외부 프로세스 권한의 개별 거부 검사가 대상이다.
초기 수정 후 두 항목은 소스상 해결됐지만, 파일·디렉터리 생성에서 최초 handle 확보까지의
교체 가능 구간이 남았다. 검증할 수 없는 새 native API를 추가하며 진행하지 않고 실행을 잠갔다.
이 선택은 안전한 보존을 위한 것으로, 소유권 문제를 해결하거나 기능을 완료한 것이 아니다.

최종 독립 리뷰는 **비활성 초안 보존만 승인**했다. 전체 명세·네이티브 실행 판정은
`BLOCKED / INCOMPLETE`다. 재개에는 남은 객체 소유권 구현과 검증, 코드 실행 정책이 승인하는
서명·실행 경로, 전체 native 수명주기·네트워크 검사가 필요하다.

최종 계약 테스트는 22건이며 최초 RED16 이후 추가 6건과 수정 후 전체 GREEN은 미실행이다.
메인의 최종 `mainfinal01` 컴파일은 종료 코드 0이다. 실행 파일 크기는 Canary 19,968bytes,
ContractTests 20,480bytes, Supervisor 33,280bytes다. 테스트·native 실행 통과로 해석하지 않는다.

## 산출물과 보존

이번 임시 산출물은 `.local-data/project-agent-work/codex-os-isolation-probe/` 한 곳에 있다.
마감 조사에서 32파일, 738,067bytes였다. 이후 이 경로의 진행 기록 갱신으로 작은 차이가 날 수 있다.
실행 프로세스와 `run-*` 디렉터리는 없었다. 실패 재현용 산출물을 보존했으며 삭제하지 않았다.
새 SDK·런타임·모델을 다운로드하지 않았고 기존 프로젝트 캐시·원문·Docker는 변경하지 않았다.

## 근거

- [Microsoft AppContainer/LPAC 생성](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer)
- [프로세스 생성 속성](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
- [토큰 정보와 LPAC 확인](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ne-winnt-token_information_class)
- [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)

호스트 접근 제한과 원격 모델 서버의 도구 사용 통제는 다른 검증 대상이다.
1차 결과가 성공하더라도 통제된 인증·통신 검증 없이 실제 RAG 생성을 활성화하지 않는다.

## 후속 조사: 보안 정책을 유지하는 서명 경로

2026-09-07 사용자 승인에 따라 공식 문서와 현재 산출물의 서명 상태만 조사했다.
`mainfinal01/ContractTests.exe`의 Authenticode 상태는 `NotSigned`, signature type은 `None`이었다.
인증서·개인 키를 조회하거나 계정 가입·결제·바이너리 업로드·정책 변경을 수행하지 않았다.

| 경로 | 조사 결과와 적용 조건 |
|---|---|
| 신뢰된 RSA 코드 서명 | SAC 유지 조건에서 검토 가능한 공식 경로. 각 자체 실행 파일의 서명과 실제 장치 정책 수락을 확인해야 하며 격리 안전성을 증명하지는 않는다. |
| Azure Artifact Signing Public Trust | 공식 서비스 등록 문서에 한국 조직이 포함된다. 개인 개발자는 미국·캐나다로 제한되므로 신청 주체를 확인해야 한다. |
| 상용 CA 코드 서명 | 후보이나 한국 개인 발급, RSA·키 보관 장치의 Windows ARM64 지원과 최종 비용은 공급자별 확인이 필요하다. 지금 구매하지 않는다. |
| SignPath Foundation | 조건을 충족하는 공개 OSS에 무료 서명 제공. OSI 라이선스·공개 릴리스·관리 절차가 필요하며 현재 프로젝트의 적격성을 확인하지 않았다. 소스 공개 승인은 별도다. |
| Store MSIX | Store 인증 뒤 패키지 재서명 경로. 등록·패키징·심사·업로드가 필요하고 추출한 EXE 단독 실행의 보장은 아니므로 로컬 실험의 즉시 해결책으로 선택하지 않는다. |

Azure 가격 안내는 Basic 월 USD9.99/5,000서명, 초과 서명당 USD0.005다. 한국 조직 지원은
일반 Windows 안내의 과거 지역 목록과 다르므로 서비스별 등록 문서를 우선했고 실제 가입 적격성은
확인하지 않았다. 한국 개인에게 미국·캐나다 주소를 사용하도록 유도하지 않는다.
[등록 요건](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart),
[공식 가격](https://azure.microsoft.com/en-us/products/artifact-signing/).

일반 Microsoft 안내의 CA 가격 범위는 실제 견적이 아니다. 예를 들어 조사 시점 Sectigo 공식 FAQ는
5년 옵션 기준 연 USD536.25부터라고 표시한다. 단년 가격·배송·키 보관 비용과 한국 개인 발급을
확정한 것이 아니며 이 실험만을 위해 구매를 권장하지 않는다.
[Sectigo 공식 FAQ](https://www.sectigo.com/ssl-certificates-tls/code-signing).

자체 서명 인증서의 로컬 신뢰 등록을 SAC 해결책으로 제시하지 않는다. 신뢰 제공자 조건은
[Microsoft SAC 서명 안내](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)를 따른다.
OSS와 Store 조건은 [SignPath 공식 약관](https://signpath.org/terms.html)과
[Microsoft 배포 서명 안내](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options)를 확인했다.

독립 보안 검토는 신뢰된 서명을 조건부 실행 경로로 판단했으며 서명과 sandbox 안전성을 분리했다.
기존 Codex 바이너리의 서명이 자체 supervisor/canary에 적용되는 것은 아니다.
남은 객체 소유권·수명주기 결함은 서명 후에도 해결해야 하며 `run` 차단은 유지한다.

권고: 먼저 개인 또는 실제 조직 명의인지 확인한다. 적격 조직이면 Azure를 우선 후보로 검토하되
가입·결제·신원 확인은 별도 승인한다. 한국 개인이면 Azure를 기본 경로로 확정하지 않고 기존
코드 서명 보유 여부와 CA 발급 조건을 확인한다. 기존 인증서가 없다면 비용과 공개 여부 결정 전
유료 인증서·OSS 공개·새 실행 환경을 임의로 선택하지 않는다.

## 무과금 대안 검토와 백그라운드 실행 확인

후속 사용자 결정: 개인 학습·개발 프로젝트이며 추가 유료 서명 서비스를 사용하지 않는다.
위의 명의 확인·유료 서명 권고는 더 이상 활성 작업이 아니다.

읽기 전용 프로세스·포트 조사에서 Next.js의 5173(PID 25204), FastAPI의 18000(PID 7000)을
확인했고 각각 루트·health 응답은 HTTP 200이었다. Celery worker(PID 17332), beat(PID 12076)는
프로세스 존재만 확인했으며 작업 처리 성공을 새로 검증한 것은 아니다. 부모 Python 런처와 자식을
중복 서비스로 계산하지 않는다. Codex CLI·app-server·Node 도구와 IDE 터미널도 존재한다.
app-server 존재만으로 RAG Provider 연결 또는 모델 요청이 진행 중이라고 판단하지 않는다.
이전 하위 에이전트 세 개는 조사 시점 완료 상태였다. 자체 Supervisor·Canary·ContractTests와
pytest/vitest 실행은 관찰되지 않았다. 특정 UI 터미널 카드와 PID의 일대일 연결은 미확인이다.
프로세스 종료, 설치, 모델 요청, 인증·Windows 정책 변경은 하지 않았다.

검토 결과:

- 유료 서명은 Codex 연결 자체의 일반 필수 조건이 아니라 이번 자체 실행기의 Windows 정책 문제다.
  공식 [App Server](https://developers.openai.com/codex/app-server)는 제품 통합 인터페이스지만
  직접 호출 가능성과 기존 격리 계약 충족은 다르다. 기존 `run` 차단과 Provider 미연결 상태를 유지한다.
- 기존 `generation/openai_compatible.py`는 대화 이력·질문·검색 근거를 `/v1/chat/completions`에
  전송하고 구조화 결과를 검증한다. 이를 순수 로컬 추론 서버에 연결하는 경로는 별도 후보다.
- LM Studio는 공식 [Windows ARM 지원](https://lmstudio.ai/docs/app/system-requirements),
  [무료 로컬 실행](https://lmstudio.ai/pricing),
  [Chat Completions API](https://lmstudio.ai/docs/developer/openai-compat/chat-completions)를 안내한다.
  클라우드 크레딧·에이전트 도구·MCP 기능은 이 후보 범위에서 제외한다.
- 현재 adapter는 `json_object`를 요청하므로 공식 문서의
  [json_schema 구조화 출력](https://lmstudio.ai/docs/developer/openai-compat/structured-output)과
  동일하다고 가정하지 않는다. 실제 모델·서버 버전별 계약 검증 또는 승인된 adapter 조정이 필요하다.
- 소프트웨어의 무료 로컬 경로가 모델 라이선스·장치 메모리·디스크 비용, 실제 Windows 실행 허용,
  답변·인용 품질을 보장하지 않는다. 아직 모델 선정·다운로드·실제 실행을 검증하지 않았다.
  로컬 바인딩·허용 endpoint·요청/로그 보호도 확인해야 한다. Codex에서 이 후보로 임의 전환하지 않는다.

다음 판단은 Codex 경로 유지와 별도 로컬 추론 후보 채택을 구분해 사용자에게 제시하는 것이다.
개인/조직 명의를 다시 묻거나 유료 인증서 구매를 요구하지 않는다.

독립 보안 검토는 사전 타당성 후보에 동의했으며 구현·실행·보안 완료 승인은 하지 않았다.
도구 없는 요청과 서버 전체의 도구 기능 부재를 구분하고 tools·integrations·도구 실행 루프 및
서버 MCP 설정을 확인해야 한다. loopback·LAN 공유·인증·CORS·프록시·로그/본문 보존도 검증 대상이다.
이 후보는 기존 OS 격리를 완성하는 방식이 아니라 신뢰하는 로컬 추론 서버에 일반 요청을 보내는
다른 실행 방식이다. 모델 출력은 비신뢰 데이터로 취급하고 기존 인용 검증·실패 차단을 유지한다.
