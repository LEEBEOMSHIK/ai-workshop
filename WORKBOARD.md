# Workboard

- 마지막 갱신일: 2026-09-03
- 현재 단계: 전체 화면 AI 연구소 월드 재설계
- 전체 상태: 전체 화면 AI 연구소 월드 설계와 ADR 초안을 작성하고 독립 검토 `Ready`를 받았다. `/`와 `/labs`의 동일 월드, RAG 방·관리자, 반응형 말풍선과 접근성 계약에 대한 사용자 검토·승인을 기다리며 소스 구현은 시작하지 않았다.

## 현재 작업

### 목표

전체 화면 AI 연구소 월드의 공간·route·component·반응형·접근성 계약을 확정하고, 구현 전에 정본 설계와 상세 계획을 준비한다.

### 진행 상태

- 사용자는 `/`를 연구소 입구 겸 전체 월드로 사용하고 `/labs`도 동일한 연구소 화면을 제공하는 방향을 승인했다.
- 구현 방식은 게임 엔진이나 WebGL이 아니라 접근 가능한 DOM·CSS 기반 2D 연구소로 결정했다. 현재 단계에서는 설계 문서만 작성하고 승인 전 소스 구현을 변경하지 않는다.
- 연구소 월드는 viewport 전체를 사용하며, RAG 방 안의 작업 중인 관리자 캐릭터를 선택하면 중앙 modal이 아닌 캐릭터와 연결된 말풍선을 열고 `/labs/rag` 상세로 안내한다.
- 상세 설계는 `docs/superpowers/specs/2026-09-03-full-screen-ai-lab-world-design.md`, 결정 초안은 `docs/decisions/0005-public-ai-lab-world.md`에 작성했다.
- 독립 검토에서 초기 초점, 빈·오류 상태, route-group 경로, catalog CTA와 비변경 범위를 보완한 뒤 남은 finding 없이 `Ready` 판정을 받았다.
- 프로젝트 에이전트 계약 `validate`와 `git diff --check`가 통과했다. 검증기 테스트는 Windows에서 POSIX 셸 fixture를 실행하는 기존 5건이 실패하고 47건이 통과했으며 이번 문서 작업에서 검증기 소스는 변경하지 않았다.
- 아래 브라우저·테스트 결과는 새 전체 화면 월드가 아니라 2026-09-03 기존 카드형 공개 화면의 기준선 검증이다. 새 월드는 아직 구현·브라우저 검증하지 않았다.
- Chrome 연결이 복구됐고 `/`와 `/labs`의 desktop 화면, 캐릭터 소개 열기, 초기 닫기 버튼 focus, Escape 닫기와 trigger focus 복귀를 실제 브라우저에서 확인했다.
- `/labs` 스크롤 상태에서 소개 대화상자 layer와 animated character의 실제 경계가 모두 `240×269px`로 일치하고 character computed transform이 활성화된 것을 측정했다. `position: fixed` layer가 transformed ancestor를 containing block으로 사용해 dialog 하단이 viewport 797px보다 큰 약 1085px까지 내려가는 것이 직접 원인이다.
- 대화상자를 `document.body` portal로 분리하고 모바일 eyebrow에 닫기 버튼 안전 영역을 추가했다. 독립 실제 브라우저 재검증에서 desktop `1189×797`, mobile `390×844` 모두 viewport containment, 가로 overflow 없음, 닫기 초기 focus, Tab 순환, Escape 닫기와 trigger focus 복귀를 통과했다.
- 공개 `/`, `/labs`, `/labs/rag`의 navigation/content 겹침이 없고 공개 RAG CTA가 `/login?next=%2Fworkshop%2Frag%2Fsearch`로 이동하는 것을 확인했다. 인증 정보가 없는 브라우저였으므로 owner 로그인 후 실제 데이터 화면은 검증하지 않았다.
- `prefers-reduced-motion`은 연결 브라우저에 media override capability가 없어 실제 에뮬레이션하지 못했다. CSS의 reduce media query가 `.roaming`, `.working`, `.statusLight` 애니메이션을 제거하는 정적 근거만 확인했으며 실제 브라우저 통과로 주장하지 않는다.
- 전체 계획 리뷰에서 retired `/app` 아래 남은 오류 경계를 `/workshop/error.tsx`로 이동하고 회귀 테스트를 추가했다. Setup·인증 backend/frontend 테스트의 개인 식별값과 과거 bootstrap 예시의 개인 이메일을 합성 값으로 교체했으며 개인정보 독립 검증에서 현재 추적 파일의 개인 이메일과 테스트 fixture 이름이 0건임을 확인했다.
- 최종 재검증은 frontend Vitest `36 files, 122 passed`, TypeScript, ESLint 무경고, production build, backend focused `8 passed`, unit `423 passed`, Ruff와 mypy가 통과했다. backend unit을 저장소 루트에서 실행하면 루트 `.env`가 기본값 테스트에 주입돼 1건 실패하므로 정본 `backend/` 작업 디렉터리에서 실행해야 한다.
- 공개 전시실은 `/`, `/labs`, `/labs/rag`에서 인증 없이 접근하며, 비공개 작업소는 `/workshop/*`, owner 시스템 관리는 `/admin/*`로 분리됐다.
- `/app/*`는 compatibility-only 영구 리다이렉트다. `/app/rag/search`는 `/workshop/rag/search`, `/app/rag/configurations`는 `/admin/rag/configurations`로 이동한다.
- 1단계 공개 화면은 캐릭터 랜딩, Lab 목록과 RAG 기술 소개까지만 구현한다. 공개 검색, 불변 공개 릴리스, LLM 답변, 문서 업로드, 피드백과 학습은 승인된 후속 단계이며 아직 구현하지 않았다.
- RAG는 여러 전문 도메인이 공유하는 기술 Lab이고 자산운용은 첫 도메인 패키지다. 다음 단계에서 동적 도메인과 공개 릴리스 계약을 상세 설계한다.
- 2026-09-03 최종 프론트 순차 검증은 Vitest `35 files, 121 passed`, TypeScript, ESLint 무경고, Next.js 16.3.4 production build 모두 통과했다.
- WinGet `uv` shim은 접근 거부돼 backend `.venv` Python module 명령으로 동일 검사를 실행했다. 구성·평가 API `7 passed`(기존 Starlette deprecation warning 1건), fresh `%TEMP%` basetemp의 unit `423 passed`, Ruff와 mypy가 통과했다.
- backend unit 최초 실행은 기존 ACL 잠금 `backend/.pytest-tmp`를 pytest가 제거하지 못해 `380 passed, 43 setup errors`로 종료됐다. 해당 경로는 건드리지 않았고 fresh 외부 basetemp 재실행으로 테스트 자체를 검증했다.
- 기존 FastAPI health는 `200`이었다. 기존 Next 서버는 재시작 전 legacy redirect 두 건이 `404`였고, 현재 소스 구성으로 Next만 재시작한 뒤 공개 경로 3개 `200`, 보호 경로 2개 `307`과 원래 `next` query, legacy 경로 2개 `308` 및 정확한 Location을 확인했다.

