# HTTP 업로드 임시물의 선행 예약

- 날짜: 2026-09-20
- 상태: 독립 검토 완료·사용자 상세안 확인 전, 제품 구현 전
- 목적: HTTP 수신 bytes가 디스크에 기록되기 전에 소유자를 등록하고 신규 문서/새 버전의 원본 예약과 연결한다.
- 선행: [원본 추적](2026-09-20-original-file-ownership-design.md), [문서 임시 작업공간](2026-09-20-document-temporary-workspace-design.md)

## 1. 현재 빈틈과 범위

현재 upload route의 File/Form은 FastAPI가 인증 dependency 실행 전에 request.form을 호출하게
한다. Starlette는 파일이 메모리 spool 한도를 넘으면 OS 임시 파일을 만든다. 원본 coordinator의
예약은 이 뒤이므로 HTTP 수신 복사본은 추적하지 못한다. dependency 순서를 바꾸는 것만으로
해결되지 않는다.

이번 범위는 두 업로드 API의 request 수신·multipart parser·사전 원장·원본 연결·읽기 목록이다.
Platform Assets가 계약을 소유한다. RAG에는 새 소유 책임을 추가하지 않는다.
일반 Jobs 출처, 기존 OCR 잔존 회수, 비Windows native 구현, 실제 purge 활성화는 후속이다.
실사용 환경 적용·자료 업로드/삭제는 구현 검증과 구분한다.

## 2. 선택한 흐름과 대안

선택은 **Request 직접 수신 → 인증/공간 권한 확인 → intake 예약 commit → 등록된 payload
파일 하나로 증분 multipart 해석 → 기존 원본 예약/게시/확정 → intake 정리**다.
파일명/폴더 필드가 뒤에 와도 수신 소유권은 이미 사용자·공간·예정 source로 고정된다.

raw multipart body 전체를 먼저 저장하고 다시 payload로 풀면 전체 크기의 복사본과 I/O가
한 번 더 생긴다. 필요하지 않으므로 채택하지 않는다. 전역 tempfile monkeypatch는 다른
요청과 파서의 경계를 오염시키므로 사용하지 않는다. spool 한도를 무한히 늘려 메모리에만
보관하는 방법도 사용하지 않는다.

두 endpoint의 주소·201 응답·DocumentResponse·성공 후 조건부 job dispatch는 유지한다.

- 신규: `POST /api/v1/workspaces/{workspace_id}/documents`, file 1개와 선택 folder_id.
- 새 버전: `POST /api/v1/documents/{document_id}/versions`, file 1개만 허용.
- frontend는 현재 file을 먼저, folder_id를 나중에 보낸다. 두 순서를 모두 허용한다.
- 자동 File/Form 선언을 제거하되 multipart requestBody OpenAPI를 명시적으로 유지한다.
- file filename/content-type의 기존 해석 및 확장자 정책은 원본 coordinator와 일치시킨다.

## 3. 수신 전 소유권

새 `UploadIntakeClaim`은 서버가 생성하는 불변 capability다. 사용자가 예정 ID를 임의 제출하는
API는 만들지 않는다. 일반 파일 목록에는 아직 생성되지 않은 문서를 노출하지 않는다.

원장에는 다음을 기록한다.

| 항목 | 계약 |
| --- | --- |
| intake ID | UUID, 작업공간 token과 동일, 재사용 금지 |
| 사용자·공간 | 수신 전 현재 인증과 공간 쓰기 권한 검증 |
| 예정 document/version ID | 처음 예약부터 원본 확정까지 동일 |
| 신규/새 버전 구분 | 불변, 기존 문서는 lifecycle generation 고정 |
| 기존 문서 pin | 새 버전만 실제 `(workspace_id, existing_document_id)` RESTRICT FK |
| 저장소 ID/binding | 전용 temporary root의 marker와 일치 |
| original attempt 연결 | 최초 NULL, 원본 예약과 같은 transaction에서 단 한 번 연결 |
| attachment | 미확정/확정, 실제 source pin과 최종 transaction에서 함께 확정 |
| state/revision | open/closed/cleaning/cleaned와 단조 증가 revision |
| 고정 오류 코드·시각 | 내부 진단용, 시각은 writer 종료 증명으로 쓰지 않음 |

예정 version ID에 실제 source FK를 걸지 않는다. 신규 문서는 실제 Document가 없으므로
원장 자체를 workspace/attempt 목록으로 발견할 수 있어야 한다. 실제 source 확정 후에는
별도 실제 source pin과 common provenance를 같은 transaction으로 생성한다.
실패 원장은 사용자/공간 삭제 CASCADE로 잃지 않도록 예정 소유 식별자와 실제 pin을 분리한다.

일반 source provenance와 달리 원장은 attachment 전부터 존재한다. attachment 후 공통 자원은
`platform_http_uploads / intake / intake_id`로 식별한다. 상태/연결/attachment 변경마다
revision을 증가시키고, 관계가 존재하면 현재 relation revision도 같은 transaction에서 교체한다.
문서 임시 작업공간의 고정 1~4 revision을 이 원장에 그대로 적용하지 않는다.

