# 문서 전용 임시 작업공간 설계 기록

- 날짜: 2026-09-20
- 범위: 원본 파일 추적 다음 단계의 상세 설계 및 읽기 전용 경로 조사
- 상세안: [문서 전용 임시 작업공간](../superpowers/specs/2026-09-20-document-temporary-workspace-design.md)

## 조사와 결정

메인은 저장소 수명주기·문서 경계를 정리했다. 별도 RAG 담당이 파서/DOCX/PDF OCR/preview와
HTTP spool 호출 경로를 조사했고, DBA가 일반 Job 변경과 FK·독립 예약 잠금을 조사했다.
독립 검토자는 상세안의 소유권·종료·프라이버시를 검토한다.

RAG lifecycle transaction이 끝난 뒤 예약해야 FK 자기 대기를 피할 수 있다.
동기 parser에 DB session을 전달하지 않고 이미 예약된 작업공간을 전달한다.
preview는 권한 확인 source를 전달하고 실제 worker reap 뒤에 정리한다.
종료를 확인할 수 없는 실행은 open으로 남기며 단순 job 완료나 timeout으로 닫지 않는다.

HTTP multipart spool은 원본 coordinator 이전에 생기므로 별도 선행 예약 계약이 필요하다.
일반 Job revision은 dispatch의 직접 ORM/bulk 변경도 포함해야 하므로 별도 구현 단위로 남긴다.
OCR/preview 라이브러리의 외부 쓰기와 과거 미추적 파일은 전체 삭제 검증의 미완료 경계다.

## 검증 및 운영 범위

제품 코드·DB·서버·실자료는 변경하지 않았다. 애플리케이션 테스트는 실행하지 않았다.
상세안/기록의 상대 링크·UTF-8·공백 검사와 WORKBOARD 최근 완료 5개 제한 검사를 통과했다.
독립 검토의 필수 보완 2건(트리 관찰만으로 소유권 추정 금지, worker와 동일한 예약 잠금 순서)을 반영했다.
배타 생성·생성 전 메모리 manifest·미등록 파일 정리 차단과 job→version→document→원장 순서를 명시했다.
독립 재검토에서 두 보완의 반영과 설계 단계의 잔여 차단 없음이 확인됐다.
사용자 참고 이미지 `references/`는 보존하고 커밋에 포함하지 않는다.
