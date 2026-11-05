import { useState } from "react";
import { createRoot } from "react-dom/client";
import { Button, ButtonLink } from "../../src/shared/ui/Button";
import { ChoiceGroup } from "../../src/shared/ui/ChoiceGroup";
import { WorkspaceCreateForm } from "../../src/features/workspaces/WorkspaceCreateForm";
import { IssueManagement } from "../../src/features/issue-history/IssueManagement";
import issueStyles from "../../src/features/issue-history/IssueHistoryPage.module.css";
import { GenerativeEvaluationPanel } from "../../src/features/rag/configurations/GenerativeEvaluationPanel";
import type { SavedConfiguration, Workspace } from "../../src/features/rag/configurations/api";
import "../../src/app/styles.css";
import "../../src/app/office-tailwind.css";

// Every fetch is answered locally; mutations deliberately return a synthetic error.
// The server additionally rejects /api and CSP blocks connections to other origins.
let intercepted = 0;
globalThis.fetch = async (input, init) => {
  intercepted += 1;
  const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
  const url = new URL(input instanceof Request ? input.url : String(input), location.origin);
  let body: unknown = [];
  let status = 200;
  if (method !== "GET") {
    status = 403;
    body = { error: { code: "synthetic_only", message: "합성 화면입니다. 실제 저장 없이 입력과 오류 표시만 검사합니다." } };
  } else if (url.pathname === "/api/v1/admin/issue-history/documents") {
    body = { items: [] };
  } else if (!["/api/v1/rag/generative-evaluations", "/api/v1/rag/generative-evaluations/policies"].includes(url.pathname)) {
    status = 403;
    body = { error: { code: "synthetic_only", message: "Preview fetch blocked." } };
  }
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
};

const configurations: SavedConfiguration[] = [{ version_id: "synthetic-candidate", name: "합성 후보 — 긴한글식별자표시와줄바꿈검사", version: 1,
  id: "synthetic-configuration", owner_id: null, is_default: false, is_system: false, experimental: true,
  document_processing_profile_id: "synthetic-processing", indexing_profile_id: "synthetic-indexing", retrieval_profile_id: "synthetic-retrieval",
  workspace_ids: ["synthetic-workspace"], evaluation_state: "draft", answer_ready: false, search_ready: false, service_ready: false,
  answer_reasons: ["synthetic_only"], search_reasons: ["synthetic_only"],
  answer_policy: { id: "synthetic-policy", version: 1, mode: "generative", conflict_mode: "separate_sources",
    require_complete_provenance: true, min_keyword_coverage: 0, min_semantic_score: 0 },
  generation_profile_id: "synthetic-generation", generation_execution_preview: null }];
const workspaces: Workspace[] = [{ id: "synthetic-workspace", name: "합성 작업공간", kind: "company", expires_at: null }];
const params = new URLSearchParams(location.search);
const section = params.get("section") ?? "common";
const isFrame = params.get("frame") === "1";

function inspection() {
  const region = document.getElementById("specimen")!;
  const controls = [...region.querySelectorAll<HTMLElement>("button,select,input:not([type=radio]):not([type=checkbox]),summary")]
    .filter(el => el.getClientRects().length > 0)
    .map(el => ({ label: el.getAttribute("aria-label") ?? el.textContent?.trim().slice(0, 55) ?? el.tagName,
      height: Math.round(el.getBoundingClientRect().height * 10) / 10,
      width: Math.round(el.getBoundingClientRect().width * 10) / 10,
      minWidth: getComputedStyle(el).minWidth, disabled: el.matches(":disabled") }));
  const visible = (el: Element) => el.getClientRects().length > 0;
  const colorData = (el: Element) => {
    const style = getComputedStyle(el);
    return { text: el.textContent?.trim().slice(0, 55), color: style.color,
      background: style.backgroundColor, border: style.borderColor };
  };
  const radios = [...region.querySelectorAll<HTMLInputElement>("input[type=radio]")].filter(visible)
    .map(el => ({ name: el.name, value: el.value, checked: el.checked, disabled: el.disabled,
      width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height,
      labelHeight: el.closest("label")?.getBoundingClientRect().height ?? null,
      visuallyHidden: getComputedStyle(el).clipPath !== "none" || getComputedStyle(el).opacity === "0" }));
  const headings = [...region.querySelectorAll("h1")].filter(visible).map(el => ({
    text: el.textContent, fontFamily: getComputedStyle(el).fontFamily,
    fontSize: getComputedStyle(el).fontSize, lineHeight: getComputedStyle(el).lineHeight,
  }));
  return JSON.stringify({ synthetic: true, authenticated: false, backendCalls: 0, interceptedFetches: intercepted,
    viewport: innerWidth, documentOverflow: document.documentElement.scrollWidth > innerWidth + 1,
    controlTargets: controls, below44px: controls.filter(c => c.height < 43.5),
    radios, headings,
    inputs: [...region.querySelectorAll("input:not([type=radio]):not([type=checkbox]),select,textarea")].filter(visible).map(colorData),
    buttons: [...region.querySelectorAll("button")].filter(visible).map(colorData),
    computed: { bodyFont: getComputedStyle(document.body).fontFamily,
      text: getComputedStyle(region).color, background: getComputedStyle(document.body).backgroundColor },
    note: "Geometry observation only; keyboard and contrast require root review. No automated clicks." }, null, 2);
}

