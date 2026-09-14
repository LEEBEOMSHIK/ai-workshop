# RAG 출처 연결 조사

- 상태: 소스 조사 및 독립 프라이버시 검토 완료, 세부 연결 방식 승인 대기
- 상위 계약: [2C 공통 출처·목록·증명](../superpowers/specs/2026-09-14-asset-purge-provenance-design.md)
- 이번에는 제품 코드·실사용 DB·서버·사용자 자료를 변경하지 않았다. 애플리케이션 테스트는 실행하지 않았다.

## 확인한 저장 경로

- `labs/rag/documents/repository.py`: projection 생성, 구조 요소 저장, 청크·근거 교체를 수행한다.
- `labs/rag/ingestion/repository.py`: 정확한 source 잠금 후 projection 생성/재사용과 job·dispatch를 같은 트랜잭션에서 저장한다.
- `labs/rag/ingestion/tasks.py`: 파싱/청킹 완료 트랜잭션에서 문서 repository와 산출물 참조를 갱신한다.
- `labs/rag/ingestion/models.py`: parsed/chunk/embedding 객체 경로·해시 및 source 참조도 보관한다. 문서 네 테이블과 별도 추적 범위다.
- `platform/assets/provenance_repository.py`: 관계 등록은 insert-only 멱등 처리다. 자원 소유권은 소유 모듈의 실제 행과 대조해야 한다.

## 대안과 권장 방향

1. 자식 행마다 추적: 세밀하지만 교체되는 행 수만큼 관계가 늘고 이전 관계 정리 부담이 크다.
2. 처리 단위별 집계와 내용 revision: 구조 요소·청크·근거를 하나의 SQL 산출물 묶음으로 추적하고 변경 시 revision을 갱신한다. 권장 후보다.
3. 처리 단위별 고정 revision: DBA 조사에서 가장 작은 안으로 제안됐지만, 현재 교체 가능한 저장 메서드와 오래된 목록 무효화 조건을 충분히 해결하지 못해 그대로 채택하지 않는다.

권장 후보는 SQL 산출물 묶음만 담당한다. 전체 RAG 또는 모든 SQL 자원의 추적 완료라는 뜻이 아니다.
추적 묶음에 포함되는 정확한 테이블, 내용 revision 증가/CAS 조건, 현재 출처 관계의 원자적 교체 또는 이전 관계 비활성화 계약은 상세 설계에서 확정해야 한다.
기존 insert-only 등록에 단순히 revision만 추가하면 과거 관계가 남으므로 이 보완 없이 구현하지 않는다.

## 독립 검토에서 요구한 조건

- 대장을 단독 근거로 삼지 않는다. 실제 projection→원본 버전→문서→공간과 현재 등록을 양방향 비교한다.
- 모든 처리 상태와 모든 대상 버전을 조사한다. 등록 누락·이전 revision·알 수 없는 관계·조회 불완전은 안전한 오류 또는 미완료 상태다.
- DB 저장·revision 변경·현재 출처 관계 갱신은 같은 트랜잭션이다. 실패 시 함께 rollback한다.
- 목록은 UUID·revision·건수·안전 코드만 반환한다. 본문·경로·원본 해시를 공통 추적 데이터에 복제하지 않는다.
- ingestion 작업 메타데이터, 파일/OCR 산출물, Elasticsearch, 평가·생성·Learning·Publishing은 별도 소유 범위로 유지한다. 미연결 참여자를 누락한 채 전체 완료로 판단하지 않는다.
- 원본과 관계의 RESTRICT 해소 순서, worker 재생성 차단, 실제 삭제와 잔존 검증은 후속 활성화 조건이다.

## 인계

메인은 요구·시스템 설계·문서, 별도 DBA는 저장 경로 조사, 독립 프라이버시 담당은 누락·과잉 삭제 위험을 검토했다.
상세 설계 승인 후 Python/DB 구현, 테스트 설계와 독립 통합/코드 검증 역할을 재배정한다.
실사용 backfill·migration·삭제 API/UI 활성화·서버 재시작·커밋/푸시는 이번 조사에 포함하지 않았다.
기존 임시 검토 기록 정리도 별도 승인 전까지 보류한다.
