export interface RectLike {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

export interface Size {
  width: number;
  height: number;
}

export interface DialogPlacement {
  side: "right" | "left" | "above" | "below";
  left: number;
  top: number;
  tailOffset: number;
}

const VIEWPORT_MARGIN = 20;
const DIALOG_GAP = 24;
const TAIL_MARGIN = 24;

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(Math.max(value, minimum), Math.max(minimum, maximum));
}

export function calculateDialogPlacement(
  anchor: RectLike,
  dialog: Size,
  viewport: Size,
): DialogPlacement {
  const anchorCenterX = anchor.left + anchor.width / 2;
  const anchorCenterY = anchor.top + anchor.height / 2;
  const clampLeft = (left: number) =>
    clamp(left, VIEWPORT_MARGIN, viewport.width - dialog.width - VIEWPORT_MARGIN);
  const clampTop = (top: number) =>
    clamp(top, VIEWPORT_MARGIN, viewport.height - dialog.height - VIEWPORT_MARGIN);

  if (anchor.right + DIALOG_GAP + dialog.width <= viewport.width - VIEWPORT_MARGIN) {
    const top = clampTop(anchorCenterY - dialog.height / 2);
    return {
      side: "right",
      left: anchor.right + DIALOG_GAP,
      top,
      tailOffset: clamp(anchorCenterY - top, TAIL_MARGIN, dialog.height - TAIL_MARGIN),
    };
  }

  if (anchor.left - DIALOG_GAP - dialog.width >= VIEWPORT_MARGIN) {
    const top = clampTop(anchorCenterY - dialog.height / 2);
    return {
      side: "left",
      left: anchor.left - DIALOG_GAP - dialog.width,
      top,
      tailOffset: clamp(anchorCenterY - top, TAIL_MARGIN, dialog.height - TAIL_MARGIN),
    };
  }

  const side = anchor.top - DIALOG_GAP - dialog.height >= VIEWPORT_MARGIN ? "above" : "below";
  const left = clampLeft(anchorCenterX - dialog.width / 2);
  const top = clampTop(
    side === "above" ? anchor.top - DIALOG_GAP - dialog.height : anchor.bottom + DIALOG_GAP,
  );

  return {
    side,
    left,
    top,
    tailOffset: clamp(anchorCenterX - left, TAIL_MARGIN, dialog.width - TAIL_MARGIN),
  };
}
