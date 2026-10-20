import { createRoot } from "react-dom/client";
import { useState } from "react";
import { ChoiceGroup } from "../../src/shared/ui/ChoiceGroup";
import { GenerativeEvaluationPanel } from "../../src/features/rag/configurations/GenerativeEvaluationPanel";
import type { SavedConfiguration, Workspace } from "../../src/features/rag/configurations/api";
import "../../src/app/styles.css";
import "../../src/app/office-tailwind.css";

// Synthetic component harness only: no app routing, credentials or production data.
const configurations = [{ version_id: "candidate", name: "Synthetic candidate", version: 1, is_system: false,
  generation_profile_id: "generation", generation_execution_preview: { provider: "local_transformers" } }] as SavedConfiguration[];
const workspaces = [{ id: "workspace", name: "Synthetic workspace", kind: "company", expires_at: null }] as Workspace[];

function BoundaryExamples() {
  const [value, setValue] = useState("first");
  const [ordinary, setOrdinary] = useState("one");
  return <section aria-label="합성 경계 검사" style={{ maxWidth: "240px", margin: "1rem" }}>
    <ChoiceGroup variant="segmented" legend="좁은 영역의 긴 선택 문구" value={value} onChange={setValue}
      options={[{ value: "first", label: "기존에저장된평가자료와입력내용을그대로보존하여다시사용합니다" },
        { value: "blocked", label: "선택 불가", disabled: true }, { value: "last", label: "새 자료" }]} />
    <ChoiceGroup variant="segmented" legend="비활성 그룹" value="kept" onChange={() => { throw new Error("Disabled group changed"); }} disabled
      options={[{ value: "kept", label: "보존된 선택" }, { value: "other", label: "다른 선택" }]} />
    <ChoiceGroup legend="기본 원형 선택" value={ordinary} onChange={setOrdinary}
      options={[{ value: "one", label: "첫 선택" }, { value: "two", label: "다음 선택" }]} />
  </section>;
}

createRoot(document.getElementById("root")!).render(<>
  <main className="configuration-studio-shell" style={{ padding: "1rem", minHeight: "100vh" }}>
    <GenerativeEvaluationPanel configurations={configurations} workspaces={workspaces} />
  </main><BoundaryExamples /></>,
);
