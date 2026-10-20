# 구조 기반 문맥 후보 선택 — 2026-10-16

## 승인 범위와 사전 설계

직전 [업체 호환성 감사](2026-10-16-rag-company-portability.md) 뒤 사용자가 승인한 최소 opt-in 구현이다. RAG P0 안에서 기존 문맥 선택 함수에 제한된 경로를 추가한다. API·프로파일·DB·색인·파서 계약과 활성 동작은 바꾸지 않으므로 새 공개 계약/모듈 경계 변경이나 재색인은 없다. 실제 호출·설치·서버 변경·보안 변경·commit/push는 하지 않는다. 이전 모델 시험 예산은 재사용하지 않으며 새 시험은 승인 대기다.

기존 `payment_table_units`는 환매/지급 질문·행 이름을 인식하고 상품 헤더를 찾아 다른 열을 제거한다. 참조를 놓치지 않기 위해 `같은` 등의 어휘에서 투영을 거절한다. 동의어 사전을 확장하면 업무 의존성이 계속 증가하고, 언어 모델로 관계를 추정하면 비용·의미 검증 범위가 커진다. 이번에는 원문 구조의 제한된 관측만 사용하며 **청크 전체를 보존하는 후보 선택**으로 범위를 좁힌다.

- `select_context(..., table_strategy="structure-v1")`의 명시적인 Python 호출만 opt-in한다. 기본값은 기존 `payment-v1`; API/프로파일에 연결하지 않는다. 미지정 호출과 기존 생성 프롬프트는 그대로다. 알 수 없는 전략은 오류로 처리한다.
- 새 순수 검사기는 명시적 셀 행/열 좌표 또는 엄격히 정렬된 bbox 격자를 검사한다. 셀 좌표에도 table ID가 없고 native PDF bbox는 텍스트 span이므로 **청크 안의 격자 후보**일 뿐 실제 전체 표/헤더/규칙 의미를 확정하지 않는다. OCR 좌표도 bbox 정합과 출처 범위를 검사한다.
- PDF 단일 출처 범위에서 관측된 셀의 중복·병합·중간 좌표 누락·겹침 없는 사각 격자를 요구한다. 관측 subset 안의 검사이며 전체 표 완전성 검사는 아니다. 모호/구조 없음/불완전 원문은 명시적 진단을 남기고 기존 일반 keyword/semantic/qualified-evidence 선택으로 넘긴다. opt-in에서 환매 전용 투영은 사용하지 않는다.
- 질문에 격자 셀의 전체 원문이 문자 경계와 함께 일치하면 후보로 삼는다. NFKC·대소문자·공백만 정규화하며 숫자만인 셀은 앵커로 쓰지 않는다. 업체 이름·상품·행 의미·동의어·한국어 조사 사전을 추가하지 않는다. 일치 실패는 질문에 답이 없다는 의미가 아니다.
- 모든 행/열·제목·주변 본문·주석·교차참조를 원래 Evidence 객체와 순서로 보존한다. `같은 조건`, `참조`를 해석하거나 거절어로 쓰지 않는다. 문서 밖 참조를 가져오거나 인접 문장을 적용 조건으로 연결하지 않는다.
- 기존 그룹/단위/문자 예산·conflict anchor 보호를 그대로 적용한다. 넘치면 전체 후보를 거절하며 잘라내지 않는다. 표를 전부 보존하므로 기존 32-unit 예산에서 33-unit 청크가 거절될 수 있다.

성공 기준은 업무 어휘 없이 관측 격자 후보를 선택하고 원문을 보존하며, 구조 모호성·예산·기존 동작 보존을 오프라인에서 재현하는 것이다. 규칙 존재/상충 해결/근거 충분성/실제 답변 품질은 성공 기준에 포함시키지 않는다. 업체 tenant 격리는 별도 미해결 사항이다.

## 실행 결과

### 알고리즘 변경

