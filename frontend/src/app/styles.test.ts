import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("global responsive styles", () => {
  it("does not force the body wider than the viewport content area", () => {
    const stylesheet = readFileSync(resolve(process.cwd(), "src/app/styles.css"), "utf8");
    const bodyRule = stylesheet.match(/body\s*\{(?<declarations>[^}]*)\}/)?.groups?.declarations;

    expect(bodyRule).toBeDefined();
    expect(bodyRule).not.toMatch(/min-width\s*:\s*320px/);
  });

  it("reserves the dialog placement margin on short viewports", () => {
    const stylesheet = readFileSync(
      resolve(process.cwd(), "src/features/public-labs/PublicLabScene.module.css"),
      "utf8",
    );

    expect(stylesheet).toContain("max-height: calc(100dvh - 2.5rem);");
  });

  it("keeps exact 64rem and 48rem widths in the wider responsive tier", () => {
    const stylesheet = readFileSync(
      resolve(process.cwd(), "src/features/public-labs/PublicLabScene.module.css"),
      "utf8",
    );

    expect(stylesheet).toContain("@media (width < 64rem)");
    expect(stylesheet).toContain("@media (width < 48rem)");
    expect(stylesheet).not.toContain("@media (max-width: 64rem)");
    expect(stylesheet).not.toContain("@media (max-width: 48rem)");
  });
});