function Samples() {
  const [choice, setChoice] = useState("saved");
  const [clicks, setClicks] = useState(0);
  const [report, setReport] = useState("");
  return <main className={section === "workspace" || section === "common" ? "workspace-area" : "administration-area"}
    style={{ padding: "1rem", minWidth: 0 }}>
    <p>합성 전용 · 실제 저장/모델 호출 없음 · {section}</p>
    <section id="specimen" style={{ minWidth: 0 }}>
      {section === "common" && <>
        <h1>작업용 제목과 조작 상태</h1>
        <p>긴한글식별자가공백없이이어져도좁은화면에서내용과포커스를유지해야합니다.</p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: ".5rem", marginBottom: "1rem" }}>
          <Button variant="primary" onClick={() => setClicks(v => v + 1)}>기본 실행</Button>
          <Button variant="secondary">보조 동작</Button>
          <ButtonLink href="#common">간편 설정 링크</ButtonLink>
          <Button variant="quiet">조용한 동작</Button>
          <Button variant="danger">삭제 예시</Button>
          <Button disabled>비활성 · 입력 유지</Button>
          <Button aria-disabled="true">접근성 비활성</Button>
        </div>
        <div className="conversation-sidebar">
          <button type="button" aria-current="page">선택된 대화 예시</button>
        </div>
        <p role="status">합성 기본 버튼 클릭 {clicks}회</p>
        <ChoiceGroup variant="segmented" legend="자료 준비 방식" value={choice} onChange={setChoice}
          options={[{ value: "saved", label: "저장된합성자료와작성중입력을유지하여재사용" },
            { value: "create", label: "새 자료 작성" }, { value: "disabled", label: "선택 불가", disabled: true }]} />
        <ChoiceGroup legend="기본 원형 선택" value={choice} onChange={setChoice}
          options={[{ value: "saved", label: "기존 자료" }, { value: "create", label: "새 자료" }]} />
        <label><input type="checkbox" /> 기본 체크박스 기호와 라벨</label>
      </>}
      {section === "workspace" && <><h1>작업공간 폼</h1><WorkspaceCreateForm canCreateCompany onCreated={() => {}} /></>}
      {section === "issues" && <div className={issueStyles.page}><h1>문제 이력 작성</h1><IssueManagement categories={[]} issue={null} onSaved={() => {}} /></div>}
      {section === "evaluation" && <div className="configuration-studio-shell"><h1>평가 준비</h1><GenerativeEvaluationPanel configurations={configurations} workspaces={workspaces} /></div>}
    </section>
    <hr />
    <button type="button" onClick={() => setReport(inspection())}>현재 배치 검사</button>
    {report && <pre aria-label="합성 배치 검사 결과" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: ".8rem" }}>{report}</pre>}
  </main>;
}

function Preview() {
  const requested = Number(params.get("width") ?? 375);
  const width = [320, 375, 1280].includes(requested) ? requested : 375;
  return <main style={{ padding: "1rem" }}>
    <h1>합성 디자인 시스템 검사</h1>
    <p>로그인·라우팅·실제 API는 검증하지 않습니다. 아래 프레임은 실제 CSS media query 폭입니다.</p>
    <nav aria-label="합성 화면 선택" style={{ display: "flex", flexWrap: "wrap", gap: "1rem" }}>
      {["common", "workspace", "issues", "evaluation"].map(value => <a key={value} href={`?section=${value}&width=${width}`}>{value}</a>)}
      {[320, 375, 1280].map(value => <a key={value} href={`?section=${section}&width=${value}`}>{value}px</a>)}
    </nav>
    <div style={{ overflowX: "auto", marginTop: "1rem" }}>
      <iframe title={`${section} 합성 ${width}px 실제 viewport`} src={`?frame=1&section=${section}`} width={width} height={1400}
        style={{ display: "block", border: 0, maxWidth: "none" }} />
    </div>
  </main>;
}

createRoot(document.getElementById("root")!).render(isFrame ? <Samples /> : <Preview />);
