# RAG 서버 측 접근 epoch 설계 검토

- 날짜: 2026-10-01
- 문제: ISSUE-00013
- 상태: 설계 초안 작성·독립 검토 완료, 사용자 설계 검토 대기
- 설계: [접근 epoch 계약](../superpowers/specs/2026-10-01-rag-access-epoch-design.md)
- ADR 제안: [ADR-0033](../decisions/0033-rag-access-epoch.md)

## 이번 작업

사용자는 다음 기능 작업을 진행하고 품질 개선만 남았을 때 알릴 것을 요청했다.
기존 전체 HOST 종료 계약을 도구 이름 예외로 완화하는 대신, 이전 ES accepting JVM을
종료하고 새 TLS·인증 실행이 과거 익명 capability를 거부하는 별도 전이를 설계했다.

기존 ES named data volume·이미지·cluster·영속 node와 원본/DB/계정/구성/큐는 보존한다.
원본 ES 컨테이너는 정확한 종료 확인 후 메타데이터만 퇴역시키고 secured 세대로 교체한다.
API·worker·beat는 새 immutable credential 세대로 실행하며 IDE·Codex·frontend는 유지한다.
프로젝트 전용 CA만 사용하고 root .env/부모 shell/hot reload/proxy로 새 key를 전달하지 않는다.

distinct v2 proof와 exact claim/epoch/execution의 원자적 closure·receipt, 영속 인증 floor,
settled-only 외부 제어 재개와 unknown 결과의 frozen 보존을 명시했다. 과거 보안 metadata와
이미 수락됐을 수 있는 요청의 경계도 다룬다. secured forward repair만 지원한다.

## 독립 검토와 문서 검증

아키텍처·Docker·DB 제안과 구현 책임으로부터 분리된 보안 검토 및 계약 검토를 수행했다.
양쪽 판정은 **Ready for user design review**이며 사용자·구현·배포 승인과 구분한다.
검토 보고서는 해당 task의 `.local-data/project-agent-work/alias-access-epoch-20261001/`에 있다.
미래 실제 cutover/테스트를 현재 성공 근거로 사용하지 않았다.

설계와 ADR의 상대 링크·미완성 표식·WORKBOARD 최근 완료5개와 AGENTS200줄 제한을 검사했다.
이전 독립 승인된 HOST 코드2파일의 SHA가 그대로인 것을 확인했다. 이번에는 application
코드를 변경하지 않아 product tests·타입·린트를 다시 실행하지 않았다. 이전369건을 이번
새 v2 계약의 테스트 결과로 쓰지 않는다.

Git 읽기에서 core.excludesFile=NUL은 이번에는 오류를 반환했다. 기존 `.git/info/exclude`를
명령 단위로 지정해 status와 WORKBOARD diff check를 완료했다. Git 설정·index를 쓰지 않았다.
diff check는 LF/CRLF 안내만 있었고 whitespace 오류는 없었다. 별도 worktree를 만들지 않았다.

## 아직 실행하지 않은 것과 다음 단계

credential/CA 생성, original container stop/remove/create/start, migration, epoch/operation/gate
변경, proof·receipt·release·parity는 **모두 미실행**이다. 현재 본래 상태 설명은 이전 검증의
인계이며 이번 설계 검토에서 새 원본 DB/ES 보존 관찰을 했다는 의미가 아니다.

먼저 사용자가 이 설계를 검토한다. 그 뒤 상세 구현 계획과 TDD·독립 검증으로 코드를 준비하고,
구체적인 원본 컨테이너/volume/secret 보관/중단/secured 회복 계획을 최종 배포 승인에 제시한다.
관리자 UI는 여전히 로그인 화면이며 본래 문제 DB에 새 HOST/설계 문서·진행 이력을 저장하지 못했다.
로그인 후 정확한 문서 버전과 과거 링크를 보존해 연결한다. JSON 편집으로 저장을 대신하지 않는다.

WORKBOARD에는 별칭 정상화, 신규 실패 저장·monitoring, 본래 사용자 흐름, 이력·배포 인계의
기능 마감 기준을 추가했다. 이 기준이 모두 실제로 검증된 때 사용자에게 품질 개선만 남았다고
알린다. 현재는 그 시점이 아니며 ISSUE-00013 해결이나 전체 RAG 기능 완료를 주장하지 않는다.