- 신규 `backend/src/ai_workshop/labs/rag/highlighting/structural_context.py::inspect_grid_candidate`는 `eligible/reason`만 반환한다. 표 제목/헤더/값의 의미 역할을 새로 만들거나 답을 생성하지 않는다. 정렬된 bbox 행·열과 있는 경우 `TableCellLocation`의 순서·단일 셀 span·출처 범위를 검사한다. 좌표가 부분적이거나 충돌하면 bbox 경로로 조용히 재해석하지 않는다.
- 기존 `highlighting/context.py::select_context`에 내부 keyword-only `table_strategy`를 추가했다. 기본 `payment-v1`은 유지하고 `structure-v1`에서만 새 검사기를 사용한다. 알 수 없는 전략은 ValueError다. 새 후보는 모든 원문 객체를 유지한 채 기존 순위·예산·conflict anchor 검사를 통과한다.
- `CandidateDiagnostic.structure_reason`에 구조 관측 이유를 보존한다. `reason`은 실제 선택/일반 fallback/예산 거절을 표시한다. 새 필드는 내부 Python 진단이며 API/DB 스키마에는 연결하지 않았다.
- 전부 부적격인 source는 원문/근거 ID를 반환하지 않고 `structural_context_incomplete_source` 경고를 남긴다. 유효한 다른 source가 있어도 경고를 유지하며 진단 임베딩 오류가 함께 나면 두 코드가 쉼표로 구분되어 남는다. 기본 경로의 경고 형식/동작은 그대로다.

제품 호출부에서 `structure-v1`을 지정하는 코드는 없다. 시험은 `select_context`를 명시 호출한다. 활성 프로파일, 기존 환매 함수, 생성 프롬프트, source_reading, 파서, 색인, 권한 코드는 변경하지 않았다. **프롬프트 개선이 아니라 순수 Python 후보 선택 변경**이다.

### 테스트와 기존 경로 비교

신규 `backend/tests/unit/labs/rag/highlighting/test_structural_context.py` 47개는 다음을 검사한다.

- 다른 업체를 가정한 용어·값, 셀 좌표 유무, 열 순서·표 전치, bbox 이동/배율·입력 순서 변경에도 원문을 parser ordinal 순서로 보존한다.
- 주석, `같은 조건`, 다른 열/다른 페이지 참조, 상충 문장, 질문이 묻는 규칙이 없는 입력을 삭제/연결/답변으로 변환하지 않는다. 생성 payload까지 원문과 위치를 그대로 전달하는 것을 확인한다.
- 부분 이름·조사가 붙은 이름·숫자·의역만으로 구조 경로를 승격하지 않는다. 단 `23`이 기존 keyword 기준을 충족하면 일반 경로로 선택될 수 있으며 두 진단을 구별한다.
- 셀 누락·중복 좌표·병합·좌표 gap·bbox 겹침/비정렬/NaN, 다른 page/part/image, 일부 provenance 제거, 나뉜 격자, 구조 없음·비PDF 입력을 검사한다.
- 청크 전체가 단위/문자 예산을 넘으면 주석이나 다른 열을 잘라내지 않는다. 이미 알려진 conflict 근거가 누락되면 기존 blocked 결과를 유지한다.
- 같은 질문 `ORCHID-71 현금화하면 돈은 며칠 뒤 받을 수 있어?`에서 기본 경로는 기존대로 28단위, 새 경로는 33단위 전부를 유지한다(시험 예산 64). 기본 호출과 명시 `payment-v1` 결과도 동일하다. 예산 32에서 새 경로의 성공을 주장하지 않는다.

처음에는 새 모듈 부재로 테스트 수집 실패를 확인한 뒤 구현했다. 이후 숫자 질문 `23`에 대해 일반 keyword fallback도 없을 것이라는 테스트 기대가 틀려 1실패했고, 제품 정책을 바꾸지 않고 구조/일반 경로를 구별하는 테스트로 바로잡았다.

독립 리뷰에서 **P2: 모든 bbox가 없을 때 진단까지 사라지는 조기 반환**을 발견했다. 전체 필터와 유효 source 혼합 2개를 각각 실패 재현한 뒤 opt-in 안전 경고를 추가했다. 독립 재검토에서 수정과 기본 경로 보존을 확인했으며 남은 차단 결함은 없었다. 이 작업 중 발견·수정 내역은 여기 기록하고 별도 운영 DB 문제 이력을 쓰거나 기존 ISSUE-00013을 닫지 않았다.

### 실제 실행한 검증

기존 `backend/.conda/python.exe -X utf8 -B`만 사용했다. 모델·네트워크·DB·ES 실행 없이 mock 임베딩/보존 fixture로 실행했다.

| 검증 | 실제 결과 |
|---|---|
| 신규 테스트 | 47 passed / 2.28초 |
| 최종 관련 pytest 회귀 | 296 passed / 10.28초 |
| 독립 신규·기존 context/table/stored-table 4파일 | 141 passed / 6.11초 |
| 독립 구조 부재+진단 임베딩 실패 보충 assertion | 2개 통과 |
| Ruff 제품2·신규 테스트1 | 통과 |
| Mypy 제품2·신규 테스트1 | `--strict --follow-imports=silent --explicit-package-bases`, `MYPYPATH=src`로 3파일 통과 |

