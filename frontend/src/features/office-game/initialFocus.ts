import type { GameStore } from "./gameStore";

/** Observe intent before the asynchronous runtime starts; ready gets only one chance. */
export function prepareInitialGameFocus(host: HTMLElement, store: GameStore) {
  const page = host.ownerDocument;
  const window = page.defaultView;
  let finished = false;
  let unsubscribe = () => {};
  const dispose = () => {
    finished = true;
    unsubscribe();
    page.removeEventListener("focusin", onFocus);
    page.removeEventListener("pointerdown", onPointer, true);
    page.removeEventListener("keydown", onKey, true);
    page.removeEventListener("visibilitychange", onVisibility);
    window?.removeEventListener("blur", dispose);
  };
  const isCanvas = (target: EventTarget | null) => target === host.querySelector("canvas");
  const onFocus = (event: FocusEvent) => { if (!isCanvas(event.target)) dispose(); };
  const onPointer = (event: PointerEvent) => { if (!isCanvas(event.target)) dispose(); };
  // Observe navigation intent only; movement keys remain canvas-scoped in OfficeInput.
  const onKey = (event: KeyboardEvent) => { if (event.key === "Tab") dispose(); };
  const onVisibility = () => { if (page.visibilityState !== "visible") dispose(); };
  const check = () => {
    if (finished) return;
    const state = store.getState();
    if (state.dialogueOpen || state.status === "error") { dispose(); return; }
    if (state.status !== "ready") return;
    const canvas = host.querySelector("canvas");
    const active = page.activeElement;
    const canFocus = page.visibilityState === "visible" && page.hasFocus()
      && (active === page.body || active === page.documentElement || active === null);
    dispose();
    if (canFocus) canvas?.focus({ preventScroll: true });
  };
  page.addEventListener("focusin", onFocus);
  page.addEventListener("pointerdown", onPointer, true);
  page.addEventListener("keydown", onKey, true);
  page.addEventListener("visibilitychange", onVisibility);
  window?.addEventListener("blur", dispose);
  unsubscribe = store.subscribe(check);
  if (page.visibilityState !== "visible" || !page.hasFocus()
    || (page.activeElement !== page.body && page.activeElement !== page.documentElement
      && page.activeElement !== null && !isCanvas(page.activeElement))) dispose();
  check();
  return dispose;
}
