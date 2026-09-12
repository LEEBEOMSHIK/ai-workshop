# 통합 파일함·대화 범위·자산운용 PDF

## 요청과 작업 경계

- 파일함 방문 → 폴더 탐색 → 미리보기를 대화의 필수 순서로 만들지 않는다.
- 도메인 대화에서 공간, 폴더 또는 개별 파일을 검색 범위로 명시 선택한다.
- 기존 오류 수정 → 통합 설계 → 권한과 관리·동시 변경 → 형식별 통합 검증 순서다.
- 이번 경계는 오류 수정과 대화 범위 UX다. 이름 변경·이동·휴지통·복원은 서버 권한 및
  metadata revision/tombstone 계약과 함께 후속 구현하며 버튼만 먼저 노출하지 않는다.
- [승인된 상세 설계](../superpowers/specs/2026-09-13-unified-cabinet-design.md), ADR-0023,
  architecture/system-design 및 labs/rag/design을 연결했다.

## 역할과 판단

- 프론트 개발: 뷰어 승인 상태 수명주기와 대화 범위 UI 구현을 순서대로 담당한다.
- 요구 설계/RAG 책임/문서: 기존 API·검색 필터를 확인하여 공간/폴더/파일 계약을 구체화한다.
- 테스트·통합/독립 코드·권한 검증: 범위 자동 확대, 잘못된 버전 열람과 지연 응답을 검증한다.
- 메인 오케스트레이터: 문서 통합과 합성 PDF 제작·기존 파서/뷰어 검사·작업판을 담당한다.
- 현재 UI 단계는 DB·배포·모델 계약을 변경하지 않으므로 DBA·인프라·AI 런타임 구현은 배정하지 않는다.
  후속 쓰기/휴지통 단계에서 해당 역할과 데이터 이관 위험을 다시 분류한다.
- 사용자 지시에 따라 main에서 작업하며 기존 dirty 변경을 보존한다. 커밋·push·원본 삭제는 하지 않는다.

## 오류 수정

`LibraryViewer`의 기존 fetch mock 인자 타입 오류와 effect 내 동기 상태 갱신 린트 오류를 재현했다.
버전 변경 시 이전 승인 상태가 남거나 진행 중 승인 요청 때문에 새 버전 버튼이 잠기는 실제 결함도
회귀 테스트로 재현했다. 승인 UI를 버전별 keyed 컴포넌트로 분리하고 종료된 요청을 무효화했다.
관련 12개 테스트, 프론트 전체 typecheck/lint 통과. 독립 리뷰도 내부 수정은 통과했다.
독립 리뷰에서 발견한 대화 화면 원문 패널의 unkeyed 호출부도 공간/문서/버전 identity key와
다른 답변의 원문 버전 재선택 회귀로 보완했다.

## 대화 범위 구현과 검증

`ConversationPage`, `ScopeSelector`, `DocumentSelectionPanel`, `types`와 대응 회귀를 변경했다.
초기 전체 공간 자동 선택을 제거하고 공간·폴더·파일 모드를 분리했다. 공간·폴더 편집은 적용/취소되며,
파일 탐색/미리보기는 검색 범위를 바꾸지 않는다. 최초 무범위 상태에서도 파일 트리를 직접 열어
선택한 문서를 적용할 수 있다. 빈 선택은 전송을 차단하며 이전 폴더 제한을 전체 공간으로 바꾸지 않는다.
회사/개인 등 kind와 폴더 경로를 표시하고 폴더는 현재 직접 소속 문서만 포함한다고 안내한다.
적용한 범위 변경은 기존 transcript를 보존하면서 다음 요청의 history 및 전송 동의를 초기화한다.

독립 리뷰의 Important 두 건도 해결했다. 공간 해제 시 해당 폴더 draft를 함께 제거하고,
여러 공간의 폴더에서 한 공간의 파일만 고르면 요청의 workspace/folder/document 교집합을 맞춘다.
두 수정의 직접 회귀를 검토한 뒤 사양·품질 verdict 모두 통과, Critical/Important 잔여 0건이다.

```powershell
pnpm --dir frontend test --run src/features/rag/conversation/ConversationPage.test.tsx src/features/rag/conversation/DocumentSelectionPanel.test.tsx src/features/rag/domains/DomainFileCabinet.test.tsx src/features/assets/LibraryViewer.test.tsx --no-file-parallelism --maxWorkers=1 --testTimeout=20000
```

