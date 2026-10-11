import { describe, expect, it } from "vitest";

import { findFlow, validateFlowCatalog } from "./catalog";
import type { FlowDefinition } from "./types";
import { ragFlows } from "../rag/flows/catalog";
import { projectAgentFlows } from "../project-agents/flows";

function graph(): FlowDefinition {
  return {
    id: "example", categoryId: "common", categoryLabel: "공통", title: "합성 절차", summary: "검증용 절차",
    version: "1", reviewedAt: "2026-10-03", entryNodeId: "start", links: [], sources: [],
    architecture: { summary: "합성 구성", technologies: [{ name: "규칙", purpose: "검사", implementation: "정해진 기준 비교" }], steps: [{ title: "입력", technology: "규칙", explanation: "값 검사" }], example: { question: "합성 입력", explanation: "검사 결과" }, boundaries: ["합성 예시"], references: [{ title: "기준", reference: "docs/vision/project-vision.md" }] },
    phases: [{ id: "all", title: "절차", summary: "합성 단계 묶음", nodeIds: ["start", "review", "finish"], technical: { components: [{ name: "규칙", role: "판정" }], mechanism: ["입력을 검사합니다."], checks: ["검사 결과"], references: [{ title: "합성 설명", reference: "docs/vision/project-vision.md" }] } }],
    nodes: ["start", "review", "finish"].map((id) => ({ id, label: id, kind: id === "start" ? "start" : id === "finish" ? "result" : "decision", input: "입력", process: "처리", output: "결과", failures: [] })),
    edges: [{ from: "start", to: "review", condition: "접수" }, { from: "review", to: "finish", condition: "승인" }],
  };
}

describe("flow catalog integrity", () => {
  it("rejects incomplete technology descriptions and disconnected empty architecture content", () => {
    const flow = graph();
    expect(() => validateFlowCatalog([{ ...flow, architecture: { ...flow.architecture, technologies: [] } }])).toThrow("flow_architecture_invalid");
    expect(() => validateFlowCatalog([{ ...flow, architecture: { ...flow.architecture, steps: [{ title: "입력", technology: "", explanation: "검사" }] } }])).toThrow("flow_architecture_invalid");
    expect(() => validateFlowCatalog([{ ...flow, architecture: { ...flow.architecture, example: { question: "질문", explanation: "" } } }])).toThrow("flow_architecture_invalid");
  });
  it("provides an actual technology architecture and an explicitly illustrative example for each flow", () => {
    for (const flow of [...ragFlows, ...projectAgentFlows]) {
      expect(flow.architecture).toBeDefined();
      expect(flow.architecture.steps.length).toBeGreaterThanOrEqual(4);
      expect(flow.architecture.technologies.length).toBeGreaterThan(0);
      expect(flow.architecture.example.question.trim()).not.toBe("");
      expect(flow.architecture.references.length).toBeGreaterThan(0);
    }
  });

  it("provides a small overview and explained technical mechanisms for every real step", () => {
    for (const flow of [...ragFlows, ...projectAgentFlows]) {
      expect(flow.phases).toBeDefined();
      expect(flow.phases.length).toBeGreaterThanOrEqual(4);
      expect(flow.phases.length).toBeLessThanOrEqual(5);
      expect(flow.phases.flatMap(phase => phase.nodeIds).sort()).toEqual(flow.nodes.map(node => node.id).sort());
      for (const phase of flow.phases) {
        expect(phase.technical.components.length).toBeGreaterThan(0);
        expect(phase.technical.mechanism.length).toBeGreaterThan(0);
        expect(phase.technical.checks.length).toBeGreaterThan(0);
        expect(phase.technical.references.length).toBeGreaterThan(0);
      }
    }
  });

  it("rejects missing, duplicate or unknown mappings between overview and technical steps", () => {
    const flow = graph();
    const phase = flow.phases[0];
    expect(() => validateFlowCatalog([{ ...flow, phases: [] }])).toThrow("flow_phase_invalid");
    expect(() => validateFlowCatalog([{ ...flow, phases: [{ ...phase, nodeIds: ["start", "review"] }] }])).toThrow("flow_phase_coverage_invalid");
    expect(() => validateFlowCatalog([{ ...flow, phases: [{ ...phase, nodeIds: [...phase.nodeIds, "absent"] }] }])).toThrow("flow_phase_coverage_invalid");
    expect(() => validateFlowCatalog([{ ...flow, phases: [{ ...phase, nodeIds: [...phase.nodeIds, "start"] }] }])).toThrow("flow_phase_coverage_invalid");
  });

  it("loads exactly the current five flows under two categories", () => {
    const flows = [...ragFlows, ...projectAgentFlows];
    expect(() => validateFlowCatalog(flows)).not.toThrow();
    expect(flows.map(({ categoryId, id }) => `${categoryId}/${id}`)).toEqual([
      "rag/ingestion", "rag/answer", "rag/sessions", "rag/multiturn", "common/development-agents",
    ]);
  });

  it("resolves only the exact category and flow pair", () => {
    expect(findFlow(ragFlows, "rag", "sessions")?.title).toBe("대화 세션 관리");
    expect(findFlow(ragFlows, "common", "sessions")).toBeUndefined();
    expect(findFlow(ragFlows, "rag", "missing")).toBeUndefined();
  });

  it("routes successful model responses with insufficient evidence directly past citation validation", () => {
    const answer = findFlow(ragFlows, "rag", "answer")!;
    expect(answer.edges).toContainEqual({ from: "generation", to: "insufficient", condition: "모델 응답의 근거 부족" });
  });

  it("rejects duplicate flow identities", () => {
    const flow = graph();
    expect(() => validateFlowCatalog([flow, flow])).toThrow("flow_identity_duplicate");
  });

  it("rejects duplicate node identities", () => {
    const flow = graph();
    expect(() => validateFlowCatalog([{ ...flow, nodes: [...flow.nodes, flow.nodes[0]] }])).toThrow("flow_node_duplicate");
  });

  it("rejects edges with missing targets and missing entries", () => {
    const flow = graph();
    expect(() => validateFlowCatalog([{ ...flow, edges: [...flow.edges, { from: "review", to: "absent", condition: "오류" }] }])).toThrow("flow_edge_invalid");
    expect(() => validateFlowCatalog([{ ...flow, entryNodeId: "absent" }])).toThrow("flow_entry_invalid");
  });

  it("rejects isolated nodes even if they are valid results", () => {
    const flow = graph();
    expect(() => validateFlowCatalog([{ ...flow, nodes: [...flow.nodes, { ...flow.nodes[2], id: "isolated" }] }])).toThrow("flow_node_unreachable");
  });

  it("rejects a reachable loop with no path to a result", () => {
    const flow = graph();
    expect(() => validateFlowCatalog([{ ...flow, nodes: flow.nodes.slice(0, 2), edges: [{ from: "start", to: "review", condition: "진행" }, { from: "review", to: "review", condition: "재시도" }] }])).toThrow("flow_result_unreachable");
  });

  it("allows a review loop with a reachable result and multiple result branches", () => {
    const flow = graph();
    const branching = { ...flow, phases: [{ ...flow.phases[0], nodeIds: [...flow.phases[0].nodeIds, "rejected"] }], nodes: [...flow.nodes, { ...flow.nodes[2], id: "rejected" }], edges: [...flow.edges, { from: "review", to: "review", condition: "수정" }, { from: "review", to: "rejected", condition: "거절" }] };
    expect(() => validateFlowCatalog([branching])).not.toThrow();
  });
});
