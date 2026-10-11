# RAG 별칭 복구 사전검사·관찰 중복 제거와 본래 검증

- 날짜: 2026-10-01
- 문제: ISSUE-00013
- 계약: [사전검사 설계](../superpowers/specs/2026-10-01-rag-alias-preflight-design.md), [구현 계획](../superpowers/plans/2026-10-01-rag-alias-preflight.md), [ADR-0032](../decisions/0032-rag-alias-recovery.md)
- 결과: 사전검사 기능 구현·회귀·독립 코드 검토 완료. 본래 명령은 읽기 실패로 blocked이며 기존 별칭 요청의 종료·해제·새 정상 parity는 미완료다.

## 변경 동작

로컬 복구 CLI에 `preflight --operation UUID --actor UUID`를 추가했다. 원래 `.env`, 활성 owner,
binding과 snapshot을 확인하고 고정 읽기 명령만 허용한다. STOP/START와 임의 명령은 실행 전에
거부한다. 결과는 ready/blocked/not_required이며 항상 termination_proven=false, parity=not_run이다.
reserved는 종료 관찰이 필요 없다. explicit preflight는 종료 collector 자체를 생성하지 않는다.

새 open legacy_unknown/dispatching freeze는 snapshot digest와 정확한 readback 확인 뒤 사전검사를
수행한다. 실패하면 freeze 호출과 새 gate 획득이 없다. 정확한 기존 frozen/receipt 재접수와
reserved/closed는 불필요한 HOST 검사를 반복하지 않는다. 실제 동시 상태 변경은 기존 repository
CAS가 판정하며 preflight 관찰을 이후 recover의 종료 proof로 재사용하지 않는다.

HOST의 한 관찰 안에서만 같은 canonical 실행 파일의 서명·해시를 공유한다. 읽기 파일 handle과
ancestor handle이 write/delete sharing을 금지하고 final path·파일 식별을 검증한다. 서명 후
같은 파일 객체인지 다시 확인하고 해시는 잠근 stream에서 읽는다. 모든 handle은 finally에서
닫는다. 다른 파일·다음 호출은 새로 검사하고 process별 PID·부모·생성 시각·command는 각각 유지한다.
unknown runtime/WSL/TCP/controller 검사와45초 제한은 유지한다. 이 관찰은 원자적 OS snapshot이 아니다.

수정 제품 범위는 native/CLI와 각각의 단위 테스트4파일이다. 기존0061·core service·proof v1·권한·
원문·계정·활성 구성은 유지했다. 취소, endpoint 폐기와 ES 인증 전환은 포함하지 않았다.
이번 작업은 커밋·push하지 않았고 앞선 첫 질문·복구 미커밋 변경을 보존했다.

## 검증과 수정 이력

- CLI/capability RED15건 → GREEN. 합성 HOST 최초 실제 RED3실패/1통과로 잠금·경로 검사·중복 제거의 부재를 확인했다.
- 합성 helper는 실제 PowerShell 코드에 가짜 CIM/TCP와 공개 합성 파일만 넣었다. 같은 파일 검사 횟수, 별도 호출 freshness, 쓰기/parent 교체 거부, junction·기존 writer 거부, 첫/두 번째 파일 실패 후 handle 해제를 검증했다.
- 첫 실행의 sandbox PowerShell 접근 거부와 script를 두 번 인코딩한 harness의 Windows 명령 길이 오류를 기록했다. 고정 공식 PowerShell 실행과 scriptblock 재호출로 검증했으며 보안 정책·패키지는 바꾸지 않았다.
- root 경로에서 실행한 indexing 검사는 실제 `.env` prefix 영향으로 기존 합성 core fixture28건이 실패했다. 정본의 backend cwd와 상속 AI 설정 초기화로304건 통과했으며 core/설정을 수정하지 않았다.
- 독립 리뷰 I1: native와 CLI가 안전한 세부 거부 사유를 일반 stage로 지웠다. 유한한 고정 코드 allowlist를 공유해 보존하고 임의/private 값은 일반 코드로 제한했다. 회귀 RED18실패/14통과 → GREEN32건; 독립 재검토32건 및 spec/quality 승인.
- 최종 root 실행: backend cwd의 `pytest tests/unit/labs/rag/indexing -q --tb=short` + 새 작업 basetemp, **336 passed in32.51s**, exit0. 네 파일 Ruff 통과, 두 source mypy `--cache-dir=nul` 통과. 외부 모델·실제 DB integration·전체 오래된 package 재검증은 실행하지 않았다.
- 독립 실환경 확인 도구 리뷰에서는 기본 HTTP transport의 프록시/redirect 가능성을 수정했다. no-proxy/no-redirect와 exact URL/200을 적용한 새 before-verified 기록을 기준으로 사용하며 이전 증거를 덮어쓰지 않았다.

