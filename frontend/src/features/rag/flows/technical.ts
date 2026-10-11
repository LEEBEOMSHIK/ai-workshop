import type { FlowPhase } from "../../flowcharts/types";

export const ragFlowPhases = {
  ingestion: [
    {
      id: "original", title: "원본 저장·무결성 확인",
      summary: "파일을 안전하게 저장하고 현재 문서 버전을 정합니다.",
      nodeIds: ["upload", "asset"],
      technical: {
        components: [
          { name: "Platform Assets·ObjectStore", role: "원본 바이트와 변경하지 않는 파일 버전을 보관합니다." },
          { name: "검증 Job", role: "저장된 크기와 SHA-256 지문이 업로드한 원본과 같은지 확인합니다." },
        ],
        mechanism: [
          "원본을 STORED로 저장한 뒤 worker가 실제 저장 객체의 크기와 지문을 검증합니다.",
          "검증된 Asset Version만 READY로 전환하고, 버전 순서에 따라 현재 원본 포인터를 같은 트랜잭션에서 갱신합니다.",
        ],
        checks: ["무결성 불일치가 나면 READY와 현재 원본을 갱신하지 않습니다.", "원본 READY는 파일 보관 완료이며 RAG 검색 준비 완료와 구분합니다."],
        references: [
          { title: "원본 검증 작업", reference: "backend/src/ai_workshop/platform/assets/tasks.py" },
          { title: "원본·검색 준비 수명주기", reference: "docs/labs/rag/design.md" },
        ],
      },
    },
    {
      id: "dispatch", title: "색인 작업 예약·전달",
      summary: "필요한 프로파일의 작업을 만들고 백그라운드 처리로 넘깁니다.",
      nodeIds: ["demand", "waiting"],
      technical: {
        components: [
          { name: "프로파일 구독·멱등 command", role: "같은 원본 버전과 색인 프로파일의 중복 작업을 방지합니다." },
          { name: "outbox·Celery worker·beat", role: "DB의 전달 기록을 worker로 보내고 주기적으로 누락 전달과 색인 수요를 복구합니다." },
        ],
        mechanism: [
          "현재 READY 원본과 구독을 확인해 원본·프로파일별 작업을 예약합니다. outbox는 아직 전달해야 할 작업의 영속 기록입니다.",
          "worker가 실제 처리를 수행하고 beat가 전달·수요 점검을 예약합니다. broker 전달 실패는 재시도 시점과 안전한 오류를 기록합니다.",
        ],
        checks: ["각 단계에서 같은 활성 원본인지 다시 확인해 늦은 이전 버전 작업을 막습니다.", "작업 대기나 worker·beat 중지를 검색 완료로 표시하지 않습니다."],
        references: [
          { title: "색인 수요 인계", reference: "backend/src/ai_workshop/labs/rag/ingestion/handoff.py" },
          { title: "전달·재시도", reference: "backend/src/ai_workshop/labs/rag/ingestion/dispatch.py" },
        ],
      },
    },
    {
      id: "structure", title: "문서 구조·원문 위치 추출",
      summary: "문장을 꺼내면서 페이지·문단·표·이미지의 출처를 함께 남깁니다.",
      nodeIds: ["parse"],
      technical: {
        components: [
          { name: "형식별 parser·Document Processing Profile", role: "Markdown·TXT·PDF·DOCX를 설정된 경로로 읽어 공통 문서 구조로 바꿉니다." },
          { name: "OCR·provenance", role: "설정된 이미지 문자 인식과 원문 위치 정보로 추출 내용의 출처를 보존합니다." },
        ],
        mechanism: [
          "불변 처리 프로파일의 parser 경로를 검증하고 원본을 읽습니다. OCR이 구성된 PDF나 DOCX 내장 이미지는 문자 인식 결과를 구조 요소에 연결합니다.",
          "provenance는 원본 버전·구조 요소·문자 범위와 가능한 페이지·좌표·표 셀 위치를 묶어 이후 원문 뷰어까지 추적하게 합니다.",
        ],
        checks: ["지원하지 않는 형식이나 선택한 parser·OCR 실패를 다른 처리기로 조용히 대체하지 않습니다.", "요소의 부분 실패와 낮은 인식 품질을 완전한 정상 문서와 구분합니다."],
        references: [
          { title: "파서 선택과 실행", reference: "backend/src/ai_workshop/labs/rag/parsing/service.py" },
          { title: "파서·OCR 구성", reference: "backend/src/ai_workshop/labs/rag/ingestion/tasks.py" },
          { title: "원문 위치 모델", reference: "backend/src/ai_workshop/labs/rag/documents/provenance.py" },
        ],
      },
    },
    {
      id: "index", title: "청크·벡터·검색 색인 만들기",
      summary: "문서를 검색할 단위로 나누고 단어와 의미로 찾을 준비를 합니다.",
      nodeIds: ["chunk", "index"],
      technical: {
        components: [
          { name: "구조 청킹", role: "제목·문단·표 등 문서 구조를 고려해 검색 단위인 청크를 만듭니다." },
          { name: "임베딩 어댑터", role: "구성된 모델로 청크의 의미를 숫자 벡터로 변환합니다." },
          { name: "Elasticsearch 색인 어댑터", role: "청크 텍스트와 벡터를 저장해 BM25·dense 검색을 지원합니다." },
        ],
        mechanism: [
          "청크에 원문 근거 단위와 위치를 유지하고, 색인 프로파일에 맞는 모델·차원으로 임베딩을 생성합니다.",
          "청크와 벡터 산출물을 저장한 뒤 Elasticsearch의 준비 색인에 기록합니다. 청킹·임베딩 변경은 호환되는 새 색인 버전으로 처리합니다.",
        ],
        checks: ["벡터 차원과 청크 수가 해당 프로파일·build의 기대값과 맞아야 합니다.", "실행 중 현재 원본이 바뀌거나 모델이 실패하면 이전 작업을 정상 활성화하지 않습니다."],
        references: [
          { title: "구조 청킹", reference: "backend/src/ai_workshop/labs/rag/chunking/service.py" },
          { title: "임베딩·색인 단계", reference: "backend/src/ai_workshop/labs/rag/ingestion/stages.py" },
          { title: "Elasticsearch 색인", reference: "backend/src/ai_workshop/labs/rag/indexing/elasticsearch.py" },
        ],
      },
    },
    {
      id: "readiness", title: "검색 준비 검증·상태 확정",
      summary: "검색에 쓸 수 있는 완성된 색인만 활성화합니다.",
      nodeIds: ["verify", "ready", "failed"],
      technical: {
        components: [
          { name: "ReadinessVerifier·RAG Projection", role: "청크·벡터·출처가 완성됐는지 확인하고 검색 준비 상태를 관리합니다." },
          { name: "alias journal·유지보수 gate", role: "검색 별칭이 가리키는 실제 색인과 미종료 변경 요청을 확인합니다." },
        ],
        mechanism: [
          "청크·임베딩·색인 개수, 원문 추적, 프로파일·벡터 차원을 대조하고 별칭의 실제 대상을 확인합니다.",
          "검증을 통과하면 Projection과 build를 READY·활성으로 확정합니다. 실패·부분 준비·별칭 차단은 별도 상태로 남깁니다.",
        ],
        checks: ["READY가 아닌 projection은 일반 검색에 포함하지 않습니다.", "미종료 별칭 요청이나 유지보수 차단은 종료 증거 없이 해제하지 않으며 health 정상만으로 완료를 판단하지 않습니다."],
        references: [
          { title: "완성·별칭 검증", reference: "backend/src/ai_workshop/labs/rag/ingestion/stages.py" },
          { title: "별칭 복구 경계", reference: "docs/decisions/0032-rag-alias-recovery.md" },
        ],
      },
    },
  ],
  answer: [
    {
      id: "prepare", title: "질문·문맥 준비",
      summary: "이번 질문에서 사용할 범위와 이전 대화를 먼저 정합니다.",
      nodeIds: ["request", "history", "context"],
      technical: {
        components: [
          { name: "접수 사전검사·ConversationAccess", role: "현재 연결·문서 범위·권한과 필요한 외부 전송 승인을 확인합니다." },
          { name: "문맥 정책·contextualization", role: "허용된 이전 대화를 예산 안에서 골라 생략된 대상·조건을 검색 질문에 반영합니다." },
        ],
        mechanism: [
          "서버가 저장된 대화의 범위·권한·검증 상태를 다시 확인하고 생성 프로파일의 메시지·토큰 예산을 적용합니다.",
          "문맥이 있으면 구성한 모델로 검색 질문을 문맥화하고, 없으면 이번 질문으로 바로 검색합니다.",
        ],
        checks: ["브라우저의 메시지 전체를 그대로 신뢰하거나 모델에 보내지 않습니다.", "사전검사 거절과 실행 중 모델 실패를 구분하고 선택 모델 실패를 숨기지 않습니다."],
        references: [
          { title: "질문·생성 사전검사", reference: "backend/src/ai_workshop/labs/rag/search/pipeline.py" },
          { title: "저장된 이전 대화 선별", reference: "backend/src/ai_workshop/labs/rag/conversations/service.py" },
        ],
      },
    },
    {
      id: "search", title: "원문 검색·근거 선택",
      summary: "단어와 의미로 찾은 원문 후보를 합쳐 답변에 쓸 근거를 고릅니다.",
      nodeIds: ["retrieve", "rerank", "selection"],
      technical: {
        components: [
          { name: "BM25", role: "질문에 나온 단어가 문서에 얼마나 적절하게 등장하는지로 후보를 찾습니다." },
          { name: "dense·bi-encoder", role: "질문과 문서를 각각 임베딩 벡터로 바꿔 표현이 달라도 의미가 가까운 후보를 찾습니다." },
          { name: "RRF", role: "두 검색 목록의 순위를 합쳐 공통으로 높은 후보를 앞에 놓습니다." },
          { name: "선택 리랭커", role: "후보를 다시 정렬하는 선택 단계입니다. 현재 V1은 활성 리랭커를 지원하지 않으며 미설정은 정상 생략입니다." },
          { name: "EvidenceSelector·근거 예산", role: "문장 근거의 적합성과 주변 문맥을 평가해 허용된 분량만 생성에 전달합니다." },
        ],
        mechanism: [
          "현재 권한·공간·문서 필터를 먼저 적용한 뒤 Elasticsearch에서 BM25 단어 검색과 임베딩 벡터 검색을 수행합니다. BM25 단독 구성도 비교할 수 있습니다.",
          "RRF는 각 목록의 순위 r에 대한 1/(k+r)를 더해 정렬합니다. 이 점수는 유사도 백분율이 아닙니다. 선택 리랭킹은 별도 개념이며 현재 실행 코어에는 활성 리랭커 경로가 없습니다.",
          "EvidenceSelector가 근거 문장의 적합성과 충돌을 확인하고, 문맥 선택기가 청크·근거 수·문자 분량 예산으로 생성 입력을 제한합니다.",
        ],
        checks: ["원문 버전·청크·위치를 추적할 수 있어야 하며 검색 뒤 결과 숨김으로 권한 필터를 대신하지 않습니다.", "현재 V1은 활성 리랭커 바인딩을 구성 검증에서 거절합니다. 미설정은 오류가 아닙니다.", "근거 부족·모델 오류를 구분합니다. RRF 순위와 의미 유사도는 인용 정확성이나 정답 확률을 보장하지 않습니다."],
        references: [
          { title: "하이브리드 검색", reference: "backend/src/ai_workshop/labs/rag/retrieval/service.py" },
          { title: "순위 결합 공식", reference: "backend/src/ai_workshop/labs/rag/retrieval/rrf.py" },
          { title: "근거 선택·예산", reference: "backend/src/ai_workshop/labs/rag/search/pipeline.py" },
          { title: "현재 리랭커 구성 경계", reference: "backend/src/ai_workshop/labs/rag/configurations/domain.py" },
        ],
      },
    },
    {
      id: "generate", title: "근거로 답변 생성",
      summary: "선택한 원문 안에서 답변과 주장별 인용을 만듭니다.",
      nodeIds: ["generation"],
      technical: {
        components: [
          { name: "GenerationProfile·런타임 어댑터", role: "모델·배포 버전·프롬프트와 실행 제한을 구성대로 적용합니다." },
          { name: "구조화된 생성 응답", role: "답변의 주장과 근거 ID를 분리해 후속 검증이 가능하게 합니다." },
        ],
        mechanism: [
          "이번 질문·허용된 대화 문맥·선택 원문을 구성된 런타임에 전달하고 구조화된 답변을 받습니다.",
          "모델이 근거 내용 부족을 반환하면 해당 종료 이유를 기록하고 인용 검증을 생략합니다. 이전 답변은 이번 원문 근거를 대신하지 않습니다.",
        ],
        checks: ["구성한 모델의 오류·시간 초과·취소를 구분하며 다른 모델로 조용히 전환하지 않습니다.", "외부 전송은 현재 승인된 데이터·동의 조건을 만족해야 합니다."],
        references: [
          { title: "생성과 근거 부족 처리", reference: "backend/src/ai_workshop/labs/rag/search/pipeline.py" },
          { title: "생성 프로파일", reference: "backend/src/ai_workshop/labs/rag/generation/profile.py" },
        ],
      },
    },
    {
      id: "validate", title: "인용 검증·결과 저장",
      summary: "답변의 인용과 원문 연결을 검사하고 실행 결과를 보관합니다.",
      nodeIds: ["citation", "persist"],
      technical: {
        components: [
          { name: "CitationValidator", role: "주장별 인용 ID·원문 추적 정보와 날짜·수치의 근거 포함 여부를 검사합니다." },
          { name: "대화 저장소·실행 관측", role: "답변·근거·종료 상태와 가능한 단계별 시간·오류를 기록합니다." },
        ],
        mechanism: [
          "각 주장에 허용된 근거 ID가 있는지, projection·chunk 출처가 완전한지, 검사 대상 날짜·수치가 인용 원문에 있는지 확인합니다.",
          "검증 결과와 실행 상태를 저장하고 반환 시 현재 권한을 다시 확인합니다. 저장 실패 등 일부 예외는 정상 저장 경로를 완주하지 못할 수 있습니다.",
        ],
        checks: ["검증 실패 초안을 정상 답변으로 노출하지 않습니다. 이 검사는 모든 문장의 의미적 타당성을 보장하는 판정은 아닙니다.", "취소 뒤 늦은 완료가 취소 상태를 덮어쓰지 않으며 비공개 내부 추론을 실행 근거로 저장하지 않습니다."],
        references: [
          { title: "인용 검사 범위", reference: "backend/src/ai_workshop/labs/rag/generation/citation_validation.py" },
          { title: "결과·종료 상태 저장", reference: "backend/src/ai_workshop/labs/rag/conversations/service.py" },
        ],
      },
    },
    {
      id: "result", title: "답변·종료 이유 확인",
      summary: "성공·근거 부족·실패를 구분해 사용자가 다음 조치를 정할 수 있게 합니다.",
      nodeIds: ["answered", "insufficient", "failed"],
      technical: {
        components: [
          { name: "답변·원문 뷰어", role: "검증된 답변에서 근거와 실제 원문 위치로 이동하게 합니다." },
          { name: "검색 진단·실행 모니터링", role: "검색 순위·근거 선택 이유와 단계 상태·소요 시간·안전한 오류를 보여줍니다." },
        ],
        mechanism: [
          "정상 답변은 인용과 원문 링크를 함께 표시합니다. 근거 선택 단계의 부족과 생성 이후 내용 부족은 별도 이유로 남깁니다.",
          "접수 전 거절·실행 실패·취소를 구분해 가능한 진단을 표시합니다. 취소 표시와 실제 실행 종료 확인도 구분합니다.",
        ],
        checks: ["의미 하이라이트를 정확한 문자열 일치로 표현하지 않습니다.", "진단 조회와 원문 열기는 각 화면의 현재 사용자 권한을 유지합니다."],
        references: [
          { title: "검색 진단", reference: "backend/src/ai_workshop/labs/rag/search/diagnostics.py" },
          { title: "원문 뷰어", reference: "backend/src/ai_workshop/labs/rag/search/viewer.py" },
          { title: "실행 관측", reference: "backend/src/ai_workshop/labs/rag/executions/observer.py" },
        ],
      },
    },
  ],
  sessions: [
    {
      id: "draft", title: "질문 전 준비",
      summary: "새 대화 화면과 첨부 초안을 준비하며 첫 질문 접수를 기다립니다.",
      nodeIds: ["open", "draft"],
      technical: {
        components: [
          { name: "새 대화 화면", role: "질문 전 입력 상태를 제공하며 메뉴 진입만으로 DB 세션을 만들지 않습니다." },
          { name: "AttachmentDraft", role: "첫 질문 전 PC 첨부를 소유자·도메인·revision이 있는 별도 초안으로 보관합니다." },
        ],
        mechanism: [
          "새 대화에서는 질문과 문서 범위를 선택합니다. PC 파일은 세션 대신 첨부 초안에 연결됩니다.",
          "초안은 열림·결합·포기·만료 상태를 관리하고 첫 질문 접수 시 현재 revision과 첨부 결합 가능 여부를 확인합니다.",
        ],
        checks: ["초안 소유자·도메인·만료와 업로드 진행 상태를 검사합니다.", "파일 저장 상태와 현재 질문에 사용할 수 있는 준비 상태를 구분합니다."],
        references: [
          { title: "첨부 초안 수명주기", reference: "backend/src/ai_workshop/labs/rag/conversations/draft_service.py" },
          { title: "첫 질문 접수 설계", reference: "docs/decisions/0031-first-question-conversation-and-drafts.md" },
        ],
      },
    },
    {
      id: "accept", title: "첫 질문·제목 원자 접수",
      summary: "첫 질문을 받을 때 제목과 첨부를 함께 저장해 빈 대화를 방지합니다.",
      nodeIds: ["preflight", "title", "accept"],
      technical: {
        components: [
          { name: "사전검사·접수 멱등 기록", role: "연결·권한·승인과 동일 요청의 재전송 여부를 확인합니다." },
          { name: "결정적 제목 정책", role: "LLM 호출 없이 첫 질문의 대상·의도·조건을 로컬 규칙으로 추출합니다." },
          { name: "PostgreSQL 트랜잭션", role: "세션·제목·첫 turn·접수 기록·초안 결합을 한 번에 저장합니다." },
        ],
        mechanism: [
          "요청 ID와 입력 digest로 동일 요청을 식별합니다. 사전검사 후 제목을 한 번 산출하며 불명확한 경우 fallback 이유를 기록합니다.",
          "동일 트랜잭션에서 세션과 첫 질문, 제목 출처, 접수 기록과 첨부 결합을 확정합니다. 중간 오류는 접수 전체를 되돌립니다.",
        ],
        checks: ["같은 요청 ID의 다른 입력은 충돌로 거절하고 같은 입력의 재전송은 기존 접수 결과로 수렴합니다.", "사전검사 거절은 새 세션을 만들지 않습니다. 접수 후 모델 오류는 실패 turn을 가진 세션에 남습니다."],
        references: [
          { title: "첫 질문 사전검사·제목", reference: "backend/src/ai_workshop/labs/rag/conversations/service.py" },
          { title: "원자 접수 저장소", reference: "backend/src/ai_workshop/labs/rag/conversations/repository.py" },
          { title: "로컬 제목 정책", reference: "backend/src/ai_workshop/labs/rag/conversations/title_policy.py" },
        ],
      },
    },
    {
      id: "restore", title: "현재 권한으로 복원",
      summary: "기존 대화를 다시 열 때 지금 볼 수 있는 내용만 복원합니다.",
      nodeIds: ["restore"],
      technical: {
        components: [
          { name: "대화 저장소", role: "소유자·도메인·삭제 여부를 확인해 해당 세션만 조회합니다." },
          { name: "ConversationAccess·의존 관계", role: "현재 원문 접근과 선행 답변의 가시성을 다시 검사합니다." },
        ],
        mechanism: [
          "DB에 저장된 질문·응답·선택 범위를 읽되 현재 SQL 권한과 원문 상태로 접근 가능 여부를 다시 판단합니다.",
          "비허용 turn은 질문·응답·범위·실행 참조를 가립니다. 첫 질문을 볼 수 없으면 파생된 세션 제목도 가립니다.",
        ],
        checks: ["과거 저장된 권한 정보로 현재 접근을 대신하지 않습니다.", "다른 소유자·도메인의 세션과 삭제된 세션은 복원하지 않습니다."],
        references: [
          { title: "현재 문서 접근 검사", reference: "backend/src/ai_workshop/labs/rag/conversations/access.py" },
          { title: "복원·가림 처리", reference: "backend/src/ai_workshop/labs/rag/conversations/service.py" },
        ],
      },
    },
    {
      id: "followup", title: "후속 질문·동시 실행 제어",
      summary: "같은 세션의 중복 요청과 겹친 실행을 구분해 관리합니다.",
      nodeIds: ["followup", "execute"],
      technical: {
        components: [
          { name: "revision·요청 ID·digest", role: "조회 이후 상태 변경과 요청의 중복·충돌을 구분합니다." },
          { name: "inflight·종료 guard", role: "실행 중이거나 취소 뒤 실제 실행이 끝나지 않은 경우 후속 실행을 막습니다." },
        ],
        mechanism: [
          "대화 행을 잠그고 기존 요청을 확인한 뒤 revision을 검사해 새 turn을 예약합니다. 접수된 turn은 공통 검색·생성 코어를 실행합니다.",
          "취소 상태와 execution_terminated 종료 증거를 분리합니다. 완료 저장 시 현재 상태를 다시 읽어 늦은 결과가 취소를 덮어쓰지 못하게 합니다.",
        ],
        checks: ["오래된 revision과 같은 요청 ID의 다른 입력은 충돌로 안내합니다.", "running 또는 종료가 확인되지 않은 취소 요청이 있으면 새 실행을 막습니다."],
        references: [
          { title: "turn 예약·중복·충돌", reference: "backend/src/ai_workshop/labs/rag/conversations/domain.py" },
          { title: "실행·종료 기록", reference: "backend/src/ai_workshop/labs/rag/conversations/service.py" },
        ],
      },
    },
    {
      id: "result", title: "저장·거절·종료 상태 확인",
      summary: "다시 이어갈 대화와 조치가 필요한 종료 상태를 구분합니다.",
      nodeIds: ["saved", "rejected", "ended"],
      technical: {
        components: [
          { name: "저장된 세션·수동 제목", role: "대화 결과를 보존하고 후속 질문이 수동 제목을 덮어쓰지 않게 합니다." },
          { name: "취소·삭제·원본 정리 경계", role: "화면 상태 변경, 실제 writer 종료와 첨부 정리 가능 여부를 분리합니다." },
        ],
        mechanism: [
          "첫 질문 미접수는 입력·초안을 유지하고, 기존 대화의 충돌·실행 실패는 세션을 보존한 채 상태를 안내합니다.",
          "삭제는 재실행을 차단합니다. 원본·첨부 정리는 실제 writer 종료와 참조 조건을 확인하는 별도 수명주기를 따릅니다.",
        ],
        checks: ["lease 만료로 interrupted가 됐다는 사실만으로 실제 실행 종료를 단정하지 않습니다.", "다시 조회할 때 권한을 재검사하며 실패 turn을 정상 answered 문맥으로 쓰지 않습니다."],
        references: [
          { title: "대화 종료·삭제", reference: "backend/src/ai_workshop/labs/rag/conversations/service.py" },
          { title: "첨부 정리 수명주기", reference: "backend/src/ai_workshop/labs/rag/conversations/attachment_lifecycle.py" },
        ],
      },
    },
  ],
  multiturn: [
    {
      id: "scope", title: "같은 검색 범위 묶기",
      summary: "이번 질문과 같은 문서 범위의 과거 대화만 후보로 삼습니다.",
      nodeIds: ["scope", "same"],
      technical: {
        components: [
          { name: "scope identity", role: "연결·공간·폴더·선택 모드·문서·활성 원본·READY build를 묶어 범위를 식별합니다." },
          { name: "segment·앱 DB", role: "범위가 바뀔 때 대화를 구간으로 나누고 같은 구간의 저장 turn을 읽습니다." },
        ],
        mechanism: [
          "현재 허용 문서의 원본 버전과 활성 READY build를 포함한 범위 지문을 서버에서 계산합니다.",
          "직전 turn의 범위 지문과 다르면 새 segment를 만들고, 이번 turn 이전의 같은 segment만 문맥 후보로 삼습니다.",
        ],
        checks: ["화면에 남은 다른 범위 메시지를 모델 문맥에 자동 포함하지 않습니다.", "브라우저가 제출한 임의 이력 대신 앱 DB의 저장 상태를 기준으로 재구성합니다."],
        references: [
          { title: "범위 지문 계산", reference: "backend/src/ai_workshop/labs/rag/conversations/access.py" },
          { title: "segment 전환", reference: "backend/src/ai_workshop/labs/rag/conversations/domain.py" },
        ],
      },
    },
    {
      id: "eligible", title: "현재 권한·검증 상태 선별",
      summary: "지금 접근할 수 있고 검증된 답변만 문맥으로 사용합니다.",
      nodeIds: ["access", "eligible"],
      technical: {
        components: [
          { name: "현재 접근·dependencies", role: "원문 접근과 의존한 선행 turn의 가시성을 함께 다시 검사합니다." },
          { name: "validation token", role: "서버가 발급한 검증 표식으로 과거 답변과 해당 범위의 유효성을 확인합니다." },
        ],
        mechanism: [
          "completed·answered 상태이고 답변 텍스트와 검증 토큰이 있는 turn만 질의·응답 쌍으로 선별합니다. 실행 코어는 토큰의 범위 유효성을 확인합니다.",
          "원문과 선행 turn 의존 관계를 재검사하며 외부 처리에는 현재 전송 승인과 공개·합성 분류·동의 조건을 추가 적용합니다.",
        ],
        checks: ["권한이 철회된 원문이나 가려진 선행 답변에 의존한 turn은 제외합니다.", "실패·취소·근거 부족·검증 불가 답변을 다음 질문의 모델 문맥으로 쓰지 않습니다."],
        references: [
          { title: "문맥 후보·의존 관계 검사", reference: "backend/src/ai_workshop/labs/rag/conversations/service.py" },
          { title: "문맥 검증 토큰 확인", reference: "backend/src/ai_workshop/labs/rag/search/pipeline.py" },
        ],
      },
    },
    {
      id: "context", title: "문맥 예산·질문 문맥화",
      summary: "최근 대화를 필요한 분량만 남겨 이번 질문의 대상을 분명히 합니다.",
      nodeIds: ["budget", "context"],
      technical: {
        components: [
          { name: "최근 질의·응답 쌍", role: "서버에서 선별한 최근 최대 10개 쌍을 문맥 후보로 제공합니다." },
          { name: "GenerationProfile 문맥 정책", role: "메시지 수·토큰 예산을 적용해 실제 모델 입력을 더 줄입니다." },
        ],
        mechanism: [
          "서버의 후보 상한은 20개 메시지이며 프로파일 예산에 따라 실제 포함량은 더 작아질 수 있습니다.",
          "남은 문맥으로 이번 질문의 대상·조건을 보완해 검색 질문을 만듭니다. 문맥이 없으면 이 모델 호출을 생략합니다.",
        ],
        checks: ["항상 10개 쌍을 전송하는 고정 동작으로 설명하지 않습니다.", "모델 내부 세션 resume 대신 매 요청마다 앱에서 문맥을 재구성하며 선택 모델 실패를 숨기지 않습니다."],
        references: [
          { title: "최근 문맥 후보 상한", reference: "backend/src/ai_workshop/labs/rag/conversations/service.py" },
          { title: "문맥 예산", reference: "backend/src/ai_workshop/labs/rag/generation/profile.py" },
          { title: "질문 문맥화", reference: "backend/src/ai_workshop/labs/rag/search/pipeline.py" },
        ],
      },
    },
    {
      id: "ground", title: "현재 원문 재검색·답변 검증",
      summary: "대화가 이어져도 새 질문의 근거는 현재 원문에서 다시 찾습니다.",
      nodeIds: ["search", "answer"],
      technical: {
        components: [
          { name: "하이브리드 검색·근거 선택", role: "현재 권한과 범위에서 이번 질문을 뒷받침할 원문을 새로 찾습니다." },
          { name: "생성·인용 검증", role: "선택 근거로 답변을 생성하고 주장별 인용 ID·출처·검사 대상 수치를 확인합니다." },
        ],
        mechanism: [
          "문맥 유무와 관계없이 현재 원문에 BM25·dense 검색과 근거 선택 예산을 적용합니다.",
          "과거 답변은 질문 이해에만 활용하고 새 답변의 인용은 이번 선택 원문에 연결합니다. 모델이 근거 부족을 반환하면 별도 종료 상태로 남깁니다.",
        ],
        checks: ["이전 segment의 답변을 현재 원문 근거처럼 재사용하지 않습니다.", "인용 검사 실패와 모델·검색 오류를 정상 답변으로 바꾸지 않습니다."],
        references: [
          { title: "재검색·생성 실행", reference: "backend/src/ai_workshop/labs/rag/search/pipeline.py" },
          { title: "인용 검사", reference: "backend/src/ai_workshop/labs/rag/generation/citation_validation.py" },
        ],
      },
    },
    {
      id: "result", title: "새 turn·의존 관계 저장",
      summary: "새 답변과 어떤 대화에 의존했는지 남겨 다음 질문에서 다시 검증합니다.",
      nodeIds: ["saved", "failed"],
      technical: {
        components: [
          { name: "turn·dependencies 저장소", role: "이번 결과와 문맥에 포함한 선행 turn의 관계를 보관합니다." },
          { name: "종료 상태·현재 가시성", role: "답변 성공 여부와 실패·취소를 구분하고 이후 권한 변경을 반영합니다." },
        ],
        mechanism: [
          "사용한 선행 turn ID와 실행 결과를 저장합니다. 다음 질문에서 같은 segment·현재 접근·검증 상태를 다시 검사합니다.",
          "근거 부족·실패·취소는 가능한 진단과 함께 남기되 answered 문맥 후보에서 제외합니다.",
        ],
        checks: ["선행 turn이 가려지면 그 turn에 의존한 답변의 가시성도 재검사합니다.", "저장 성공만으로 다음 질문의 재사용이나 현재 원문 접근을 보장하지 않습니다."],
        references: [
          { title: "의존 관계·종료 상태 저장", reference: "backend/src/ai_workshop/labs/rag/conversations/service.py" },
          { title: "대화 영속 저장", reference: "backend/src/ai_workshop/labs/rag/conversations/repository.py" },
        ],
      },
    },
  ],
} as const satisfies Record<"ingestion" | "answer" | "sessions" | "multiturn", readonly FlowPhase[]>;
