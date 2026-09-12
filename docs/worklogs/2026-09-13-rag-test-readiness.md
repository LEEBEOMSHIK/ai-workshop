# 분류 안내 및 RAG 테스트 준비 후속

사용자 승인: 분류 기준 안내 보완과 구성 평가·도메인 활성화 진행.
main의 기존 변경을 보존했다. 프론트 담당과 RAG/독립 검토를 분리했다.

## 반영한 변경

- CodexEvidenceApproval.tsx: 공개/합성 정의와 겹칠 때의 선택 기준, 자동 익명화·사이트 공개·
  AI 자동 실행이 아니라는 설명을 추가. useId/aria-describedby로 선택란에 연결했다.
  이미 승인된 문서도 취소 없이 설명을 읽을 수 있다. 기존 동의/승인/API 계약 유지.
- CodexSetup.test.tsx: 복수 문서별 접근성 연결, 선택만으로 승인되지 않음,
  승인 완료 문서에서도 안내가 보이는 회귀 검증.
- 관련 테스트15건 main 재실행 통과, 담당자의 변경 파일 ESLint 통과.
  전체 typecheck는 기존 LibraryViewer.test.tsx 272/315/396행 오류,
  전체 lint는 기존 LibraryViewer.tsx 82행 오류로 통과하지 않았다. 이번 범위 밖 변경은 보존했다.

## 실행 환경 복구

API18000과 ES 단일 노드는 응답했지만 Redis6379는 연결 거절 상태였다.
프로젝트 Redis 컨테이너가 Exited255이고 Python은 API만 실행 중임을 확인했다.
기존 ai-workshop-redis-1을 시작했으며 새 이미지/컨테이너는 만들지 않았다.
확인 당시 celery 큐0, 평가 실행0, jobs는 succeeded5/failed1로 실행 중 작업은 없었다.

기존 root.env·정확한 로컬 DB 설정의 호스트 Celery worker/beat를 숨김으로 실행했다.
실행기 `.local-data/project-agent-work/document-transfer-reapproval/serve-worker.py`.
launcher worker30572/beat25436, worker solo/concurrency1.
로그 `.local-data/dev-logs/rag-ready-20260913-{worker,beat}.{out,err}.log`.
Redis ping true, 작업자 ai-workshop-local ping pong, 프론트5173 경유 API health ok를 확인했다.
실제 프론트/백엔드는 계속 호스트 실행이다.

## 완료하지 못한 검증과 다음 순서

브라우저 제어 두 번 및 대체 node_repl 연결도 도구 프로세스 실행 오류로 실패했다.
`orchestrator_helper_launch_failed`, `codex-windows-sandbox-setup.exe ... program not found`.
앱 로그인 실패와 구분하며 인증정보 추출이나 세션 발급으로 우회하지 않았다.
현재 평가 실행0·도메인 연결0이다. 사용자 승인된 합성 문서 상태를 바꾸지 않았고 모델 호출도 없다.

복구 후 관리자 `/admin/rag/configurations` → `비교 실험`에서:

1. 정확한 RAG-TEST v2와 합성 참조 자료 공간·문서 버전 선택 → 근거 조회.
2. 제공된 문서의 정답 근거/하이라이트가 있는 질문과 문서에 없는 정보 질문을 작성.
   수동 기대값과 통과 기준은 관측 점수에 맞춰 낮추지 않는다.
3. 보관 동의와 최초 실행 → 정책 저장 → 정책 적용 재실행 → 정확한 버전 평가 통과 반영.
4. 기존 자산운용 도메인에 해당 구성·합성 공간 연결 → 활성화.
5. 실제 대화에서 Codex 답변·인용·하이라이트·후속질문을 별도로 확인.

현 EvaluationWorkerSearch는 HybridRetrievalService/로컬 임베딩/EvidenceSelector를 사용하며
LLM 생성을 호출하지 않는다. 평가 통과를 LLM 답변 품질 검증 완료로 표현하면 안 된다.
시스템 BM25 비교와 같은 처리/색인 호환 조건, PASSED·generative·service_ready 활성화 gate 유지.
실제 전체 RAG 테스트 준비 완료를 주장하지 않는다.

## 후속 파일함 작업

같은 날 [통합 파일함 후속](2026-09-13-unified-cabinet.md)에서 위 LibraryViewer 타입/린트 오류와
승인 UI 버전 전환 결함을 수정했다. 해당 오류를 현재 미해결 차단 원인으로 재사용하지 않는다.
대화 범위 UX와 합성 PDF 검증은 별도로 진행하며, 구성 평가·도메인 연결·실제 LLM 검증을 대체하지 않는다.