- `docs/vision/project-vision.md`와 `docs/architecture/system-design.md`는 외부 방문자가 별도 공개 전시실에서 캐릭터형 에이전트의 안내로 승인된 결과와 선별된 시행착오를 보는 구조를 정본으로 명시한다.
- 1단계 이전 공개 홈은 정적 카드에서 보호된 `/app/rag/search`, `/app/rag/configurations`와 owner 전용 `/admin/rag/models`로 직접 연결해, 캐릭터 탐색과 공개 AI Lab 상세 진입이라는 제품 의도를 구현하지 못했다.
- 화면의 `RAG 기술 관리자 에이전트`는 공개 방문자를 안내하는 도메인 캐릭터이고, `owner`는 비공개 작업소와 백오피스를 관리하는 인증 역할이다. 두 개념을 별도 명칭과 계약으로 분리해야 한다.
- 공개 RAG Lab은 승인된 공개 데이터로 이미 구현된 검색 기능을 직접 확인할 수 있어야 하며, 기능 설명과 함께 문제·시도·이슈·실패·해결·검증 결과를 연결해 보여준다.
- 모델 등록·교체, 색인·검색·생성 구성 편집과 기본 구성 승격은 공개 캐릭터 화면이 아니라 인증된 시스템 관리자 화면의 책임으로 분리한다.
- 공개 RAG Lab은 현재 공개 서비스에 적용된 모델명·버전과 Parser·Chunker·Sparse/Dense Retriever·Fusion·Highlight 구성을 읽기 전용으로 표시한다. 내부 UUID·비밀값·환경 경로와 편집 동작은 제외한다.
- 공개 전시실은 비공개 작업소의 현재 설정을 실시간 조회하지 않는다. 관리자가 검증·승인한 모델 구성, 공개 문서·색인, 평가와 해결 기록을 하나의 불변 공개 릴리스 패키지로 발행하고 활성 릴리스만 공개 화면에 제공한다.
- 1단계 공개 URL은 `/`, `/labs`, `/labs/rag`까지 구현됐다. 2단계 이후 승인된 계약은 공통 `/labs/rag/architecture`와 `/labs/rag/domains`, 도메인별 `/labs/rag/domains/{domainSlug}` 및 그 아래 `search`, `journey`, `configuration`의 동적 공개 URL이며, 캐릭터 선택 시 소개 패널을 거쳐 공유 가능한 독립 상세 URL로 이동한다.
- 공개된 완성 기능에는 `데모` 명칭을 사용하지 않고 `AI 검색`처럼 기능·서비스 자체의 이름을 사용한다. 검증 중인 기능은 비공개 작업소에 유지하거나 `연구 중` 상태로 명확히 구분한다.
- 비공개 작업소는 `/workshop/*`, 모델·RAG 구성 편집과 공개 릴리스 관리는 `/admin/*`로 분리한다. 현재 `/app/rag/configurations` 편집 책임은 관리자 영역으로 이전한다.
- RAG는 자산운용 전용 기능이 아니라 여러 전문 도메인이 사용하는 기술 Lab으로 정의한다. 자산운용은 첫 도메인 패키지이며 보험·금융·법률·HR 등을 동일한 도메인 계약으로 추가한다.
- 공개 URL은 도메인 식별자를 동적으로 받아 `/labs/rag/domains/{domainSlug}/search`처럼 구성하고, 도메인 이름·목록·공개 상태를 프론트 코드에 고정하지 않는다.
- RAG 에이전트 조직은 `RAG 총괄 + 공통 기술 작업자 + 도메인별 관리자`를 기본 계층으로 삼고, 도메인 고유 처리가 실제로 필요할 때만 전용 작업자를 추가한다.
- 공개 방문자는 활성 공개 릴리스의 승인된 지식 문서만 검색한다. 문서 첨부 검색과 개인 지식 공간 저장은 로그인 사용자에게만 제공하며, 업로드 수락 전에 형식·크기·파일 서명·파싱 가능성·도메인 적합성과 사용량 정책을 검사한다.
- 로그인 사용자의 `현재 검색에 첨부` 문서는 세션 만료 후 원본·파싱·임베딩·색인을 자동 삭제한다. `내 지식 공간에 저장`을 명시한 문서만 영속 보관하며 두 범위는 검색 UI에서 사용자가 직접 선택한다.
- 도메인 적합도가 낮은 문서는 자동 폐기하지 않고 확인 상태로 두어 다른 도메인 선택을 안내한다. 악성·손상·정책 위반 파일은 명시적 사유와 함께 거절하며 강제 진행을 허용하지 않는다.
- 도메인별 공개 릴리스는 한 시점에 하나만 활성화하고 이전 릴리스는 일반 검색에서 제외한 채 재현·감사·즉시 롤백용으로 보존한다. 새 릴리스 검증 또는 배포 실패는 현재 활성 서비스에 영향을 주지 않는다.
- 공개 검색과 로그인 검색은 대화형 인터페이스로 제공한다. 검색 순위는 BM25·dense·RRF가 결정하고, 각 응답은 사용 릴리스·원문 근거·하이라이트와 연결하며 근거 부족을 정상 상태로 표현한다.
- 공개 RAG 서비스는 검색 근거에 제한된 LLM 답변까지 제공한다. 생성 답변은 인용 검증을 통과해야 하며 근거가 부족하거나 검증에 실패하면 답변을 꾸며내지 않고 근거 부족 상태와 검색 결과를 반환한다.
- 잘못된 결과는 재현 가능한 품질 이슈로 등록해 검색 실행 스냅샷, 사용 릴리스·프로파일, 검색 근거, 검증 결과, 원인 분류, 수정 실험과 재평가를 연결한다. 모델의 비공개 내부 추론은 저장하거나 원인 설명으로 사용하지 않는다.
- 오답 사례는 원문 그대로 자동 공개하지 않고 공개·합성 데이터로 재현한 뒤 비식별화와 관리자 승인을 통과한 선별 사례만 `해결 과정`에 발행한다.
- 현재 구현은 Recall@K·MRR·nDCG 중심의 오프라인 검색 평가를 제공하지만 사용자 피드백 수집·검토·평가 세트 승격 계약은 없다. 좋아요·싫어요를 순위나 모델에 즉시 반영하지 않고 RAG Evaluation의 검토 대기 신호로 수집한다.
- 피드백은 전체 답변 만족도, 답변 정확성·완전성, 인용 지지 여부, 검색 문서 관련성·누락·최신성으로 분해한다. 검증된 피드백만 도메인별 judgment/evaluation set에 추가해 기존 구성과 후보 구성을 재평가하고 승인된 새 릴리스로 반영한다.
- 검증된 피드백은 평가 세트뿐 아니라 파인튜닝 데이터셋 후보로도 승격할 수 있다. 리트리버·리랭커는 query-positive-negative relevance 예제, LLM은 근거가 연결된 교정 정답 또는 chosen-rejected preference pair로 별도 정제한다.
- 원본 좋아요·싫어요는 모델 학습에 직접 사용하지 않는다. 권한·동의·비식별화, 중복 제거, 전문가 검토, train/validation/test 분리와 데이터셋 버전 고정을 통과한 학습 예제만 Training Experiment가 사용한다.
- 파인튜닝 결과는 새 모델 버전으로 Model Registry에 등록하고 기존 기준선과 도메인 회귀 평가를 통과한 뒤에만 후보 RAG 구성과 공개 릴리스로 승격한다.
- 파인튜닝은 데이터량 기준으로 자동 시작하지 않는다. 관리자가 데이터셋 버전·도메인·기반 모델·예상 비용·데이터 권한 검사를 확인해 명시적으로 실행하며, 학습 완료·평가 통과·RAG 구성 연결·공개 릴리스 승격도 각각 분리된 승인 단계로 둔다.
- 공개 방문자의 질문·답변·좋아요·싫어요는 저장·관리·평가·학습 데이터로 사용하지 않는다. 공개 화면에는 피드백 기능의 존재만 안내하고 실제 제출과 상세 피드백은 로그인 뒤에만 허용한다.
- 로그인 사용자의 상세 피드백은 활용 동의, 개인정보·권한 검사와 도메인 전문가 검토를 통과한 경우에만 평가·파인튜닝 데이터 후보로 승격한다.
- 공개 화면의 좋아요·싫어요는 기능 안내용으로 표시하되 선택 내용을 저장하지 않는다. 선택 시 로그인 안내를 열고, 실제 피드백·평가·학습 데이터 수명주기는 인증된 세션에서만 시작한다.
- 예상 밖 인증 동작에 체계적 디버깅 절차를 적용한다. 사용자·관리자 라우트, 로그인 세션 응답, 역할 검사와 사용자 생성 경로를 역추적한다.
- 현재 `/app/*`는 인증 레이아웃이 아니라 compatibility-only 영구 리다이렉트다. `/workshop/*`는 `requireWorkspaceUser`, `/admin/*`는 `requireOwner`를 사용하며, RAG 구성·평가 API는 인증 사용자 조회와 owner 전용 mutation 경계를 분리한다.
- 최초 설정 API와 CLI 외에 일반 `member` 사용자를 생성·초대·관리하는 API/UI가 없고 현재 DB에도 owner 1명만 있어, 로그인 문구와 실제 사용 가능 계정이 모두 소유자 중심으로 굳어진 것이 직접 원인이다.

