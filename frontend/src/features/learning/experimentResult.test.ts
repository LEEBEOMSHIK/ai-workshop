import { describe, expect, it } from "vitest";
import { analyzeResult, type Comparison } from "./experimentResult";

function analyze(overrides: Partial<Comparison> = {}) {
  return analyzeResult({
    question: "점검 기한은?", expected: "7일 뒤 [e1]", before: "7일 후", after: "7일 후", notes: "",
    ...overrides,
  });
}

describe("experiment result evidence", () => {
  it("separates unchanged output and missing source markers from unassessed meaning", () => {
    const result = analyze({ notes: "문구는 달라도 정확할 수 있다." });
    expect(result.sameText).toBe(true);
    expect(result.after.missing).toEqual(["[e1]"]);
    expect(result.citationTrend).toBe("unchanged");
    expect(result.semanticTrend).toBe("unevaluated");
    expect(result.after.semantic).toBe("unevaluated");
  });

  it("tracks additions and losses by required id, including replacements", () => {
    const result = analyze({ expected: "참고 [e1] [e10] [e3]", before: "[e1] [e3]", after: "[e10] [e10] [e3] [e7]" });
    expect(result.citationTrend).toBe("mixed");
    expect(result.added).toEqual(["[e10]"]);
    expect(result.lost).toEqual(["[e1]"]);
    expect(result.after.cited).toEqual(["[e10]", "[e3]", "[e7]"]);
  });

  it("recognises grouped source numbers without treating a change of citation formatting as recovery", () => {
    const result = analyze({
      expected: "규정과 달력 [e1, e2]", before: "계산 결과 [e1] [e2]",
      after: "계산 결과 [ e1,\te2, e1 ]",
    });
    expect(result.required).toEqual(["[e1]", "[e2]"]);
    expect(result.after.cited).toEqual(["[e1]", "[e2]"]);
    expect(result.after.missing).toEqual([]);
    expect(result.added).toEqual([]);
    expect(result.lost).toEqual([]);
    expect(result.citationTrend).toBe("unchanged");
    expect(result.after.semantic).toBe("unevaluated");
  });

  it("keeps grouped e10 distinct from e1 and ignores malformed groups instead of guessing their references", () => {
    const result = analyze({
      expected: "[e1] [e2] [e10] [e3]",
      after: "[e10, e2] [e1, 설명] [e1-e2] [e1,,e2] [e1,] [e1 e2] [e1, [e3]]",
    });
    expect(result.after.cited).toEqual(["[e10]", "[e2]"]);
    expect(result.after.missing).toEqual(["[e1]", "[e3]"]);
  });

  it.each([
    ["7일 후", "7일 뒤 [e1]", "오답", "정확", "improved"],
    ["7일 뒤 [e1]", "8일 후", "정확", "오답", "regressed"],
  ])("reads recorded judgements when output changes from %s to %s", (before, after, from, to, trend) => {
    const result = analyze({ before, after, notes: `학습 전 의미 평가: ${from}\n학습 후 의미 평가: ${to}` });
    expect(result.sameText).toBe(false);
    expect(result.semanticTrend).toBe(trend);
    expect(result.citationTrend).toBe(trend);
  });

  it("keeps unrecognised and fenced commentary, extracts conditions and declines conflicting verdicts", () => {
    const code = "~~~\r\n학습 후 의미 평가: 정확\r\n~~~";
    const notes = [code, "학습 전 의미 평가: 오답", "평가 조건: 동일 근거", "학습 전 의미 평가: 정확", "비교 조건  1회 생성", "예전 관찰"].join("\r\n");
    const result = analyze({ notes });
    expect(result.before.semantic).toBe("unevaluated");
    expect(result.after.semantic).toBe("unevaluated");
    expect(result.notes).toBe([code, "학습 전 의미 평가: 오답", "학습 전 의미 평가: 정확", "예전 관찰"].join("\r\n"));
    expect(result.conditions).toEqual(["동일 근거", "1회 생성"]);
  });

  it("can report a single recorded judgement without inventing a prior evaluation or reference baseline", () => {
    const result = analyze({ expected: undefined, after: "[e1]", notes: "학습 후 의미 평가：정확" });
    expect(result.after.semantic).toBe("correct");
    expect(result.semanticTrend).toBe("unevaluated");
    expect(result.citationTrend).toBe("unevaluated");
  });
});
