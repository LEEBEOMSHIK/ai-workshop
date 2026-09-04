import ragLabAgentsManifest from "../../content/rag-lab-agents.json";

export interface RagLabAgent {
  slug: string;
  name: string;
  role: string;
  statusLabel: string;
  eyebrow: string;
  intro: string;
  currentWork: string;
  inputOutput: string;
  handoff: string;
}

const agentKeys = [
  "slug",
  "name",
  "role",
  "statusLabel",
  "eyebrow",
  "intro",
  "currentWork",
  "inputOutput",
  "handoff",
] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const valueKeys = Object.keys(value);
  return valueKeys.length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function requiredString(value: unknown, error: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(error);
  }

  return value;
}

function parseAgent(input: unknown): RagLabAgent {
  if (!isRecord(input) || !hasExactKeys(input, agentKeys)) {
    throw new Error("rag_lab_agent_invalid");
  }

  const slug = requiredString(input.slug, "rag_lab_agent_slug_invalid");
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/u.test(slug)) {
    throw new Error("rag_lab_agent_slug_invalid");
  }

  return {
    slug,
    name: requiredString(input.name, "rag_lab_agent_string_invalid"),
    role: requiredString(input.role, "rag_lab_agent_string_invalid"),
    statusLabel: requiredString(input.statusLabel, "rag_lab_agent_string_invalid"),
    eyebrow: requiredString(input.eyebrow, "rag_lab_agent_string_invalid"),
    intro: requiredString(input.intro, "rag_lab_agent_string_invalid"),
    currentWork: requiredString(input.currentWork, "rag_lab_agent_string_invalid"),
    inputOutput: requiredString(input.inputOutput, "rag_lab_agent_string_invalid"),
    handoff: requiredString(input.handoff, "rag_lab_agent_string_invalid"),
  };
}

export function parseRagLabAgents(input: unknown): readonly RagLabAgent[] {
  if (!isRecord(input)) {
    throw new Error("rag_lab_agent_registry_invalid");
  }
  if (!Object.hasOwn(input, "agents") || !Array.isArray(input.agents)) {
    throw new Error("rag_lab_agents_invalid");
  }
  if (!hasExactKeys(input, ["agents"])) {
    throw new Error("rag_lab_agent_registry_invalid");
  }

  const agents = input.agents.map(parseAgent);
  const slugs = new Set<string>();
  for (const agent of agents) {
    if (slugs.has(agent.slug)) {
      throw new Error("rag_lab_agent_slug_duplicate");
    }
    slugs.add(agent.slug);
  }

  return agents;
}

export function listRagLabAgents(): readonly RagLabAgent[] {
  return parseRagLabAgents(ragLabAgentsManifest);
}
