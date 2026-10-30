import type { ConversationTurn } from "./sessions-api";

type TurnExecutionState = Pick<ConversationTurn, "status" | "execution_terminated" | "error_code">;

// Match the conversation reservation contract. Legacy failed/interrupted turns
// without an explicit termination error retain their existing retry behavior.
export function isTerminationUnconfirmed(turn: TurnExecutionState): boolean {
  return !turn.execution_terminated
    && (turn.status === "cancelled" || turn.error_code === "provider_termination_unconfirmed"
      || turn.error_code === "conversation_termination_unconfirmed");
}

export function blocksNextTurn(turn: TurnExecutionState): boolean {
  return turn.status === "running" || isTerminationUnconfirmed(turn);
}