- 테스트 설비가 `synthetic-indexing-<UUID>` 프로파일을 커밋한 뒤 삭제하지 않는 직접 원인과, 총 8개의 잔여 프로파일 중 1개가 실패한 ingestion job·projection에 연결된 상태를 확인했다.
- 선택 역할은 요구·구현 설계자, Python 백엔드, DB 관리자, 프론트엔드, RAG 책임자, 테스트 설계자, 통합 검증자, 독립 코드 리뷰어다. 모델 런타임·배포·권한 계약은 변경하지 않아 해당 전문 역할은 호출하지 않는다.
- `delete_fixture`가 생성한 정확한 색인 프로파일까지 삭제하도록 고치고, ingestion 통합 테스트 13개를 고유 loopback 임시 PostgreSQL DB와 임시 object store에서 실행하도록 격리했다. production·비-loopback 대상은 연결 전에 거부하고 모든 실패 경로에서 생성 DB를 제거한다.
- 프론트 색인 패키지 선택지는 embedding binding이 실제 embedding 모델로 해석되는 프로파일만 표시한다. 기존 synthetic 8개가 DB에 남아 있어도 사용자 콤보박스에는 나타나지 않는다.
- 대상 프론트 테스트 10개, 전체 프론트 85개, TypeScript, ESLint, Next production build, backend unit 423개, ingestion 통합 13개, Ruff, mypy, 에이전트 계약과 독립 통합 검증·코드 리뷰가 통과했다.
- 전체 backend 597개 실행은 이번 대상 13개를 포함해 진행됐으나, 별도 integration test URL이 설정되지 않은 환경 때문에 기존 DB 통합 테스트 21개와 루트 `.env` 영향을 받는 기본값 단위 테스트 1개가 실패했다. 이번 변경 대상은 독립 격리 DB에서 모두 통과했다.
- 사용자 승인 뒤 개발 DB의 정확한 synthetic 프로파일 8개, 연결된 synthetic workspace 1개·사용자 2개와 cascade된 실패 job/projection 각 1개를 단일 트랜잭션으로 제거했다. 사후 잔여는 모두 0건이고 정상 E5/BGE 색인 프로파일 2개는 보존됐다.

