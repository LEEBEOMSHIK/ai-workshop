interface SceneEvents {
  once: (event: string, listener: () => void) => unknown;
  off: (event: string, listener: () => void) => unknown;
}
export function onSceneExit(events: SceneEvents, cleanup: () => void) {
  let disposed = false;
  const release = () => {
    if (disposed) return;
    disposed = true;
    events.off("shutdown", release);
    events.off("destroy", release);
    cleanup();
  };
  events.once("shutdown", release);
  events.once("destroy", release);
}