## 4. 인증과 트랜잭션 순서

1. Request-only endpoint는 get_current_user를 비롯한 인증 dependency를 완료한다.
   body를 읽는 dependency, request.body/form 호출과 request logging을 추가하지 않는다.
2. 신규 업로드는 공간 쓰기 권한을 확인한다. 새 버전은 문서 접근·공간 쓰기·active 상태를
   확인한다. 독립 예약에서 현재 권한을 잠금 아래 다시 검사하고 generation을 고정한다.
3. intake commit 성공을 확인한 뒤에만 filesystem workspace를 생성하고 request.stream을 읽는다.
   commit 결과 불명은 파일 생성/스트림 소비 0회다. 재접속 요청은 새 intake를 사용한다.
4. multipart EOF/완료 확인 뒤 folder UUID·소속·active 상태를 검사한다. 권한 없는 폴더나
   잘못된 metadata는 원본 게시로 진행하지 않고 이미 추적된 intake만 정리한다.
5. 원본 예약은 intake의 예정 source와 user/generation을 재사용한다. 원본 attempt 생성과
   intake 연결/CAS를 같은 독립 transaction에서 확정해 두 attempt가 한 intake를 소비하지 못하게 한다.
6. 원본 게시 이후 기존 prepare_attachment 경계에서 권한·folder/document·generation을
   재검사한다. 문서/버전/job/원본 관계/intake 실제 source pin·attachment/관계를 같은
   요청 transaction에서 확정한다. commit 성공 확인 뒤 기존 응답과 dispatch를 반환한다.

기존 업로드 잠금 순서인 workspace → membership → folder/document → intake/original 원장을
고정한다. 두 원장은 intake → original 순서를 사용하며 역순 경로를 만들지 않는다.
Document 뒤에서 기존 version을 추가로 잠그지 않는다. 호출 session이 source/권한 행을
잠근 채 독립 예약을 await하지 않는다. 상세 SQL/CAS는 구현 계획에서 기존 prepare capability와
같은 root/nested transaction 검증까지 포함한다.

intake의 revision은 서버의 live lease가 추적한다. 원본 예약/최종 attachment의 성공이 확인된
경우에만 새 revision을 lease에 전달한다. commit 응답이 불명인데 재조회로 revision을 추정해
정리 권한을 얻지 않는다. 이 경우 원본과 intake를 보존해 목록에 미완료로 남긴다.

DB에는 intake–original 연결의 예정 source 일치 복합 FK, original attempt 중복 연결 방지,
실제 pin의 source 일치와 attachment 불변식을 명명된 제약으로 둔다. caller 검증만으로
이 제약을 대신하지 않는다. 구체 column/constraint와 CAS는 구현 계획에서 함께 정의한다.

## 5. 디스크와 multipart 경계

문서 임시 어댑터의 actual-source claim을 위조해 재사용하지 않는다. 기존 `TemporaryClaim`
검증은 유지하면서 하부의 `(token, binding)` 물리 할당을 작은 공통 계약으로 분리한다.
HTTP 전용 wrapper는 검증한 UploadIntakeClaim으로만 접근한다. 새 저장소/모델 캐시는 만들지 않는다.
동일 temporary root 아래 exclusive UUID 작업공간에 고정 `payload.bin` 파일 하나를 배타 생성한다.
파일 핸들 identity와 ancestor/marker pin은 수신부터 원본 읽기 종료까지 유지한다.

low-level python-multipart callback만 사용한다. Starlette MultiPartParser와 multipart의
고수준 파일 생성 helper를 사용하지 않는다. 라이브러리의 max_size는 초과 오류 대신 truncate할
수 있고 finalize도 terminal 상태를 보증하지 않으므로 직접 한도와 완료 증거를 검사한다.

한도는 named policy로 다음 기본값을 둔다. 파일 상한은 기존 50 MiB와 같은 정본을 참조한다.

- file payload: 최대 50 MiB, 정확히 1개의 `file` part.
- request envelope: file 상한 + 64 KiB, Content-Length와 무관하게 실제 수신 bytes를 계산.
- 각 parser 입력 slice: 최대 64 KiB. file write는 해당 요청의 동기 bounded write로 수행한다.
- multipart boundary: 최대 256 bytes, part header 수 8개·총 4,224 bytes 이하.
- field: 신규 업로드의 folder_id 한 개만, 최대 128 bytes; 새 버전에서는 field 불허.