- 색인 프로파일 옵션이 `e5-structure-aware v2` 같은 내부 이름만 표시해 사용자가 임베딩 모델과 청킹 차이를 판단하기 어려운 문제를 확인했다. 표시명은 profile/model/config 데이터에서 동적으로 구성하고 UUID를 포함하지 않는다.
- 색인 선택 라벨을 `색인 패키지`로 바꾸고 각 옵션을 `임베딩 모델·버전 · 청커·버전/목표/중첩 토큰 · 프로파일 버전` 순서로 설명한다. option value와 저장 payload의 정확한 profile ID, 호환 Retrieval 필터는 유지한다.
- 대상 테스트 9개, 순차 전체 프론트 테스트 84개, TypeScript, ESLint, Next production build와 독립 통합 검증이 통과했다. 전체 테스트와 build의 최초 병렬 실행에서 ComparisonPanel 1건이 5초 timeout됐지만 단독 20개와 자원 경합 없는 순차 전체 실행은 모두 통과했다.
- 색인·검색 구성의 profile/model UUID가 사용자 옵션과 요약에 직접 노출되는 원인을 확인했고, 내부 식별자를 API 값으로 유지하면서 기본 표시에서 감추는 설계를 승인받았다.
- 저장 구성은 개별 모델 하나가 아니라 Indexing·Retrieval·Answer Policy·선택적 Generation의 불변 버전을 묶은 RAG 패키지로 표시한다. 현재 구성 계약에 고정되지 않은 Parser와 V1에서 비활성인 Reranker·LLM은 추측값 대신 명시적 미사용·미고정 상태로 표시한다.
- 정리 대상은 `backend/.pytest-nextjs-final-contract`와 `backend/.pytest-tmp` 두 리터럴 경로로 한정했으며 애플리케이션 데이터·프론트 의존성·실행 서비스는 보존한다.
- `backend/.pytest-nextjs-final-contract`는 Windows 관리자 ACL로 소유돼 현재 실행 계정의 정확 경로 삭제도 거부됐고, `backend/.pytest-tmp`는 내부 확인 자체가 거부됐다. 우회 삭제하지 않고 차단 요소로 인계한다.
- RAG 패키지·UUID 회귀 테스트 32개, 전체 프론트 테스트 83개, TypeScript, ESLint, Next production build, 백엔드 YAML 테스트 11개, 에이전트 계약과 문서 diff 검사가 통과했으며 독립 코드 리뷰는 Ready 판정을 내렸다.
- Next.js는 프론트엔드와 최소 rewrite 계층만 담당하고 인증·권한·AI·DB 업무 로직은 FastAPI에 유지하기로 결정했다.
- 사용자 역할·관리자 RAG 명령 API, Next.js 도구체인·접근 레이아웃, 공개·지식 공간·문서 화면 전환을 구현했다.
- RAG 검색·구성·모델·출처 뷰어를 App Router에 연결하고, 의미·키워드 하이라이트 메타데이터를 원문 문구 노출 없이 canonical URL에서 복원하도록 구현했다.
- Vite·React Router 진입점과 의존성을 제거하고 이전 URL 여섯 개를 permanent redirect로 보존했다.
- Next 서버가 설정 파일 위치를 기준으로 루트 `.env`를 강제 로드해 호스트 FastAPI 포트를 rewrite와 Server Component에서 동일하게 사용한다.
- 보호 경로의 실제 pathname·query를 Next 프록시가 레이아웃에 전달해 로그인 뒤 원래 화면으로 복귀하며, 서버 렌더링 API 실패는 FastAPI correlation ID를 안전한 직렬화 데이터로 표시한다.
- 로컬 Next 서버와 기존 호스트 FastAPI를 연결해 health 200, 공개 화면 200, 레거시 검색 URL 308, 원래 경로를 보존한 비로그인 사용자·관리자 경로 307을 확인했다.
- Vite·React Router를 병행하지 않는 전체 전환과 `/app/*`, `/admin/*` canonical URL 및 기존 URL 영구 리다이렉트를 승인했다.
- Next.js `16.3.4` 안정 버전, App Router, Server Component 우선, 상호작용 경계만 Client Component로 사용하는 기준을 설계에 반영한다.
- DB에서 사용자 1명, 기본 공간 2개와 멤버십 2개가 정상 생성된 것을 확인했다.
- `/workspaces` 라우트가 인증만 확인하고 `listWorkspaces()`를 호출하지 않아 화면에 기본 빈 배열이 전달되는 원인을 확인했다.
- `/workspaces` 전용 보호 로더와 route wrapper를 연결해 API의 전사·개인 공간을 표시하고 회귀 테스트로 고정했다.
- 최초 관리자 설정 서비스·공개 상태 API·`/setup` UI, 생성 직후 세션 발급과 보호 경로의 setup/login 분기를 구현했다.
- 관리자와 전사·개인 기본 지식 공간을 동일 트랜잭션에서 생성하고 PostgreSQL table lock으로 동시 최초 설정을 직렬화한다.
- CLI owner bootstrap은 정상 사용자 흐름에서 제외하고 같은 계약을 따르는 복구 수단으로 한정했다.
- 깨끗한 로컬 DB의 설정 필요 상태를 호스트 API와 Vite proxy에서 확인했으며 실제 사용자 비밀번호나 임의 관리자 계정은 만들지 않았다.
- Markdown·TXT·텍스트 PDF 파싱, 구조 청킹, 로컬 E5 임베딩, Elasticsearch BM25+dense, Python RRF, 근거 응답·뷰어, 저장 구성과 평가 UI를 구현했다.
- 자산 READY 활성화, 구독별 ingestion handoff, 다중 활성 build alias와 PostgreSQL-authoritative 검색 수명주기를 구현했다.
- newline-terminated TXT와 빈 parse/chunk 경계를 명시적으로 처리하며, 실패 시 parser나 모델을 조용히 바꾸지 않는다.
- 보호 Compose smoke에서 원본 세 형식, 기존·신규 검색, keyword·semantic highlight, 원문 뷰어, BM25/E5 평가, 승격 거절과 두 사용자 권한 비노출을 실제 API·worker·Elasticsearch로 검증했다.
- Task 14 강화 E2E는 live runtime 밖의 격리 DB·Redis·Elasticsearch reset, foundation/RAG API·worker phase와 beat-only phase를 분리한 보호 프로젝트에서 두 cold/default 실행과 최종 리뷰 실행 모두 통과했다. 최종 실행은 foundation `2 passed`, RAG `17 passed in 110.70s`, beat-only liveness와 post-reset을 검증하고 컨테이너·네트워크만 정리했다.
- 문장 단위 정확한 provenance와 PDF bbox 제한, ingestion redelivery·오류 위생, system BM25 독립 색인 구독, 검색 tie-break, 고정 모델 tokenizer 기반 청킹·질의 한도를 구현·검증했다.
- 루트 `surface`, 잠긴 pytest 임시 디렉터리와 개발 Docker 볼륨은 보존했다.
- `feature/rag-ai-search-first-slice`와 `main`을 동일한 검증 커밋 `47cba3a`로 원격에 반영했다.
- 병합 검증용 PostgreSQL·Redis·Elasticsearch와 전용 네트워크만 제거해 AI Workshop 서비스는 종류별 한 개씩 유지했다.
- 루트 캐시를 재점검해 pnpm 의존성 연결, 영속 로컬 데이터, 도구 목업, 테스트 임시물과 worktree를 구분했다. 실제 삭제는 정책 승인 뒤 별도 범위로 진행한다.
- 루트 `CACHE_POLICY.md`, worktree 수명주기 지침과 Codex 연결 규칙을 구현했다. 프론트 package·lockfile·가상 저장소를 `frontend/`에 한정하고 58개 테스트, 타입 검사, 린트, 빌드와 Docker 기반 OpenAPI 계약 검사를 통과했다.
- 승인된 미태그 AI Workshop 이미지 36개와 종료 컨테이너를 제거해 Docker image 사용량을 `198.4 GB → 24.64 GB`로 줄였다. 볼륨과 shared BuildKit cache는 제거하지 않았다.
- PostgreSQL·Redis·Elasticsearch를 기존 named volume에 연결한 채 main Compose 경로로 재생성했고 모두 healthy다.
- 루트 Node 의존성·pnpm junction과 접근 가능한 캐시·임시물을 제거했다. 독립 프론트 구조에서 frozen lockfile, 58개 테스트, 타입 검사, 린트, 빌드와 OpenAPI 계약을 다시 검증했다.
- Docker가 `root:root`, mode `111`로 만든 두 물리 worktree와 네 임시 폴더를 PowerShell 7 관리자 경로에서 제거하고, 승인 경로 부재와 보존 대상 존재를 확인했다.
- Docker 용량 미회수 후속 조사에서 BuildKit 192.5 GB와 비-sparse `docker_data.vhdx` 219.079 GB를 확인했다. `uv` 캐시 5.0 GB가 이미지 레이어에 포함되고 `/app` 5.3 GB 전체 chown이 반복 copy-up되는 것이 원인이며, AI Workshop 전용 private cache ID 31개 143.849 GB를 분리했다.
- `uv` cache mount와 `/app` chown 제거를 적용한 이미지는 5.960 GB, 내장 uv cache 0 B이며 runtime·data ownership·Dockerfile build check를 통과했다.
- 구형 image와 승인된 구형 BuildKit chain 7개를 정확한 ID로 제거했다. 승인된 parent 2개는 승인 밖 child 2개가 참조해 보존했고 넓은 prune은 실행하지 않았다.
- Docker Desktop과 네 DB·검색 서비스를 정상 중단해 VHDX를 오프라인 압축했다. VHDX는 약 227.536 GB에서 57.250 GB, host 여유 공간은 약 32.624 GB에서 202.907 GB가 됐다.
- 재기동 후 AI Workshop PostgreSQL·Redis·Elasticsearch와 다른 프로젝트 PostgreSQL의 동일 container ID·volume mount·실제 응답을 확인했으며 Docker volume 52개를 모두 보존했다.
- 최종 검증에서 백엔드 테스트 424개·Ruff·mypy·OpenAPI 계약과 프론트 테스트 58개·타입 검사·린트·빌드가 통과했다.
- 추가 승인된 BuildKit child 2개와 parent 2개를 자식부터 제거해 Build cache를 24.25 GB에서 13.55 GB로 줄였다. VHDX 실제 크기와 host 여유 공간은 이번 논리 정리만으로 추가 감소하지 않았다.
- 프로젝트 개발 에이전트와 제품 런타임 에이전트를 분리하고, 공통 프로젝트 역할과 RAG 책임자 아래 전문 역할을 갖는 계층형 조직 설계를 사용자와 확정했다.
- 역할 선택·사전 고지, 구현과 독립 검증 분리, 전체 소스 하드코딩 방지, 성공 시 임시 기록 자동 정리와 계약 자동 검증 기준을 명세로 작성했다.
- 프로젝트 개발 에이전트 조직을 `main`과 원격에 반영한 뒤 승인에 따라 격리 worktree와 로컬·원격 기능 브랜치를 제거했다.
- 프로젝트 개발 에이전트 역할 계약, activation rule, workflow, 임시 기록 수명주기, Codex 어댑터와 자동 검증기를 구현하고 대표 역할 선택 시나리오를 검증했다.

