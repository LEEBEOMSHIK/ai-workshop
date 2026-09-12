# 로컬 정합성 복구 및 실제 큐 검증

## 복구

- 승인된 합성 테스트 DB 41행을 하나의 트랜잭션에서 정리했다.
- 삭제 전후 모든 비대상 행의 count·내용 해시 동일, 외부 UUID·직렬화 참조 0을 확인했다.
- 정상 alias reconciler는 7/7, failed 0을 두 차례 확인했다.
- 독립 읽기 전용 검증에서 fixture 부재, 공유 프로파일·모델 보존과 새 worker·beat 로그의
  정합성 오류 부재를 확인했다. 웹 및 API health는 200이다.
- 상세 범위와 백업은 [복구 조사](2026-09-07-local-alias-integrity-audit.md)를 따른다.

## 실제 큐 검증 설계

`backend/tests/e2e/test_rag_mixed_pdf_actual.py`에 opt-in 실제 큐 모드를 추가했다.
고유 DB, ES 접두사, 객체 저장소, Redis keyprefix와 queue를 사용한다. 사용자 서비스는
중단하거나 설정을 변경하지 않는다. 별도 Windows host worker는 eager 실행을 금지하고,
검증 종료 시 전용 worker 종료를 확인한 후 고유 Redis 키·ES 색인·DB를 정리한다.

검증 경로는 업로드 API → Redis/Celery 파일 검증 → ingestion service command/outbox →
Redis/Celery OCR·색인 → 검색 API → 원문 뷰어 API다. 관리자 구성 UI 조작을 대신하지 않는다.

## 실행 증거

- 실제 큐 첫 실행: 1 passed, 6 warnings, 122.60s.
- 합성 혼합 PDF 2페이지에서 실제 PP-StructureV3·E5·Elasticsearch를 사용했다.
- BM25/Hybrid 4검색, 의미 검색 1건, OCR 근거·페이지·bbox·의미/키워드 하이라이트,
  PNG 원문 이미지, 비로그인 원문 접근 401을 검증했다.
- 독립 코드 리뷰에서 큐 격리·실제 전달·정리 경계에 차단 사항이 없음을 확인했다.
- 원문 뷰어 프론트 테스트: 6 passed in 3.53s.
- 추가 전체 실행에서 기능 assertion은 통과했으나 Windows `taskkill` 종료 단계가 실패해
  전체 pytest 결과는 1 failed, 6 warnings, 260.70s였다. 성공한 실행으로 기록하지 않는다.
  그 실행의 OCR task는 207.286s였고 첫 실행은 66.904s였다. CPU 실행 지연을 관측했지만
  모델 교체나 timeout은 없었다.
- 테스트 전용 프로세스를 별도로 정리하고 임시 DB·ES 색인·Redis 키·전용 worker 잔여 0을
  확인했다.
- 최종 코드는 고유 Redis keyprefix·정확 hostname을 대상으로 정상 shutdown을 요청하고
  30초 내 종료를 기다린다. 제한 시간 초과는 성공으로 숨기지 않고 실패한다.
  이 최종 코드의 별도 실제 lifecycle 실행은 exit 0이며 worker 부모·자식 0,
  Redis namespace 0을 확인했다. 독립 최종 리뷰에서 종료 보장 관련 P2가 해소됐다.
- 최종 파일 Ruff 통과. 최종 shutdown 코드로 전체 OCR을 다시 실행한 것은 아니므로
  첫 전체 성공, 중간 teardown 실패, 최종 lifecycle 성공을 각각 별도 증거로 유지한다.
- 마지막 임시 파일은 `C:\projects\ai-workshop\.local-data\project-agent-work\local-alias-recovery`
  아래 14파일·7,911,537bytes다. 생성 파일·합성 백업 삭제 승인을 사용자에게 요청했다.
  사용자 원본, 모델, 자동 테스트 소스와 공식 검증 문서는 삭제 대상이 아니다.

## 사용자 확인 준비

로컬 `/workshop/workspaces`에서 업로드하고 `/workshop/rag/search`에서 검색·원문 근거를
확인할 수 있다. 혼합 PDF의 그림 OCR을 확인할 구성은 문서 처리 `pp-structure-v3-pdf-docx`
v2(`pymupdf-ocr` v2)를 사용해야 한다. 이전 처리 결과를 새 OCR 결과로 간주하지 않는다.
외부 LLM과 실제 브라우저 조작까지 검증 완료한 상태는 아니다.

초기 테스트 실행의 Windows MAX_PATH와 subprocess 작업 디렉터리 문제는 검증 코드에서
짧은 객체 경로와 저장소 root cwd로 해결했다. 제품 코드나 모델을 바꿔 우회하지 않았다.

## 검증 제외

- 실제 브라우저 클릭·시각적 하이라이트 정밀도는 이번 API/컴포넌트 검증과 다르다.
- 외부 LLM API 호출과 최종 생성 답변 품질은 이번 검색·OCR 검증에 포함하지 않는다.
- 별도 Linux 운영 환경 검증은 수행하지 않았다.
- 기존 통합 테스트 전체의 로컬 데이터 격리 강제는 후속 항목이다.
