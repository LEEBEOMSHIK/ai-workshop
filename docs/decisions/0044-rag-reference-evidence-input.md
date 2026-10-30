# ADR-0044: 원문과 인용을 보존하는 v6 생성 입력

- 상태: 구현·실제 동일 질문2회 비퇴행 확인, 전체 품질·성능 기준 미수용·비기본 유지 (2026-10-26)
- 관련: [실제 입력 처리 병목](../worklogs/2026-10-26-ollama-native-timing.md), [ADR-0043](0043-ollama-native-timing.md)

## 목적과 선택

첫 답변 담당의 196.492초 중 입력 처리181.092초를 확인했다. 사용자 요구는 현재 답변 품질을 낮추지 않으며 이 입력 비용을 개선하는 것이다. 기존 정답0/2를 품질 통과로 바꾸거나 품질 개선 범위를 자동 재개하지 않는다.

공백 제거는 기존 compact JSON에서 절감0이고 근거 삭제·요약은 정보 손실 가능성이 있어 선택하지 않는다. 새 명시적 `rag-answer-v6`는 기존 v5의 근거 표현만 바꾼다. 고유 UUID 대신 요청 한정 e1,e2,…를 쓰고 fragment의 반복 필드 이름을 고정 columns 한 벌로 표현한다. source 메타데이터는 v5가 이미 묶으므로 같은 source/block 경계를 유지한다. 새 모델·검색/선택/청킹·출력 한도·자동 fallback·기본값 변경은 없다.

## 입력과 복원

`pack_reference_evidence(evidence)`는 v5 pack 결과를 바탕으로 evidence_sources와 block의 source_ref를 그대로 유지한다. `fragment_columns`는 evidence_ref,text,bbox,char_range,ordinal 순서로 고정하고 각 block의 rows는 같은 순서의 값을 가진다. text/Unicode/공백/숫자 정밀도/null/위치/파서 순서를 변경하지 않는다. block은 의미 관계가 아니라 파서 연속성을 나타낸다.

전체 요청의 evidence 순서대로 e1부터 연속 번호를 부여한다. UUID 중복 입력은 거절한다. 읽기 전용 ref→UUID map은 해당 요청에만 속하고 모델에는 보내지 않는다. 본문이나 주장 문장 속 문자열은 치환하지 않는다. `unpack_reference_evidence(pack)`가 v5 compact 자료 전체와 같아야 한다. 서로 다른 문서/버전/projection/chunk는 표시 메타데이터가 같아도 합치지 않는다.

v6 prompt와 JSON 안내에서 인용 식별자 표현만 수정하고 질문·규칙·조건·예시·거절·비신뢰 원문에 관한 내용 지침은 보존한다. question/resolved_query/history/delegated_task 역할도 유지한다. bbox·순서만으로 사실 관계를 추정하지 않는 규칙은 유지한다.

## 출력과 실행 경계

외부 응답 JSON schema2의 claims/evidence_ids 형태는 그대로다. v6의 evidence_ids에는 그 요청의 정확한 eN만 허용한다. JSON 중복 키·추가 키·status/claims 불일치 등의 기존 검증 이후 인용을 실제 UUID로 복원하고 기존 StructuredGeneration·인용 검증에 넘긴다. 미등록/비정규/중복 alias와 raw UUID 혼용은 실패이며 다른 요청의 map이나 공유 runtime 상태를 사용하지 않는다.

직접 HTTP 및 SDK specialist parser가 동일 request map을 사용한다. manager 동작·모델2회/도구1회·retry0·취소/종료 소유권은 유지한다. 모델 span은 실제 축약 입력/응답을 기록하고 agent/tool/final 결과는 복원한 UUID를 유지한다. 원문·최종 인용·현재 ACL 계약을 바꾸지 않는다. v6는 명시 evidence budget(max_units≤200), schema2, local HTTP 배포에만 허용한다. v5와 기존 저장 프로파일은 같은 입력 bytes/동작을 유지한다.

독립 설계 검토에서 과거 trace의 source refs만으로 실패·취소 시 eN 역매핑을 복원할 수 없음을 확인했다. 따라서 specialist model span에 선택적 `citation_reference_map`을 호출 전에 저장한다. format=rag-answer-v6와 최대200개의 고유 UUID 순서 목록이며 e1은 첫 UUID다. 모델 입력에는 보내지 않고 기존 private trace·현재 ACL 아래에만 둔다. metadata_only·실패·취소에서도 보존하고 시작한 span의 map은 변경할 수 없다. 과거 JSON은 None으로 읽으며 manager에 붙이지 않는다. 직접 HTTP의 최종 결과는 기존 canonical UUID 기록을 유지한다.

## 수용 조건

빈 근거·한 근거·다중 출처·같은 본문의 다른 UUID·비연속 순서·Unicode·bbox/null·참조처럼 보이는 본문을 검증한다. 순서/출처/본문/좌표의 왕복 동일성, 잘못된 map/alias 거절, 요청 동시성, direct/SDK·native/호환 경로, 과거 v5 byte 동일성과 인용·원문 조회를 독립 검증한다.

저장된 공개 합성 입력에는 오프라인으로 v5/v6 크기와 전체 정보 복원을 비교한다. 문자/byte 감소를 token·지연 감소로 취급하지 않는다. 실제 품질 동일성은 모델 실행 없이 보장하지 않는다. 구현·독립 검증을 마친 뒤 제한된 새 실모델 범위를 확인하고, 동일 질문·근거·설정의 답변/인용과 입력 token·시간을 비교한다. 퇴행이면 후보를 승격하지 않고 원래 v5를 유지한다. 직전4회 호출 예산은 소진됐으며 자동 연장하지 않는다.

추가 승인4회 실측에서 동일 질문의 두 답변·인용이 v5와 같았고 28근거의 전체 복원을 확인했다. 입력4691→3549토큰, 첫 입력 처리181.092→135.293초였으나 반복 전체 시간은 증가했다. 기존 정답0/2를 유지하고 운영 승격하지 않는다. 상세 결과와 잔여 병목은 [실측 기록](../worklogs/2026-10-26-rag-reference-packing.md)을 따른다.