main 최종 결과: 4파일·54테스트 통과(63.03초). 앞선 병렬 실행에서는 5초 timeout 5건이 발생했다.
타임아웃을 통과로 계산하지 않았으며, 단일 worker·순차 파일·20초 제한으로 재검증했다.
기대값이나 권한/범위 assertion을 완화하지 않았다. main도 최종 소스의 `pnpm --dir frontend typecheck`와
`pnpm --dir frontend lint`를 재실행해 exit 0을 확인했다(린트 경고 0).
실제 로그인 브라우저 smoke는 도구 장애로 수행하지 못했다.

## 합성 PDF

- `sample-data/public/rag/asset-management-text-v1.pdf`: 3쪽 한글·표·벡터 카드.
- `sample-data/public/rag/asset-management-ocr-v1.pdf`: 4쪽, 3쪽 이미지 카드와 4쪽 전체 스캔.
- 정답·근거 페이지·검색 범위 검증표: 로컬 `sample-data/public/rag/asset-management-pdf-validation.md`.
  위 PDF와 검증표는 후속 사용자 요청으로 Git에서 제외하고 로컬에 보존했다. 새 clone에 포함되지 않는다.
- 생성기 `scripts/build_rag_asset_management_pdf.py`는 기존 PyMuPDF와 인자로 받은 글꼴을 사용한다.
  새 패키지나 별도 Python 환경을 만들지 않았다. `ruff check --no-cache` 통과.
- 전 페이지 시각 검토 완료. 두 파일 공통 1·2쪽은 렌더링 픽셀 동일성을 확인했다.
- 기존 `PdfParser`: 텍스트 PDF 65개 요소, 3개 페이지, 정답 수치와 모든 bbox 보존 확인.
- 기존 격리 프로세스 `PdfPreviewRenderer`: 두 파일 총 7쪽 실제 렌더링 성공.
- 텍스트 전용 파서는 스캔 자료를 `ocr_required`로 거절했다. OCR 미실행을 성공으로 숨기지 않는다.
- 파일은 사용자가 사용할 검증 자산으로 보존한다. 업로드·외부 전송 승인·모델 호출은 하지 않았다.
- 독립 읽기 리뷰에서 생성 내용·수치·페이지·검증 한계의 일치를 확인했다. 단독 환매 날짜 질문에는
  상품 식별자를 명시해 기대 답 D+4의 대상이 모호하지 않도록 보완했다.

## 남은 검증 경계

PDF 열람/텍스트 파싱 검사는 OCR 추론·색인·실제 LLM 답변·의미 하이라이트 검증을 대신하지 않는다.
XLSX는 현재 업로드/보관/다운로드와 별개로 RAG 파서가 없으며 지원 완료로 안내하지 않는다.
브라우저 도구의 sandbox helper 실행 실패와 구성 평가/도메인 미연결은 별도
[RAG 테스트 준비 기록](2026-09-13-rag-test-readiness.md)을 따른다.

## 후속 관리 기능의 선행조건

독립 백엔드 검토에서 Platform의 membership 기반 원문 접근과 RAG의 personal.created_by 검사 차이를
확인했다. Platform도 개인 소유자 조건을 일관되게 적용해야 한다. 회사의 read/write/delete는 현재
owner/member 역할만으로 구분되지 않으므로 capability 및 명시 권한 이관 계약이 먼저 필요하다.
휴지통은 기존 Asset→Document 잠금 순서와 worker 복구/활성화 전 경로를 함께 검증한 뒤 제공한다.

기존 정확한 local DB guard를 사용하는 READ ONLY 트랜잭션으로 영향 건수만 확인했다.
타인 personal membership 0건, personal 생성자 owner 누락 0건, 회사 member 권한 매핑 대상 0건이다.
현재 다른 사용자의 개인 자료가 노출됐다는 증거는 아니며, 향후 잘못된 membership을 통한 접근을
차단할 선행 보완이다. 문서 본문·자격정보를 조회/출력하거나 DB·권한·승인을 변경하지 않았다.
실제 이관 직전에는 건수를 다시 확인해야 한다. 현재 18000 및 5173 `/api/v1/health`는 200이다.
