export interface GameHandle { destroy: () => void }
/** Owns one asynchronous browser runtime; a late import must never mount after cleanup. */
export function mountGame(load: () => Promise<() => GameHandle>, onError: () => void) {
  let disposed = false;
  let game: GameHandle | undefined;
  void load().then((create) => { if (!disposed) game = create(); }).catch(() => { if (!disposed) onError(); });
  return () => {
    if (disposed) return;
    disposed = true;
    game?.destroy();
  };
}
