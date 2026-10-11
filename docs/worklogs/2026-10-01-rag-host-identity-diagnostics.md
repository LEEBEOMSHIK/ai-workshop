# RAG HOST 파일 식별 거부의 원인과 진단 전달

- 날짜: 2026-10-01
- 문제: ISSUE-00013
- 범위: 기존 native HOST 검사와 합성 회귀 테스트. 파일 신뢰·종료 proof 기준은 유지한다.
- 선행: [사전검사 검증](2026-10-01-rag-alias-preflight.md), [ADR-0032](../decisions/0032-rag-alias-recovery.md)

## 확인한 원인

기존 `file_identity_unverified`는 Win32 정보 조회 실패, reparse 속성 또는 final path 불일치를
한꺼번에 보고했다. 고정 PowerShell의 같은 읽기 검사에서 조건을 순서대로 구분한 결과,
첫 실패는 reparse 속성이었다. 추가 태그 조회로 **Node 실행 파일의 상위 디렉터리 심볼릭 링크**를
확인했다. 실제 경로·프로세스 명령은 RAM에서만 다뤘으며 문서·Git·진단 파일에 저장하지 않았다.

| 읽기 진단 | 결과 | 시간 |
|---|---|---|
| 기존 Identity 조건 구분 | `DIAG_REPARSE_POINT` | 3.462초 |
| 같은 handle의 reparse tag 구분 | `DIAG_REPARSE_DIRECTORY_SYMLINK` | 3.366초 |
| 실행 파일의 고정 종류 구분 | `DIAG_REPARSE_NODE_DIRECTORY_SYMLINK` | 3.475초 |

이는 완전한 HOST inventory, 성능 개선 실측 또는 이전 client의 종료 증거가 아니다.
경로 정규화 오류나 WOF 압축 문제라는 초기 가설은 이번 실패의 원인으로 채택하지 않았다.
상위 디렉터리 리디렉션의 거부는 승인된 사전검사 계약에 맞는다. 링크를 따라가거나
Node·IDE·Codex를 일괄 허용하는 수정으로 대체하지 않는다.

Win32의 `FileAttributeTagInfo`는 handle에서 속성과 reparse tag를 읽는 인터페이스다.
[Microsoft API](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex),
[FILE_ATTRIBUTE_TAG_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_attribute_tag_info).

## 진단 전달 수정 범위

수정 대상은 실제 거부 조건을 CLI가 `local_command_failed`로 뭉개는 문제다. HOST는 의도적으로
분류한 고정 실패 코드만 작은 JSON 객체로 전달하고, 파일·상위 디렉터리 handle을 정리한 뒤
비정상 종료한다. native executor는 HOST의 비정상 종료에서만 정확한 객체 형태와 크기·고정
코드 목록을 확인한다. 중복 키·추가 필드·임의 문자열·비공개 내용·원시 stderr는 상세 진단으로
사용하지 않는다. 다른 명령과 알 수 없는 실패는 기존 일반 오류를 유지한다.

파일과 경로의 잠금·동일성 검사, 서명·해시, 프로세스별 관찰, fresh 호출과 45초 제한은 유지한다.
진단 코드는 차단의 이유이며 사전검사 성공이나 proof로 바뀌지 않는다.
독립 보안·코드 검토자가 이 좁은 설계를 승인했다. 구현과 최종 검증 결과는 같은 기록에 이어 남긴다.

## 실행한 회귀 검증

| 검증 | 결과 |
|---|---|
| subprocess 진단 전달의 수정 전 테스트 | 10실패·19통과 |
| 보존한 이전 HOST를 RAM에 주입한 수정된 실행기의 RED | 9실패·1통과·20.73초 |
| 현재 HOST의 실제 합성 PowerShell 테스트 | 10통과·20.54초 |
| 관련 전체 indexing 단위 테스트 | 369통과·29.62초 |
| 수정2파일 Ruff / source1파일 mypy | 통과 |