### 완료 기준

- `/`와 `/labs`의 동일 월드 직접 렌더, RAG 방·관리자와 `/labs/rag` 진입 계약이 명확하다.
- 전체 viewport, desktop 말풍선, mobile 하단 패널과 접근성·반응형 검증 기준이 명확하다.
- 현재 공개된 RAG만 표시하고 미래 Lab placeholder, backend·DB·catalog 계약 변경을 범위에서 제외한다.
- 기존 공개 서비스 설계, 비전, 시스템 설계와 ADR가 새 화면 계약과 충돌하지 않는다.
- 사용자 승인 전 구현 계획과 프론트 소스 변경을 시작하지 않는다.

## 최근 완료 작업

최근 완료 작업은 가장 최신 항목부터 **최대 5개만 유지한다**.

1. 전체 화면 AI 연구소 월드 설계와 ADR 초안을 작성하고 6개 검토 지적을 보완해 독립 검토 `Ready`를 받았다. 사용자 승인 전 소스 구현은 변경하지 않았다.
2. 공개 캐릭터 dialog를 body portal로 분리하고 모바일 안전 영역을 추가했으며, 누락된 workshop 오류 경계·개인정보 fixture·WORKBOARD 계약 모순을 전체 계획 리뷰에서 수정했다. 프론트 122개·backend unit 423개·정적 검사·빌드와 desktop/mobile 실제 브라우저를 검증했다.
3. 공개·작업소·관리자 경계의 canonical 문서와 실행서를 2026-09-03 구현 상태에 맞추고, backend API 7개·unit 423개와 signed-out HTTP route를 검증했다.
4. 로그인 화면과 공개·작업소 탐색을 정렬하고 synthetic 로그인 fixture로 개인정보 없는 회귀 계약을 고정했다 (`e970a9b`, `95b727d`).
5. 공개 캐릭터 랜딩, AI Lab 장면과 RAG 기술 소개를 구현하고 dialog focus containment를 보강했다 (`abd479c`, `2958469`, `be4a9c1`).

