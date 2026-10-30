import { formatComparisonDuration, formatComparisonMoney, formatComparisonTokens } from "./comparison-format";

describe("stored comparison value formatting", () => {
  it("distinguishes an unmeasured duration from measured zero", () => {
    expect(formatComparisonDuration(null)).toBe("미측정");
    expect(formatComparisonDuration(undefined)).toBe("미측정");
    expect(formatComparisonDuration(0)).toBe("0.000초");
    expect(formatComparisonDuration(0.074523)).toBe("0.075초");
    expect(formatComparisonDuration(133.631997999)).toBe("133.632초");
  });

  it("keeps the exact small dollar amount without rounding it to zero", () => {
    expect(formatComparisonMoney("0.000667")).toBe("USD 0.000667");
    expect(formatComparisonMoney("0.0003255")).toBe("USD 0.0003255");
    expect(formatComparisonMoney("0")).toBe("USD 0");
    expect(formatComparisonMoney(null)).toBe("미확인");
  });

  it("shows unreported tokens independently from zero usage", () => {
    expect(formatComparisonTokens(0)).toBe("0");
    expect(formatComparisonTokens(2630)).toBe("2,630");
    expect(formatComparisonTokens(null)).toBe("미보고");
  });
});
