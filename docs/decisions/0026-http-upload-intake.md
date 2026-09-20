# ADR-0026: HTTP 본문 수신 전 업로드 소유권 예약

- 날짜: 2026-09-20
- 상태: 승인됨·구현 및 독립 검토 완료 (실사용 적용 전)

## 배경

FastAPI File/Form의 자동 multipart 해석은 인증 dependency보다 먼저 실행되어,
원본 예약 전에 Starlette가 추적하지 않는 OS 임시 파일을 만들 수 있었다.
문서 전용 임시 작업공간의 실제 source FK는 아직 생성되지 않은 신규 문서에 사용할 수 없다.

## 결정

두 업로드 API는 Request stream을 직접 받는다. 인증·공간 쓰기 권한 확인과 독립 intake
예약 commit을 마친 뒤 전용 저장소에 payload 하나를 만들고 제한된 multipart adapter로 쓴다.
50MiB 파일 한도와 별도 envelope/header/field 한도를 실제 수신 바이트로 확인한다.
기존 주소·201 응답·파일/폴더 필드 순서·조건부 작업 전달은 유지한다.

Platform Assets는 예정 source와 실제 source를 구분하는 HTTP intake 원장을 소유한다.
원본 예약 생성과 intake 연결은 원자적이며, 원본·문서 버전·job·출처와 최종 intake 연결은
같은 transaction에서 확정한다. 최종 commit 응답이 확인된 뒤에만 live snapshot을 갱신한다.
reader/writer 종료와 closed→cleaning commit을 확인한 뒤 Windows 핸들 기반으로 정리하고,
실제 부재 확인 뒤 cleaned를 기록한다. commit·종료 확인이 불확실하면 파일과 원장을 보존한다.

## 영향

migration0047과 원본/임시 저장소 binding이 준비되어야 HTTP 업로드가 가능하다.
초기 mutation은 Windows 전용이며 미설정 환경은 명시 실패한다. 기존 OS temp는 인수하지 않는다.
새 intake의 정리 완료는 과거 spool 부재의 증거가 아니므로 legacy inventory 차단은 유지한다.
일반 Jobs 출처, 미확인 OCR writer, 잔존 복구와 실제 purge 활성화는 후속이다.

구현 전 승인된 [상세 설계](../superpowers/specs/2026-09-20-http-upload-intake-design.md)가 계약 정본이다.
검증과 적용 한계는 [작업 기록](../worklogs/2026-09-20-http-upload-intake.md)에 둔다.
