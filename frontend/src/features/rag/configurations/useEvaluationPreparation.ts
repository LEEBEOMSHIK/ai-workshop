import { useState, type SetStateAction } from "react";
import type { AuthoringSnapshot, GenerativeRule } from "./generative-api";

export type PreparationMode = "saved" | "create";
type Preparation = {
  snapshot: AuthoringSnapshot | null;
  snapshotId: string;
  rules: Record<string, GenerativeRule>;
  histories: Record<string, string>;
  retrievalK: number;
  repetitions: number;
  consented: boolean;
};
const empty = (): Preparation => ({ snapshot: null, snapshotId: "", rules: {}, histories: {}, retrievalK: 10, repetitions: 2, consented: false });

/** Keep each preparation's inputs while only exposing the active mode for submission. */
export function useEvaluationPreparation(mode: PreparationMode) {
  const [preparations, setPreparations] = useState(() => ({ saved: empty(), create: empty() }));
  function setter<K extends keyof Preparation>(key: K) {
    return (value: SetStateAction<Preparation[K]>) => setPreparations(previous => ({
      ...previous,
      [mode]: { ...previous[mode], [key]: typeof value === "function" ? value(previous[mode][key]) : value },
    }));
  }
  return { ...preparations[mode], setSnapshot: setter("snapshot"), setSnapshotId: setter("snapshotId"),
    setRules: setter("rules"), setHistories: setter("histories"), setRetrievalK: setter("retrievalK"),
    setRepetitions: setter("repetitions"), setConsented: setter("consented") };
}