## 본래 환경에서 실행한 결과

원래 DB `ai_workshop_local_clean`/0061과 기존 서버를 유지한 채 고정 공식 PowerShell에서 canonical
controller payload로 preflight를 실행했다. 이전과 같은 operation
`f61a8fde-5a88-4690-be51-56e8f14ae696`의 결과는 다음과 같다.

```json
{"preflight":"blocked","diagnostic":"local_command_failed","termination_proven":false,"parity":"not_run"}
```

exit1은 관찰 실패를 숨기지 않은 결과다. 추가 진단도 고정 WSL_STATE/HOST 읽기만 수행했고 원시
stdout/stderr·process command·path는 메모리 밖에 저장하거나 출력하지 않았다. WSL_STATE는
2.245초에 성공했지만 HOST는3.128초에 `file_identity_unverified` 분류로 중단됐다. 이는
canonical/final-path·파일 식별 조건을 충족하지 못했다는 뜻이며, 정확한 하위 조건·파일은
확정하지 않았다. 완전한 inventory가 아니므로 관찰 속도 개선의 실측이나 client 부재 증거로
보고하지 않는다. 기존 IDE/Codex/build 허용 범위도 넓히지 않았다.

전후 읽기 비교에서 보호 정보7개 fingerprint와 원문7개 size/SHA256은 보존됐고 양쪽 health는200이다.
operation은 legacy_unknown/open, exact gate는 frozen revision1·같은 actor/request/snapshot,
receipt0을 유지한다. ES container StartedAt도 이전 실행과 같았다. 서버·컨테이너 stop/start,
새 freeze, 종료/receipt/release/alias/parity는 수행하지 않았다. 새로운 환경·DB·계정도 만들지 않았다.

최종 독립 검증자가 원래 환경을 다시 읽어 before-verified/after와 시각·stage 외의 모든 관측 필드가
같음을 확인했다. 네 제품·테스트 파일은 최종 manifest와 일치했고 추가 Important 결함은 없었다.
기능 범위의 검증이며 기존 별칭 복구 완료 판정은 아니다.

증거는 `.local-data/project-agent-work/alias-host-boundary-20261001/`의 immutable before/fix manifests,
검토 보고서, original-before-verified.json, original-preflight.json, native-read-diagnostics.json과
original-after.json에 있다. 최초 before HTTP 근거는 수정된 before-verified로 대체했지만 보존했다.

## 남은 복구 경계

ISSUE-00013은 진행 중이다. **같은 ES 클러스터의 새 별칭 예약·전송은 계속 차단**되며 health200은
색인 정상화 또는 새 모델 답변 검증을 뜻하지 않는다. HOST 파일 식별 거부의 정확한 조건과
본래 개발 도구를 보존하는 종료 경계를 먼저 해결해야 한다. 현재 서명·이름·부모·연결 부재만으로
전체 client를 안전하다고 간주하지 않는다. 실제 복구에는 지원되는 client 통제 또는 별도로 검토한
서버 측 접근 폐기와 이에 맞는 proof 계약이 필요하다. 이후 같은 요청의 실제 종료·불변 receipt·
정확한 해제·현재 DB truth의 새 정상 parity를 각각 확인한다. 기존 target 재전송·SQL 해제는 하지 않는다.
