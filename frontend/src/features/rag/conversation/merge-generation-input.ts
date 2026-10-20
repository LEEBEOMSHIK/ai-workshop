import type { DomainSearchResult } from "./api";
import type { ConversationDetail } from "./sessions-api";

function sameJson(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (left === null || right === null || typeof left !== "object" || typeof right !== "object") return false;
  if (Array.isArray(left) || Array.isArray(right)) {
    return Array.isArray(left) && Array.isArray(right) && left.length === right.length
      && left.every((item, index) => sameJson(item, right[index]));
  }
  const a = left as Record<string, unknown>;
  const b = right as Record<string, unknown>;
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length
    && keys.every(key => Object.hasOwn(b, key) && sameJson(a[key], b[key]));
}

function withoutInput(response: DomainSearchResult) {
  if (!response.diagnostics) return response;
  const diagnostics = { ...response.diagnostics };
  delete diagnostics.generation_input;
  return { ...response, diagnostics };
}

// A completed recovery GET can win before the original POST returns. Enrich only
// its matching, unchanged, unredacted turn; never replay POST state over newer UI.
export function mergeGenerationInput(current: ConversationDetail | null, posted: ConversationDetail,
  requestId: string): ConversationDetail | null {
  if (!current || current.id !== posted.id || current.revision !== posted.revision) return current;
  const oldTurns = current.turns.filter(turn => turn.request_id === requestId);
  const newTurns = posted.turns.filter(turn => turn.request_id === requestId);
  if (oldTurns.length !== 1 || newTurns.length !== 1) return current;
  const oldTurn = oldTurns[0]; const newTurn = newTurns[0];
  if (oldTurn.status !== "completed" || newTurn.status !== "completed"
    || oldTurn.redacted || newTurn.redacted || !oldTurn.request_scope || !newTurn.request_scope
    || !oldTurn.execution_terminated || !newTurn.execution_terminated
    || !oldTurn.response?.diagnostics || !newTurn.response?.diagnostics
    || oldTurn.response.diagnostics.generation_input || !newTurn.response.diagnostics.generation_input) return current;
  // observation_complete is assigned only to the live POST after persistence.
  // It is not restored by GET; preserve the current value rather than merging it.
  if (!sameJson({ ...oldTurn, response: null, observation_complete: null },
    { ...newTurn, response: null, observation_complete: null })
    || !sameJson(withoutInput(oldTurn.response), withoutInput(newTurn.response))) return current;
  const response = { ...oldTurn.response, diagnostics: { ...oldTurn.response.diagnostics,
    generation_input: newTurn.response.diagnostics.generation_input } };
  return { ...current, turns: current.turns.map(turn => turn === oldTurn ? { ...turn, response } : turn) };
}
