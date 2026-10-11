# 개인 첨부의 저장 검증과 RAG 색인 예약 확인

2026-10-08 KST. 기존 개인 공간에 정상 업로드한 합성 PDF 한 건을 대상으로 저장 검증을 완료했다. 기존 환경·계정·대화·검색/생성 범위를 그대로 사용했다. 메인은 진단과 단일 대상 정상 작업 실행, 독립 담당은 권한·자료 보존과 작업 경계 검토를 맡았다.

## 원인과 실행 범위

원본 파일은 정상 저장됐지만 worker와 beat가 꺼져 있어 기존 검증 작업이 running/dispatching_verification에 남아 있었다. 파일 손상이나 개인 공간 저장 권한 거부가 원인은 아니었다. 현재 회사 검색·생성 범위 밖의 개인 파일이라는 상태는 별도 경계다.

전역 worker/beat를 시작하면 기존 대기 작업까지 처리하게 된다. 따라서 기존 설정으로 등록된 정상 `ai_workshop.assets.verify_stored` 작업을 이 파일의 기존 검증 작업 ID로 한 번만 실행했다. 정상 수명주기, 현재 권한 검사, 실제 PersistentVerifiedAssetSubscriptions와 artifact admission을 그대로 사용했다. 직접 SQL 상태 변경, 빈 구독 대체, 모델·파서 대체는 하지 않았다.

실행 시각은 2026-10-08 01:18:37 UTC(10:18:37 KST)다. Celery의 명시적 `apply(throw=True, retries=0)`로 정상 작업 본문과 신호를 실행하되 Retry 예외는 즉시 중단하도록 했다. 정상 작업의 재시도 계약을 바꾸거나 이전 재시도 횟수를 꾸미지 않았다. 실행 시작 표식을 배타적으로 생성해 같은 도구의 중복 실행을 막았다.

이 호출은 Redis의 기존 메시지를 소비하거나 삭제하지 않는다. 기존 메시지가 이후 정상 전달될 수 있으며, 기존 검증과 인계의 멱등 계약에 맡긴다. 이번 작업에서 broker 메시지를 수동 정리하지 않았다.

## 실제 결과

| 확인 대상 | 실행 전 | 실행 후 |
| --- | --- | --- |
| Platform AssetVersion | stored | ready |
| 문서 활성 버전 | 없음 | 검증한 기존 버전 |
| 기존 검증 작업 | running / dispatching_verification / revision2 | succeeded / ready / revision4 |
| 검증 작업 attempt | 1 | 1 |
| RAG projection | 없음 | pending1 |
| RAG ingestion 작업·dispatch | 없음 | queued1 / pending1 |
| 실제 RAG index build | 없음 | 없음 |
| 대화 첨부 표시 | stored / 검색·생성 범위 밖 | 동일 |

저장 파일과 기존 합성 원본의 실제 바이트가 같고, 크기204671 및 등록 SHA-256도 일치한다. 정상 작업 결과는 SUCCESS이며 오류 코드가 없다. 모델 호출·임베딩·PDF 파싱·ES 색인 및 별칭 쓰기0, 자동 재시도0, 전역 worker/beat 시작0이다. Platform ready는 저장 무결성 검증이며 RAG 검색 준비 완료를 뜻하지 않는다.

파일이 ready가 된 뒤 기존 구독에 따라 정상 RAG 예약이 만들어졌다. 구독을 새로 추가하거나 현재 대화에 파일을 자동 선택하지 않았다. 개인 공간의 외부 전송 deny와 기존 회사 생성 범위는 유지했다.

정상 첨부 서비스로 현재 소유자의 접근 권한과 개인 공간 쓰기 자격을 실행 직전·직후 다시 확인했다. 기존 Chrome 대화를 새로고침해 기존4턴과 개인 첨부 카드 복원을 확인했다. 화면의 “저장됨 · 현재 답변에 사용 불가”와 검색·생성 범위 밖 안내는 그대로이며, 파일 검증 실패로 해석하지 않는다. 새 질문·대화·turn·외부 전송은 없다.

