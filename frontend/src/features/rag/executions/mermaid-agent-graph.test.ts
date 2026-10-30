import { buildAgentFlow } from "./agent-flow";
import { syntheticDeepAgentTrace, syntheticSteppedAgentTrace } from "./agent-trace.test-support";
import { buildMermaidGraph, encodeMermaidLabel } from "./mermaid-agent-graph";
import { edgePath, fitBounds, moveByClientDelta } from "./mermaid-graph-geometry";

it("renders every recorded step and only the actual parent relationships", () => {
  const graph = buildMermaidGraph(buildAgentFlow(syntheticSteppedAgentTrace().spans));
  expect(graph.nodes.map(node => node.spanId)).toEqual(["manager", "manager-model", "delegate", "writer", "model"]);
  expect(graph.edges.map(edge => [edge.sourceId, edge.targetId])).toEqual([
    ["manager", "manager-model"], ["manager", "delegate"], ["delegate", "writer"], ["writer", "model"],
  ]);
  expect(graph.source).toContain("flowchart LR");
  expect(graph.source).toContain("n0 e0@--> n1");
  expect(graph.source).not.toContain("n0 e0@--> n3");
});

it("keeps duplicate names separate and encodes diagram directives instead of executing them", () => {
  const trace = syntheticSteppedAgentTrace();
  trace.spans[0].name = 'same\"]\nclick n0 href "https://invalid.example"\n%%{init: {securityLevel: loose}}%%';
  trace.spans[3].name = trace.spans[0].name;
  const graph = buildMermaidGraph(buildAgentFlow(trace.spans));
  expect(graph.nodes[0].key).not.toBe(graph.nodes[3].key);
  expect(graph.nodes[0].spanId).not.toBe(graph.nodes[3].spanId);
  expect(graph.source).not.toMatch(/^\s*click n0/m);
  expect(graph.source).not.toContain("%%{");
  expect(encodeMermaidLabel('<script>"&[]')).not.toMatch(/[<>"&\[\]]/);
  expect(encodeMermaidLabel("한글 에이전트")).toBe("한글 에이전트");
});

it("does not invent connections for missing parents or cycles", () => {
  const trace = syntheticSteppedAgentTrace();
  trace.spans[0].parent_id = "writer";
  trace.spans[1].parent_id = "missing";
  const graph = buildMermaidGraph(buildAgentFlow(trace.spans));
  expect(graph.nodes).toHaveLength(5);
  expect(graph.edges).toHaveLength(0);
});

it("supports deep records without recursive graph rendering", () => {
  const graph = buildMermaidGraph(buildAgentFlow(syntheticDeepAgentTrace().spans));
  expect(graph.nodes).toHaveLength(64);
  expect(graph.edges).toHaveLength(63);
});

it("updates edge endpoints on node boundaries when a connected node moves", () => {
  const source = { x: 0, y: 0, width: 100, height: 60 };
  expect(edgePath(source, { ...source, x: 300 })).toBe("M 50 0 L 250 0");
  expect(edgePath(source, { ...source, y: 200 })).toBe("M 0 30 L 0 170");
  expect(edgePath(source, { ...source, x: 0 })).not.toContain("NaN");
});

it("converts pointer movement through the current zoom and fits moved nodes", () => {
  expect(moveByClientDelta({ x: 100, y: 40 }, { x: 30, y: -20 }, 2)).toEqual({ x: 115, y: 30 });
  expect(fitBounds([{ x: -100, y: 80, width: 100, height: 60 }, { x: 300, y: 200, width: 80, height: 40 }], 20))
    .toEqual({ x: -170, y: 30, width: 530, height: 210 });
  expect(fitBounds([], 20)).toEqual({ x: 0, y: 0, width: 800, height: 400 });
});