## 다음 작업

1. 전체 화면 AI 연구소 월드 설계 문서 검토·승인
2. 승인 설계의 상세 구현 계획 작성
3. 기존 owner 세션으로 `/workshop/rag/search`와 `/admin/rag/configurations`의 실제 데이터 화면 smoke를 수행하거나 미검증 위험을 명시적으로 수용
4. 2단계 `다중 도메인과 공개 릴리스 기반` 상세 설계
5. 형식별 Parser Policy Version과 Saved RAG Configuration 연결, 재파싱·재청킹·재색인 수명주기 설계

## 결정이 필요한 항목

- owner 인증 smoke를 위해 사용자가 현재 로그인 화면에서 기존 계정으로 로그인할지, 자동 검증 없이 남은 위험을 수용할지 결정해야 한다. 비밀번호를 문서·명령·대화에 전달하지 않는다.

## 차단 요소

- `backend/.pytest-nextjs-final-contract`는 untracked지만 Windows 관리자 ACL 때문에 현재 비관리자 환경에서 삭제할 수 없다.
- `backend/.pytest-tmp`는 Git ignored 경로이며 같은 ACL 문제로 내부 확인과 삭제가 거부된다. 2026-09-03 기본 unit 실행도 이 경로 정리 단계에서 실패했고 fresh `%TEMP%` basetemp로 우회 검증했다. 두 경로 모두 애플리케이션 소스와 실행 데이터에는 영향을 주지 않으며, 대화형 Windows 관리자 세션에서 소유권과 내용을 확인한 뒤 정확 경로만 삭제해야 한다.
- 이번 backend unit 검증에서 만든 `.local-data/pytest-unit-current`도 정확 경로 삭제를 시도했으나 접근이 거부됐다. 애플리케이션 데이터에는 포함되지 않는 테스트 임시물이며 관리자 세션에서 해당 경로만 제거해야 한다.
- 현재 브라우저에는 owner 세션이 없고 비밀번호를 조회·재설정하지 않았으므로 `/workshop/rag/search`와 `/admin/rag/configurations`의 인증 후 실제 데이터 렌더링 smoke가 남아 있다.