중복/알 수 없는 field, 두 번째 file, 잘못된 disposition, 중복된 필수 header,
허용하지 않은 encoding, filename/field 구분 위조를 안전한 4xx로 거절한다.
filename 등 사용자 입력을 오류 메시지나 원장 locator에 넣지 않는다.
빈/없는 file, 잘못된 UUID, 한도 초과, malformed/truncated body는 성공 원본을 만들지 않는다.
정확한 file part 종료와 parser on_end, 실제 request EOF를 모두 확인해야 한다.
최종 boundary 뒤 비어 있지 않은 epilogue/추가 payload도 거절하며 묵시적으로 무시하지 않는다.
정상 종료 framing의 선택적 CRLF는 허용한다. 라이브러리가 END 뒤 bytes를 버리고 입력 전체
길이를 반환하므로 write 반환값/on_end/EOF만으로 검증하지 않는다. terminal suffix를 별도로
추적하고 같은 slice에 붙은 추가 bytes와 다음 slice의 추가 bytes를 모두 검사한다.
header/field 한도는 callback 누적 단계에서 검사해 완료 후 크기 검사로 메모리 한도를 우회하지 않는다.
모든 입력을 메모리에 모으거나 끝없는 request를 한도 없이 소비하지 않는다.

## 6. 실패·취소·정리

writer는 이 요청의 bounded 동기 write뿐이다. parser/file writer와 원본 publish용 reader가
모두 닫힌 뒤 open→closed로 전이한다. 별도 threadpool로 옮기려면 취소 뒤에도 실제 thread
종료를 기다리는 계약과 테스트를 추가해야 하며 이번 구현에서 임의로 옮기지 않는다.

closed commit → cleaning commit → manifest/핸들 기반 정리 → 정확한 부재 관측 → cleaned
commit 순서를 지킨다. 실제 source attachment 여부와 물리 정리 상태는 별개다.
정리 실패는 locator와 미완료 revision을 보존한다. 원본 commit이 성공한 요청을 임시 정리
실패 때문에 실패 업로드로 되돌리지 않는다. 안전한 고정 오류 코드로 내부 기록하며 성공
응답·job dispatch는 유지한다. 사용자 재업로드로 중복 원본이 생기도록 유도하지 않는다.

disconnect/취소/잘못된 multipart에도 finally로 writer를 닫고 가능한 범위에서 정리한다.
프로세스 crash, 원장 commit 불명, writer 종료 불명은 open 등 마지막 확인 상태를 보존한다.
원본 commit 불명 때 원본 canonical을 삭제하지 않는다. intake도 확인되지 않은 attachment
revision을 건너뛰어 정리하지 않는다. 예외를 숨기거나 cleanup 성공으로 바꾸지 않는다.
미등록 파일/reparse/hardlink/경로 교체는 기존 native 어댑터처럼 삭제를 거절한다.

## 7. 목록과 보존

문서별 목록은 실제 버전 외에 예정 document ID로 연결된 intake도 포함한다.
문서가 생성되지 않은 신규 실패 intake는 현재 권한 확인 후 workspace 기준 별도 목록으로
제공한다. 현재 권한을 확인한 API/내부 결과에는 opaque ID·revision·상태·안전 차단 코드만 둔다.
파일명·folder field·payload·파일 경로·인증 정보는 반환하지 않는다.

원장/actual pins/original attempt/current relations와 물리 관측 전후 snapshot을 비교한다.
새 intake, revision 변경, binding 불일치, open writer, 파일 잔존 또는 관계 누락은 incomplete다.
cleaned는 해당 token의 부재 증거이며 과거 HTTP spool을 정리했다는 증거가 아니다.
legacy 미추적 blocker는 유지한다. 아직 존재하지 않는 source의 관계를 만들거나 원장만으로
전체 문서 삭제 완료를 판정하지 않는다. source/original/intake pin을 정리하는 실제 purge는 후속이다.

## 8. 검증과 완료 기준

1. 인증/권한 거절·예약 실패·commit 불명에서는 body 소비와 filesystem 생성이 없다.
2. 기존 frontend의 file-first/folder-last와 역순이 동일 결과이며 두 URL/응답/OpenAPI가 유지된다.
3. payload/envelope 한도, boundary/header/field 한도, 중복·미지 part, malformed/truncated EOF,
   final boundary 뒤 같은/분할 slice의 추가 bytes와 정상 CRLF, disconnect·반복 취소를 검사한다.
4. 한도를 넘는 입력이 라이브러리 truncate 동작으로 성공 처리되지 않는다.
5. 예정 ID가 intake→원본 예약→문서/버전/job/두 관계까지 같고 다른 문서/version intake의
   재사용·위조·동시 소비는 CAS/FK/권한 검증으로 거절한다.
6. 최종 commit 결과 불명·권한 철회·generation 변경·중복 원본에서 파일과 locator를 잃지 않는다.
7. 원본 성공 뒤 intake 정리 실패가 기존 성공 응답/조건부 dispatch를 바꾸지 않는다.
8. 실제 OS spool 호출을 금지한 route 테스트와 실제 Windows 어댑터·격리 PG 통합을 실행한다.
9. 기존 원본/임시 작업공간의 unit·type·lint 회귀 및 독립 DB/프라이버시/코드 검토를 통과한다.

실제 사용자 파일이나 실사용 DB를 테스트 fixture로 쓰지 않는다. 기존 ingestion fixture의
산출물 설정 실패는 이 HTTP 계약 검증과 구분하고 전체 RAG 통합 통과로 보고하지 않는다.