Mypy 기본 import 추적 실행은 결과 없이 지속되어 해당 도구 세션만 중단했고 통과로 집계하지 않았다. 이후 변경 파일에 한정한 위 검사가 통과했다. 최초 테스트 타입/린트 오류는 테스트의 untyped fixture 경계, 타입 선언·import 형식을 수정했다. 전체 프로젝트 Mypy 통과 주장은 하지 않는다.

재현 명령(backend 디렉터리, pytest 기본 cache 비활성 설정 유지):

```powershell
.conda/python.exe -X utf8 -B -m pytest tests/unit/labs/rag/highlighting tests/unit/labs/rag/generation/test_company_portability.py tests/unit/labs/rag/generation/test_source_reading.py tests/unit/labs/rag/generation/test_source_reading_mock.py tests/unit/labs/rag/generation/test_http_evidence_groups.py tests/unit/labs/rag/evaluation/test_offline_rubric.py tests/unit/labs/rag/search/test_diagnostics.py -q
```

초기 diff/status와 1,411개 파일 해시, RED/회귀 XML은 `.local-data/project-agent-work/rag-structural-context-20261016/`에 보존한다. 원래 존재하던 파일에서는 이번 변경 대상 context.py·WORKBOARD만 바뀌었고 나머지 1,409개 해시가 동일하다. 새 파일은 검사기·테스트·이 기록이다. 독립 리뷰 최종 SHA: 검사기 `40a16be58e4a73f93cea99c856da8c01943e52bb7a16a6ff2c7dadb68ab76cc2`, context `6d61529b70168e1220a6aafc417a70b2d93a735438bf2dfe6bd7e16407c220d9`, 테스트 `6ca9c6158454aa48a0ef9b24e6167567ece775011e4933a949941c5c2f2ff462`.

## 남은 한계와 다음 후보

- **실제 품질 미검증:** 근거 후보 보존은 모델이 일반 규칙·조건을 정확히 답한다는 증거가 아니다. 입력량 증가와 지연·오답·유보율을 측정하지 않았다. 실제 모델 호출 0회이며 추가 시험 2회 제안은 승인 대기다.
- table ID가 없으므로 잘린 표라도 직사각형인 부분은 후보가 될 수 있다. 세로로 분리된 두 표가 같은 열에 정렬되고 사이에 본문이 없으면 하나의 관측 격자로 보일 수 있다. bbox가 정렬된 목록일 수도 있다. 이 경우에도 전체 청크만 보존하며 표 의미·완전성을 주장하지 않는다.
- 원문 title/주석 텍스트는 보존하지만 그 역할·적용 대상은 판정하지 않는다. 다른 청크/페이지의 주석·참조 대상을 찾지 않으며 원문 밖 관계를 보완하지 않는다.
- 엄격한 bbox 정렬·셀 span1만 지원하므로 다양한 글자 높이, 병합 셀, 줄바꿈 셀, 여러 격자, OCR 오차는 구조 경로를 통과하지 못할 수 있다. 일반 점수 경로의 성공/실패는 별개다.
- 실제 통합 지원은 PDF 한정이다. native DOCX에는 필요한 셀 좌표가 없고 DOCX OCR은 기존 provenance 검사에서 page 없는 bbox가 제외된다. 이 검사를 완화하지 않았다.
- `T+2`, `10시`, 일반 단어도 문자 포함 셀로 일치할 수 있다. 반대로 조사 붙은 이름이나 동의어·의역은 일치하지 않을 수 있다. 이는 어휘 사전 대신 택한 literal candidate 방식의 한계이며 자동 의미 이해가 아니다.
- 업체 tenant 격리, 실제 DB/ES ACL 동기화, 본래 환경의 RAG P0 마감은 별도로 남는다. 모델 예산 재승인, 설정 변경, 배포·재시작·commit/push는 하지 않았다.

다음 후보는 저장된 실제 구조에서 이 opt-in의 선택/거절·입력량을 **모델 호출 없이** 비교해 적용 범위를 좁히는 것이다. 모델 품질 비교는 별도 승인된 입력/예산 아래 진행해야 한다. 파서의 table identity나 더 넓은 셀 구조를 추가한다면 파싱·색인 호환성과 설계를 별도 검토해야 하며 이번 변경의 성공으로 대체하지 않는다.
