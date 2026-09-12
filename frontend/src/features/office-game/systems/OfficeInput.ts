const movementKeys = new Set(["w", "a", "s", "d", "arrowup", "arrowleft", "arrowdown", "arrowright"]);
export class OfficeInput {
  private keys = new Set<string>();
  constructor(private canvas: HTMLCanvasElement, private interact: () => void) {
    canvas.addEventListener("keydown", this.down);
    window.addEventListener("keyup", this.up);
    canvas.addEventListener("blur", this.clear);
    window.addEventListener("blur", this.clear);
    document.addEventListener("visibilitychange", this.clear);
  }
  private down = (event: KeyboardEvent) => {
    if (document.activeElement !== this.canvas) return;
    const key = event.key.toLowerCase();
    if (movementKeys.has(key) || key === "e") event.preventDefault();
    if (movementKeys.has(key)) this.keys.add(key);
    if (key === "e" && !event.repeat) this.interact();
  };
  private up = (event: KeyboardEvent) => { this.keys.delete(event.key.toLowerCase()); };
  clear = () => { this.keys.clear(); };
  direction() {
    const has = (a: string, b: string) => Number(this.keys.has(a) || this.keys.has(b));
    return { x: has("d", "arrowright") - has("a", "arrowleft"), y: has("s", "arrowdown") - has("w", "arrowup") };
  }
  destroy() {
    this.clear();
    this.canvas.removeEventListener("keydown", this.down);
    window.removeEventListener("keyup", this.up);
    this.canvas.removeEventListener("blur", this.clear);
    window.removeEventListener("blur", this.clear);
    document.removeEventListener("visibilitychange", this.clear);
  }
}