## 작업 인계 메모

- 새 작업을 시작하기 전에 이 파일과 루트 `AGENTS.md`를 읽는다.
- 첫 RAG 검색 수직 슬라이스의 최종 증거와 선별 실패 기록은 `docs/worklogs/2026-09-01-rag-integration-verification.md`로 공식 인계했다.
- 작업 트리의 `.idea/`는 사용자 환경 파일이므로 별도 요청 없이 추적하거나 수정하지 않는다.
- RAG worktree의 Git 등록과 물리 폴더, 미등록 foundation 복사본, 네 테스트 임시 폴더가 모두 제거됐다. 상세 결과는 캐시 감사 보고서를 따른다.
- 루트 `.pnpm-store` junction과 `node_modules`는 제거됐다.
- 프론트 의존성은 `frontend/node_modules/.pnpm`에 독립 설치됐으며 루트 `node_modules`는 감사 보고서의 레거시 제거 후보로 확정했다.
- RAG 패키지 UI는 현재 Parser가 구성에 고정되지 않음을 명시한다. 다음 우선 작업은 형식별 Parser Policy Version과 패키지·산출물 수명주기 설계다.
- Next.js 프론트는 `http://127.0.0.1:5173`, 기존 호스트 FastAPI는 `http://127.0.0.1:18000`에서 실행한다. 2026-09-03 route smoke 뒤 FastAPI는 기존 프로세스를 유지했고 Next는 현재 소스 설정으로 재시작해 실행 중이다.
- 최종 Docker 상태와 잔여 BuildKit 계보는 `docs/worklogs/2026-09-01-cache-audit.md`를 정본으로 사용한다.
- 추가 승인된 잔여 BuildKit 네 레코드는 모두 제거됐으며 추가 Docker 정리는 새 조사와 승인 없이 진행하지 않는다.
- 프로젝트 개발 에이전트 조직 설계 정본은 `docs/superpowers/specs/2026-09-02-project-development-agent-organization-design.md`다.

## 갱신 규칙

- 작업을 시작할 때 `현재 작업`, `진행 상태`, `다음 작업`을 확인하고 필요한 경우 갱신한다.
- 작업을 끝낼 때 `최근 완료 작업`, `다음 작업`, `결정이 필요한 항목`, `차단 요소`를 갱신한다.
- 최근 완료 작업은 최대 5개만 유지한다. 여섯 번째 항목이 생기면 가장 오래된 항목을 제거한다.
- 장기 작업 이력이 필요해질 때만 제거 대상 기록을 `docs/worklogs/`의 기간별 문서로 옮긴다.
- 완료 항목에는 가능하면 관련 커밋, 설계 문서 또는 검증 결과를 연결한다.
- 실제 검증하지 않은 작업을 완료로 기록하지 않는다.
- 상세 실행 로그를 계속 누적하지 않고, 다음 작업에 필요한 상태와 결정만 남긴다.
- 날짜는 `YYYY-MM-DD` 형식으로 기록한다.
