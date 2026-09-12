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

  it("keeps Korean agent names from splitting inside dialog headings", () => {
    const stylesheet = readFileSync(
      resolve(process.cwd(), "src/features/public-labs/PublicLabScene.module.css"),
      "utf8",
    );
    const dialogHeadingRule = stylesheet.match(
      /\.dialog h2\s*\{(?<declarations>[^}]*)\}/,
    )?.groups?.declarations;

    expect(dialogHeadingRule).toContain("word-break: keep-all;");
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

  // Responsive workstation order and the connected floor markings are verified
  // against actual 1440/960/640px browser layout in tests/office/office.e2e.ts.
  // The former nth-child source checks only described the superseded card arrows;
  // jsdom cannot verify media-query layout or whether stations overlap.
});
