export function comparisonModelKey(request: { provider: string; model: string }): string {
  return JSON.stringify([request.provider, request.model]);
}

function providerKind(provider: string): "api" | "local" | null {
  // Narrow display-label compatibility; do not infer execution location from model names.
  const label = provider.trim().toLowerCase().replace(/\s+/g, " ");
  if (["api", "openai", "openai api"].includes(label)) return "api";
  if (["local", "로컬", "ollama", "ollama · 로컬"].includes(label)) return "local";
  return null;
}

export function comparisonModelOrder(requests: readonly { provider: string; model: string }[]): string[] {
  const groups = [...new Map(requests.map(request => [comparisonModelKey(request), {
    key: comparisonModelKey(request), kind: providerKind(request.provider),
  }])).values()];
  const known = [...groups.filter(group => group.kind === "api"), ...groups.filter(group => group.kind === "local")];
  let nextKnown = 0;
  // Unknown groups keep their original positions; reorder only the recognized display slots.
  return groups.map(group => group.kind === null ? group.key : known[nextKnown++].key);
}

export function formatComparisonDuration(seconds: number | null | undefined): string {
  return seconds == null ? "미측정" : `${seconds.toFixed(3)}초`;
}

export function formatComparisonMoney(amount: string | null | undefined): string {
  return amount == null ? "미확인" : `USD ${amount}`;
}

export function formatComparisonTokens(tokens: number | null | undefined): string {
  return tokens == null ? "미보고" : tokens.toLocaleString("ko-KR");
}
