export interface FlowNode {
  readonly id: string;
  readonly label: string;
  readonly kind: "start" | "action" | "decision" | "result";
  readonly input: string;
  readonly process: string;
  readonly output: string;
  readonly failures: readonly string[];
}

export interface FlowEdge {
  readonly from: string;
  readonly to: string;
  readonly condition: string;
}

export interface FlowLink {
  readonly label: string;
  readonly href: string;
  readonly audience: "workspace" | "owner";
}

export interface FlowPhase {
  readonly id: string;
  readonly title: string;
  readonly summary: string;
  readonly nodeIds: readonly string[];
  readonly technical: {
    readonly components: readonly { name: string; role: string }[];
    readonly mechanism: readonly string[];
    readonly checks: readonly string[];
    readonly references: readonly { title: string; reference: string }[];
  };
}

export interface FlowArchitecture {
  readonly summary: string;
  readonly technologies: readonly { name: string; purpose: string; implementation: string }[];
  readonly steps: readonly { title: string; technology: string; explanation: string }[];
  readonly example: { question: string; followup?: string; explanation: string };
  readonly boundaries: readonly string[];
  readonly references: readonly { title: string; reference: string }[];
}

export interface FlowDefinition {
  readonly id: string;
  readonly categoryId: string;
  readonly categoryLabel: string;
  readonly title: string;
  readonly summary: string;
  readonly version: string;
  readonly reviewedAt: string;
  readonly entryNodeId: string;
  readonly phases: readonly FlowPhase[];
  readonly architecture: FlowArchitecture;
  readonly nodes: readonly FlowNode[];
  readonly edges: readonly FlowEdge[];
  readonly links: readonly FlowLink[];
  readonly sources: readonly { title: string; reference: string }[];
}
