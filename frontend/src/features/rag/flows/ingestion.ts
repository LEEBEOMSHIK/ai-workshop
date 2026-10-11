import { ragFlowPhases } from "./technical";
import { ragArchitectures } from "./architecture";
import type { FlowDefinition } from "../../flowcharts/types";
import { routes } from "../../../shared/routing/routes";

export const ingestionFlow: FlowDefinition = {
  id: "ingestion", categoryId: "rag", categoryLabel: "RAG", title: "문서 처리·색인",
  summary: "파일 저장과 검색 준비는 서로 다른 단계입니다. 원본 검증부터 활성 색인까지 확인합니다.",
  version: "3", reviewedAt: "2026-10-04", entryNodeId: "upload",
  architecture: ragArchitectures.ingestion,
  phases: ragFlowPhases.ingestion,
  nodes: [
    { id: "upload", label: "원본 업로드·검증", kind: "start", input: "사용자가 올린 파일과 저장 공간", process: "원본을 저장하고 정확한 바이트의 크기·SHA-256을 확인합니다. 저장 Job이 검증 전달을 추적합니다.", output: "검증된 원본 버전", failures: ["저장 실패나 무결성 불일치 시 READY로 바꾸지 않습니다."] },
    { id: "asset", label: "Platform 원본 준비", kind: "action", input: "검증된 Asset Version", process: "원본을 READY로 전환하고 현재 문서 버전을 원자적으로 갱신합니다. 이 상태만으로 RAG 검색 준비가 끝나지는 않습니다.", output: "활성 READY 원본", failures: [] },
    { id: "demand", label: "색인 수요·비동기 전달", kind: "decision", input: "원본과 색인 프로파일 구독", process: "원본·프로파일별 멱등 작업을 만들고 outbox에서 worker에 전달합니다. beat의 주기 작업이 누락 전달·구독 수요를 복구합니다.", output: "색인 작업 또는 대기 상태", failures: ["worker·beat의 중지는 업로드 응답과 별개로 처리를 지연시킵니다."] },
    { id: "parse", label: "파싱·OCR·문서 구조", kind: "action", input: "활성 원본과 Document Processing Profile", process: "형식별 파싱과 구성된 OCR로 구조 요소·원문 위치를 보존한 공통 문서 모델을 만듭니다. 다른 파서로 조용히 전환하지 않습니다.", output: "구조화된 문서와 provenance", failures: ["지원하지 않는 형식·파서 실패·요소의 부분 실패를 기록합니다."] },
    { id: "chunk", label: "구조 청킹·임베딩", kind: "action", input: "문서 구조와 색인 프로파일", process: "구조와 원문 위치를 유지해 청크를 만들고 구성된 임베딩 모델로 벡터를 생성합니다. 임베딩·청킹 변경은 호환되는 새 색인 버전을 사용합니다.", output: "위치 정보가 있는 청크·벡터", failures: ["선택 모델 실패나 원본 비활성 전환을 숨기지 않습니다."] },
    { id: "index", label: "BM25·벡터 색인", kind: "action", input: "청크·벡터와 동일 원본 버전", process: "검색 어댑터로 BM25와 dense 검색에 사용할 색인을 구성하고 원본 활성 여부를 다시 확인합니다.", output: "검증 전 검색 projection", failures: ["전달·실행 중 원본이 바뀌면 이전 원본 작업을 정상 활성화하지 않습니다."] },
    { id: "verify", label: "완성·별칭 검증", kind: "decision", input: "색인과 기대 청크 수·provenance", process: "개수·벡터·원문 추적과 별칭 상태를 확인합니다. 미종료 별칭 요청이나 유지보수 차단을 검증 성공으로 간주하지 않습니다.", output: "활성화 가능 여부", failures: ["별칭 차단은 종료 증거 없이 해제하지 않습니다."] },
    { id: "ready", label: "RAG 검색 준비 완료", kind: "result", input: "완성 검증 통과", process: "RAG Projection을 READY·활성 상태로 전환합니다. 권한과 연결 구성이 허용한 검색에서 사용합니다.", output: "활성 검색 가능 projection", failures: [] },
    { id: "waiting", label: "작업 대기", kind: "result", input: "색인 수요 없음 또는 전달 대기", process: "원본 저장 상태를 유지하고 작업 수요·전달·worker 상태를 확인합니다. 검색 준비 완료로 표시하지 않습니다.", output: "저장된 원본과 처리 대기", failures: [] },
    { id: "failed", label: "실패·부분 준비·차단", kind: "result", input: "파싱·모델·원본·별칭 검증 문제", process: "실패와 부분 실패를 기록합니다. READY가 아닌 버전은 일반 검색에 포함하지 않으며 재시도 가능 여부는 각 작업 정책을 따릅니다.", output: "진단 가능한 실패 또는 부분 상태", failures: [] },
  ],
  edges: [
    { from: "upload", to: "asset", condition: "무결성 검증 통과" }, { from: "upload", to: "failed", condition: "저장·검증 실패" },
    { from: "asset", to: "demand", condition: "현재 활성 원본" }, { from: "demand", to: "parse", condition: "색인 수요·전달 완료" }, { from: "demand", to: "waiting", condition: "수요 없음·전달 대기" },
    { from: "parse", to: "chunk", condition: "문서 구조 준비" }, { from: "parse", to: "failed", condition: "파싱 실패·부분 실패" },
    { from: "chunk", to: "index", condition: "청크·벡터 준비" }, { from: "chunk", to: "failed", condition: "모델 실패·원본 비활성" },
    { from: "index", to: "verify", condition: "색인 기록 완료" }, { from: "index", to: "failed", condition: "색인 실패·원본 변경" },
    { from: "verify", to: "ready", condition: "완성·별칭 검증 통과" }, { from: "verify", to: "failed", condition: "불일치·별칭 차단" },
  ],
  links: [{ label: "파일함", href: routes.workshopHome, audience: "workspace" }, { label: "RAG 구성", href: routes.adminRagConfigurations, audience: "owner" }],
  sources: [{ title: "RAG 문서 처리 설계", reference: "docs/labs/rag/design.md" }, { title: "별칭 검증 경계", reference: "docs/decisions/0032-rag-alias-recovery.md" }],
};
