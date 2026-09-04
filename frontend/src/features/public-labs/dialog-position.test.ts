import { describe, expect, it } from "vitest";

import { calculateDialogPlacement } from "./dialog-position";

describe("calculateDialogPlacement", () => {
  it("prefers the right side when the dialog fits", () => {
    expect(
      calculateDialogPlacement(
        { left: 100, top: 200, right: 260, bottom: 460, width: 160, height: 260 },
        { width: 320, height: 240 },
        { width: 1200, height: 800 },
      ),
    ).toMatchObject({ side: "right", left: 284, top: 210, tailOffset: 120 });
  });

  it("flips to the left when the right side would overflow", () => {
    expect(
      calculateDialogPlacement(
        { left: 980, top: 200, right: 1140, bottom: 460, width: 160, height: 260 },
        { width: 320, height: 240 },
        { width: 1200, height: 800 },
      ),
    ).toMatchObject({ side: "left", left: 636, top: 210, tailOffset: 120 });
  });

  it("places the dialog above when neither horizontal side has enough space", () => {
    expect(
      calculateDialogPlacement(
        { left: 300, top: 500, right: 460, bottom: 700, width: 160, height: 200 },
        { width: 400, height: 240 },
        { width: 800, height: 800 },
      ),
    ).toMatchObject({ side: "above", left: 180, top: 236, tailOffset: 200 });
  });

  it("places the dialog below when horizontal sides and the space above are unavailable", () => {
    expect(
      calculateDialogPlacement(
        { left: 300, top: 40, right: 460, bottom: 140, width: 160, height: 100 },
        { width: 400, height: 240 },
        { width: 800, height: 800 },
      ),
    ).toMatchObject({ side: "below", left: 180, top: 164, tailOffset: 200 });
  });

  it("clamps an above dialog's left edge and tail within the viewport-safe range", () => {
    expect(
      calculateDialogPlacement(
        { left: 0, top: 500, right: 20, bottom: 600, width: 20, height: 100 },
        { width: 440, height: 240 },
        { width: 500, height: 800 },
      ),
    ).toMatchObject({ side: "above", left: 20, top: 236, tailOffset: 24 });
  });

  it("clamps a right dialog's top edge and tail near the top viewport margin", () => {
    expect(
      calculateDialogPlacement(
        { left: 100, top: 0, right: 200, bottom: 40, width: 100, height: 40 },
        { width: 300, height: 240 },
        { width: 1000, height: 700 },
      ),
    ).toMatchObject({ side: "right", left: 224, top: 20, tailOffset: 24 });
  });

  it("clamps a right dialog's tail near the bottom viewport margin", () => {
    expect(
      calculateDialogPlacement(
        { left: 100, top: 780, right: 200, bottom: 800, width: 100, height: 20 },
        { width: 300, height: 240 },
        { width: 1000, height: 800 },
      ),
    ).toMatchObject({ side: "right", left: 224, top: 540, tailOffset: 216 });
  });
});
