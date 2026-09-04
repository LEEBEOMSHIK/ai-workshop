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

  it("connects workstations across wide, tablet and mobile pipeline layouts", () => {
    const stylesheet = readFileSync(
      resolve(process.cwd(), "src/features/public-labs/PublicLabScene.module.css"),
      "utf8",
    );

    expect(stylesheet).toContain(".workerStation::after");
    expect(stylesheet).toContain(
      ".workerStation:nth-child(3n):not(:last-child)::after",
    );
    expect(stylesheet).toContain(
      ".workerStation:nth-child(2n):not(:last-child)::after",
    );
    expect(stylesheet).toContain(
      ".workerStation:nth-child(n):not(:last-child)::after",
    );
    expect(stylesheet).not.toContain('content: "→"');
    expect(stylesheet).not.toContain('content: "↓"');
  });
});