실제 HOST 합성 테스트는 OS·네트워크 열거를 가짜 입력으로 대체하며 공개 합성 파일만 사용한다.
진단 코드·실제 exit1·실패 뒤 파일 잠금 해제·두 번째 파일 실패·정리 중 한 Dispose 실패 뒤
나머지 정리 계속·임의 오류 문구의 일반 실패 처리와 기존 정상 호출의 중복 제거를 확인했다.
본래 서버·DB를 합성 단위 테스트에서 사용하지 않았다. 이전 전체3161개 테스트를 이번 결과로
다시 실행했다고 보고하지 않는다.

처음 sandbox의 고정 PowerShell 실행은 WinError5로 막혔으므로 행동 RED로 간주하지 않았다.
첫 수정 후 테스트에서는 실행기가 실패 JSON을 성공용 파이프에 소비하는 결함을 발견했다.
실패 테스트의 실제 출력을 직접 관찰하도록 실행기만 수정했고 제품의 exit를 생략하지 않았다.
수정된 실행기로 보존한 이전 HOST의 RED를 다시 확인했다. programmatic pytest의 기존 anyio
선행 import 경고1건은 그 RED에만 있었으며 최종369개 검증에는 없었다.

## 본래 환경과 남은 경계

착수 전 읽기에서 보호 정보7개·원문7개 크기/해시와 양쪽 health200을 확인했다.
기존 operation은 open, gate는 frozen revision1, receipt0이며 ES 실행 세대를 보존한다.
서버·Docker·DB·색인을 변경하거나 별도 환경·계정·DB를 만들지 않는다.

구현 후 본래 `.env`·공식 고정 PowerShell·정확한 원래 operation/actor를 사용하는
`preflight`를 실행했다. 이제 CLI 결과는 **`blocked / host_ancestor_reparse`**, exit1,
`termination_proven=false`, `parity=not_run`이다. 원시 오류·비공개 경로가 결과에 포함되지 않는다.
root의 전후 읽기에서 revision·보호 정보·원문·operation·gate·receipt·ES container/cluster·health의
9개 그룹이 시각·stage 외에는 모두 일치했다. 양쪽 health200, 원문7개·보호 정보7개,
same open/frozen revision1·receipt0·기존 ES 실행 세대를 유지했다. 새 freeze·Stop/Start·
복구·receipt·release·alias·parity는 수행하지 않았다. 새 모델 답변의 실행 검증도 이번 범위가 아니다.

독립 구현 검토는 Spec/Quality Approved이며 진단 프로토콜31개를 별도로 실행해 통과했다.
최종 통합 검증자는 원래 환경을 03:24:09.957345 UTC에 다시 읽어 root의 전후 관측과 시각·stage
외의 모든 필드가 같음을 확인했다. 승인된 두 파일의 해시도 재확인했고 진단 기능 범위에서
추가 Important 결함이 없었다. 실제 복구의 완료 판정과는 구분한다.

상세 근거와 immutable 기준선·RED/GREEN·리뷰·본래 읽기 결과는
`.local-data/project-agent-work/alias-file-identity-20261001/`에 보존했다.
관리자 로그인이 만료돼 **이번 새 문서의 DB 등록·연결과 진행 이력 저장은 재로그인 대기**다.
기존 ISSUE-00013과 과거 문서·진행 이력은 변경하지 않았으며 파일 기록만으로 DB 반영을
완료했다고 보고하지 않는다. 커밋·push·캐시 또는 임시 증거 정리는 수행하지 않았다.

유효한 상위 링크 거부를 없애는 것만으로 전체 개발 PC의 늦은 ES 쓰기 불능이 증명되지는 않는다.
실제 복구에는 본래 개발 도구를 보존할 수 있는 종료 경계를 별도로 명시해야 한다.
현재 v1의 client 통제로 지원되지 않으면 서버 측 접근 폐기와 그에 맞는 proof·배포 계약을
설계한다. 기존 요청 종료·불변 receipt·정확한 release·현재 DB 기준 새 정상 parity는
실제 근거 확보 전까지 미완료로 유지한다.
