# 임베딩 의존성 import 실패의 오류 계약 보완

## 선정과 범위

WORKBOARD의 RAG 안정화 우선순위 및 native import 실패의 오류 상태 회귀 후보에서
임베딩 어댑터의 오류 분류 누락 한 건을 선택했다. 최신 기록의 v4·구조 선택·입력 확인은
이미 구현된 범위로 취급했으며 다시 구현하지 않았다. 작업 상태 도구에는 로컬 모델
평가를 준비하는 활성 작업이 관측되어 평가·프로파일·도메인 연결을 변경하지 않았다.

Python 백엔드·AI·RAG 역할은 메인 구현 담당이 수행하고 독립 코드 리뷰어는 읽기 전용으로
검증했다. UI·DB·배포·권한 정책 변경은 없어 해당 구현 역할은 제외했다.

## 원인과 수정

`SentenceTransformerEmbedding`의 토큰 계산·문서 임베딩·질의 임베딩은 기존에
`OSError`와 `RuntimeError`만 `EmbeddingRuntimeUnavailableError`로 변환했다.
의존성 import 또는 지연 실행 중 발생한 `ImportError`와 하위 `ModuleNotFoundError`가
이 계약 밖으로 전파되는 것을 합성 loader/encoder 테스트 10개로 재현했다.

세 예외 처리 경계에 `ImportError`를 추가했다. 고정된 안전한 메시지와 원인 예외를
유지하며 자동 재시도·모델 대체·다운로드는 추가하지 않는다. 기존 프로그래밍 오류와
벡터/토큰 검증 오류는 그대로 전파한다. 기존 미커밋 `close()` 구현도 보존했다.
실제 DLL 차단의 원인을 제거하거나 보호 설정을 바꾼 수정이 아니다.

## 실행한 검증

기존 `backend/.conda/python.exe -X utf8 -B`로 backend 디렉터리에서 실행했다.
모든 pytest는 `--tb=short`와 작업 전용 고유 `--basetemp`를 사용했다.

- 수정 전 adapter `-k import_failure`: 10 failed / 19 deselected. 예상한 미변환 예외 재현.
- 수정 후 embeddings 전체: 62 passed / 0.23초.
- tokenizer 지연 import 2건과 실제 query wrapper 연결 2건 추가 후:
  `-m pytest tests/unit/labs/rag/embeddings tests/unit/labs/rag/retrieval/test_query_embedding.py tests/unit/labs/rag/chunking -q`: **87 passed / 1.36초**.
- 독립 리뷰: adapter·query wrapper·highlighting context 최종 **52 passed / 1.30초**, 차단 지적 없음.
- `-m mypy src/ai_workshop/labs/rag/embeddings/sentence_transformers.py --follow-imports=silent`: strict 설정, **1 source file 성공**. 캐시는 작업 폴더에 지정.
- `-m ruff check src/ai_workshop/labs/rag/embeddings/sentence_transformers.py tests/unit/labs/rag/embeddings/test_sentence_transformer_adapter.py --no-cache`: 통과.

최초 pytest는 기본 sandbox Temp의 디렉터리 생성 오류로 10건 setup error였다.
저장소 내 쓰기 가능한 작업 폴더에 새 basetemp를 지정한 후 의도한 실패 재현과 검증을 진행했다.
이 환경 오류를 제품 실패나 통과로 집계하지 않았다.

## 보존과 남은 검증

시작 시 Git 상태 183개 변경 항목과 Git에 보이는 기존 파일 1,974개의 SHA-256을 기록했다.
기존 미커밋 소스·테스트·WORKBOARD의 원본은
`.local-data/project-agent-work/embedding-import-error-20261017/`에 보존했다.
쓰기 직전 제품 원본과 WORKBOARD를 비교했으며 기존 변경을 되돌리지 않았다.

실모델·임베딩 호출, DB/Elasticsearch 변경, 서비스 시작·종료·재기동, migration,
commit/push는 모두 0회다. 전체 pytest·실 DB/ES 통합·브라우저·실제 DLL 실패/복구와
운영 반영은 수행하지 않았다. 실행서상 전체 pytest를 실사용 환경으로 실행하지 않는다.
관리자 문제 이력은 인증된 관리 API의 DB 반영이 필요하므로 이번 기록은 등록 대기 근거다.
과거 ISSUE-00013의 현재 DB 상태나 revision은 이번에 재확인하지 않았다.

다음 후보는 기존 승인과 정상 인증 경로를 갖춘 범용 v4 후보의 정식 양성·음성 평가다.
현재 호출 가능한 도구에 인증된 사용자 브라우저 제어 기능이 없어 이번에는 후보 생성·
평가 제출·도메인 활성화를 실행하지 않았다. 코드/오프라인 통과로 평가 통과를 대체하지 않는다.
별칭 복구·첫 질문/권한·취소·실모델 종료·본래 환경 인계 순서는 유지한다.

## 정상 UI 인계 준비

부모의 후속 요청에 따라 모델·구성·평가·도메인 화면의 경로와 실제 버튼명을 코드에서
확인했다. 기존 공개 합성 기준 구성/프로파일/평가 메타데이터는 read-only 트랜잭션으로
조회하고 rollback했다. 최초 제한 환경 조회는 연결 오류였고 공식 권한 검토를 거친
읽기 조회는 성공했다. 중간 `retrieval_k` 열 조회 오류는 실제 저장 구조의
`snapshot.retrieval_k`로 정정했으며 DB 변경은 없었다.

로컬 인계 파일은 [정확한 UI 단계](../../.local-data/project-agent-work/embedding-import-error-20261017/candidate-ui-handoff.md)와
[붙여 넣을 후보 YAML](../../.local-data/project-agent-work/embedding-import-error-20261017/gemma-v4-candidate.yaml)이다.
YAML은 실제 API 입력 parser로 형식 검증했으나 등록하지 않았다. 기존 프로파일 대비
설정 변화는 prompt_ref v2→v4 한 개이며 reasoning none·retry0와 나머지 한도를 보존한다.
간편 HTTP 폼은 reasoning 설정을 전송하지 않아 고급 YAML 경로를 안내했다.
구성 폼 초기 semantic score0.7 대신 기존0.9를 유지해야 하고, 평가 자료 불러오기는
이전 정답 문자열 규칙을 복원하지 않아 양성의 `4`·`영업일`을 다시 입력해야 한다.

현재 사용자의 최소 UI 동작은 생성 프로파일 등록까지다. 후보 RAG 구성은 아직 없으며,
평가·통과 반영·연결 활성화는 각각 후속 단계다. 이번 생성/임베딩 호출0회,
승인된 정식 평가 생성 예산4/4와 통과 후 입력 확인1/1을 모두 보존했다.
최종 보존 검사에서 기존1,971파일의 SHA가 그대로였고 수정 소스·테스트의 이전 내용도 보존됐다.
