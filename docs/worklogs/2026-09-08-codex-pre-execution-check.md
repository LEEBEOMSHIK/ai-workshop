# Codex 호출 직전 경계 검사

- 날짜: 2026-09-08
- 요청: 다음 검사 진행. 코드 변경·Provider 활성화가 아닌 읽기 전용 검토와 기존 합성 테스트 재실행.
- 작업 위치: main. 역할: 메인 AI 실행 경계 점검, 독립 보안·프라이버시 검토.
- 실제 CLI·인증·외부 모델·사용자 DB·문서·서버 설정은 변경하거나 호출하지 않았다.

## 확인한 경계

| 항목 | 현재 상태 | 활성화 전 필요한 것 |
| --- | --- | --- |
| 실행 설정 | Deployment의 runner_ref 저장·검증 가능. config.py에는 HTTP endpoint/secret registry만 존재 | 허용 실행 파일·검증 버전·전용 임시 루트·환경·예산을 해석하는 typed runner registry |
| 실행 차단 | 등록 서비스·runtime resolver·readiness에서 Codex 차단 | 검증 완료 전 차단 유지. enum 추가만으로 실행 허용하지 않기 |
| 권한·전송 정책 | 검색 범위 선검사·현재 정책·정확한 외부 승인 버전 비교 및 정책 DB 잠금 존재 | 각 contextualize/generate 직전 최신 owner·전체 공간·요청/단계·실제 payload에 결합한 실행 허가 |
| 입력 승인 | AssetVersion의 UUID/SHA-256과 근거 asset_version_id 존재 | 공개/합성 revision 승인 출처와 질문·제한 이력·지침까지 포함한 전송 승인 |
| 출력 감시 | Windows 프로세스 수명주기와 JSONL 수신기 각각 구현 | 실행 중 stdout chunk를 수신기에 전달하고 금지 이벤트 즉시 해당 요청 프로세스 중단·회수 |
| 모델 확인 | CodexEventResult.observed_model은 None | 실제 모델 확인 증거. 요청한 gpt-5.5를 관측된 모델로 복사하지 않기 |

## 코드 근거와 접합 주의

- `generation/windows_process.py`: 파일 설명에 authorization/registry/임시 디렉터리 정책이
  호출자 책임임을 명시한다. run은 완료 후 ProcessResult의 bounded stdout/stderr를 반환한다.
  `generation/codex_events.py`의 feed는 독립 수신기이며 현재 production 호출부와 연결되지 않았다.
  프로세스 종료 후에만 feed하면 금지 이벤트의 실행 중 중단 요건을 충족하지 못한다.
  현재 비활성 기능의 노출 취약점이 아니라 후속 adapter의 필수 접합 요건이다.
- `search/service.py::_prepare_generation`은 정책과 정확한 외부 승인 버전을 확인한다.
  `policies/repository.py::lock_external_execution_policy`는 FOR SHARE 잠금으로 정책 변경과 실행을 순서화한다.
  이 기존 보장을 무시하고 정책 단순 재조회만 추가하지 않는다.
- 동일 search service의 `configuration.generation_runtime` 직접 주입 분기는 resolver를 거치지 않는다.
  현재 production 코드에서 그 값을 할당하는 연결은 찾지 못했다. 향후 resolver만 검사하고
  내부 실행·평가·연결 검사 경로를 제외하면 안 된다. 실제 spawn 직전 공통 경계로 묶어야 한다.
- `generation/domain.py`의 ContextualizationRequest/GenerationRequest에는 actor나 실행 허가가 없다.
  `search/configuration_port.py::ResolvedExternalApproval`에는 승인 ID·승인자·시각이 전달되지 않는다.
  기존 policy allowed 또는 UI 동의 boolean만으로 Codex 전체 실행 승인을 대체할 수 없다.
- `platform/assets/domain.py::AssetVersion`의 SHA-256은 내용 식별값이다. 공개/합성 자료라는 승인 자체는 아니다.

## 실제 검증

```powershell
# backend에서 합성 테스트 설정만 현재 테스트 프로세스에 제공
$env:AI_WORKSHOP_SECRET_KEY = ('offline-test-' * 4)
.venv/Scripts/python.exe -m pytest tests/unit/labs/rag/deployments tests/unit/labs/rag/generation tests/unit/labs/rag/policies tests/unit/labs/rag/search/test_generation_policy_gate.py -q
```

결과: **324 passed, 1 warning, 9.05초**, exit 0. 기존 Starlette/httpx deprecation 경고다.
Windows 실행기 테스트는 합성 Python 자식만 실행했으며 실제 모델·계정은 사용하지 않았다.
이 결과는 현재 개별 부품·차단·HTTP 정책 회귀 검증이며 미구현 Codex 실행 허가 검사 통과가 아니다.

독립 보안·프라이버시 검토도 같은 결론이다. 일반 검색은 로그인 사용자 경로이고 평가 worker는
저장된 owner_id로 실행하므로, 관리자 등록 권한이나 과거 owner 기록을 최신 실행 권한으로 간주하면 안 된다.
연결 검사의 기존 빈 공간 정책/health 경로도 실제 합성 호출 허가를 대신하지 않는다.
활성화된 Codex 노출 취약점은 확인하지 않았으며 현재 차단을 유지한다.

## 다음 구현 범위

1. typed runner registry와 호출별 실행 허가 계약을 정의하고 실패 테스트부터 구현한다.
2. 현재 owner·모든 공간·정확한 구성/정책/Deployment/지침 버전·입력 revision 승인과
   실제 직렬화 전송 내용의 digest를 묶는다. 양쪽 생성 단계·평가·명시 연결 검사에 동일 적용한다.
3. stdout 실시간 감시 → 금지 이벤트 취소 → 프로세스 회수 → 결과 폐기를 접합한다.
4. 실제 모델 확인 증거와 명시 합성 연결 검증이 완료되기 전 readiness를 승격하지 않는다.

기존 상세 승인 설계는 변경하지 않았다. 실제 사용자 DB migration·관리자 UI 활성화·RAG 전체
테스트 요청은 이 검사 완료와 구분한다. 기존 0026 Workspace-only downgrade 테스트 공백도 이번에 수정하지 않았다.
