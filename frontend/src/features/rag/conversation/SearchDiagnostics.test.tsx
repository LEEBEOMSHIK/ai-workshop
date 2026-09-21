import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SearchDiagnostics } from "./SearchDiagnostics";

it("separates raw scores, cosine, missing values and stage times without claiming accuracy", async () => {
  render(<SearchDiagnostics query="resolved synthetic question" diagnostics={{
    candidate_scope: "returned_hits", min_keyword_coverage: 0.5, min_semantic_score: 0.9,
    stages_ms: { retrieval: 0, contextualization: null, total: 12 },
    candidates: [{
      source: { document_id: "doc", asset_version_id: "asset", asset_version_number: 1,
        workspace_id: "space", folder_id: null, projection_id: "projection", chunk_id: "chunk",
        title: "synthetic.txt", media_type: "text/plain", section_path: ["section"], fused_score: 0.02 },
      evidence_unit_id: null, sparse_score: 8.2, dense_score: null, sparse_rank: 1, dense_rank: null,
      fused_rank: 1, keyword_coverage: 0.4, semantic_score: 0.92,
      eligible: true, selected: true, reason: "selected",
    }],
  }} />);
  await userEvent.setup().click(screen.getByText(/검색 근거·유사도/));
  expect(screen.getByText("resolved synthetic question")).toBeVisible();
  expect(screen.getByText("문맥 코사인 유사도")).toBeVisible();
  expect(screen.getByText("8.2000")).toBeVisible();
  expect(screen.getAllByText("미계산").length).toBeGreaterThan(0);
  expect(screen.getByText("미실행")).toBeVisible();
  expect(screen.getByText("0.0 ms")).toBeVisible();
  expect(screen.queryByText(/정확도.*%/)).not.toBeInTheDocument();
});