## 검증과 보존

작업 전 worker·admission·asset 수명주기·버전 계약 단위 **99개 통과**(5.58초)를 확인했다. 이번 작업에서 제품 코드·스키마·프로파일은 수정하지 않았으며 전체 저장소 회귀 통과로 확대하지 않는다. 운영 확인 도구의 첫 두 읽기 시도는 문서 필드와 User 인자 오류로 중단됐고, 수정 후 정상 권한·바이트 확인을 통과했다. 이 두 시도에서 작업 실행과 DB 변경은 없다.

독립 기준선은 기존71테이블, 추가 proof/slot/original resource4테이블, 구독·인계·artifact8테이블과 동결15보고서다. 기존5대화23턴·선택4턴, 환경·등록 Codex0.161.0, active32/pending128, schema0063, frozen gate1/receipt0, 기존3PDF와 저장 개인 파일을 보호한다.

정상 변경은 기존 문서1행·asset1행·검증 job1행과 해당 검증 job 출처 관계의 resource_revision2→4다. 마지막 관계는 JobRepository.update의 정상 출처 소유권 갱신이며, 독립 검토에서 revision만2로 재구성한 전체 SHA가 기존 행과 일치했다. 정상 신규 예약은 projection1·job1·ingestion1·dispatch1·artifact bundle1·reserved slot3·동일 원본의 출처 관계3·job source ownership1이다. 독립 READ ONLY 검토는 기존83테이블의 나머지 기존 행, 동결15보고서와 모든 기존 문제 행을 보존하고 신규 관계의 정확한 parent/source 연결을 확인해 PASS했다. 실제 Persistent 구독1개/서로 다른 profile pair1개이며 artifact attempt0, 파싱·청크·임베딩·색인 수는 미기록, alias_verified=false다. 보고서 정상 등록 이후 최종 마감 메타데이터는 Workboard에 남긴다.

실행과 독립 증거는 `.local-data/project-agent-work/rag-personal-attachment-lifecycle-20261008/`에 있다. 비공개 본문·계정·비밀값·원시 오류는 이 보고서에 저장하지 않는다.

## 남은 기능 경계

예약을 실제 파싱·임베딩·색인 READY로 진행하는 것은 남아 있다. 기존 ISSUE-00013의 별칭 작업은 open/frozen이며 새 별칭 예약·전송을 막는다. 정상 AliasJournal.reserve/dispatch가 현재 gate의 admitted 상태를 요구하므로 worker를 켜는 것만으로 검색 준비를 보장할 수 없다. 이번에는 그 실패를 만들기 위해 파싱·임베딩을 선행 실행하지 않았다. 기존 legacy 환경의 epoch 설정 부재 자체가 항상 worker admission 실패라는 주장도 하지 않는다.

후속은 실제 이전 별칭 쓰기의 종료 증거와 접근 차단·복구 receipt·새 정상 parity를 먼저 충족하고, 기존 예약의 정상 색인과 개인 첨부의 허용된 검색 흐름을 검증하는 것이다. 개인 파일을 외부 생성에 사용하려면 기존 범위·전송 승인 계약을 충족해야 하며 이번 저장 검증으로 승인된 것으로 간주하지 않는다.

실모델 취소/실패/timeout, committed 권한·첫 질문 경합, DLL 재발 방지, Git/실행 인계도 기존 기능 마감 목록에 남는다. **아직 품질 개선만 남은 상태가 아니다.** ISSUE-00002/00005에 이 보고서 exact DB 버전과 진행 사건을 연결하고 기존 status/remaining·업무 필드·이전 사건/문서 연결을 보존한다. DB 등록 후 이 보고서는 동결한다.

staging/commit/push0이다. 이번 변경은 정상 대상 작업의 DB 상태와 예약, 운영 도구 및 기록이며 제품 코드 수정이나 전체 RAG 완성으로 보고하지 않는다.
