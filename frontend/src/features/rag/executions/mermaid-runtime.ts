type MermaidRuntime = {
  initialize: (config: Record<string, unknown>) => void;
  render: (id: string, source: string, container?: HTMLElement) => Promise<{ svg: string }>;
};
let loading: Promise<MermaidRuntime> | undefined;

// The official tiny distribution is a classic script, not an ES module. The bundler
// emits this dependency as a local asset; no diagram data is sent to a third party.
export function loadMermaid(): Promise<MermaidRuntime> {
  if (loading) return loading;
  loading = new Promise<MermaidRuntime>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = new URL("@mermaid-js/tiny/dist/mermaid.tiny.js", import.meta.url).href;
    script.async = true;
    const timeout = window.setTimeout(() => failed(), 15000);
    function failed() {
      window.clearTimeout(timeout); script.remove(); reject(new Error("diagram_runtime_unavailable"));
    }
    script.onerror = failed;
    script.onload = () => {
      window.clearTimeout(timeout);
      const runtime = (globalThis as typeof globalThis & { mermaid?: MermaidRuntime }).mermaid;
      if (!runtime?.render || !runtime?.initialize) { failed(); return; }
      try {
        const palette = getComputedStyle(document.documentElement);
        runtime.initialize({ startOnLoad: false, securityLevel: "strict", htmlLabels: false,
          logLevel: "fatal", suppressErrorRendering: true, theme: "base", layout: "dagre",
          fontFamily: "Inter, Pretendard, Noto Sans KR, sans-serif",
          themeVariables: {
            primaryColor: palette.getPropertyValue("--color-surface").trim(),
            primaryTextColor: palette.getPropertyValue("--color-text").trim(),
            primaryBorderColor: palette.getPropertyValue("--color-secondary").trim(),
            lineColor: palette.getPropertyValue("--color-secondary").trim(),
            fontSize: "16px",
          },
          flowchart: { htmlLabels: false, useMaxWidth: false, curve: "linear", nodeSpacing: 36, rankSpacing: 64, padding: 16, wrappingWidth: 220 },
        });
        resolve(runtime);
      } catch { failed(); }
    };
    document.head.append(script);
  }).catch(error => { loading = undefined; throw error; });
  return loading;
}

export async function renderMermaid(id: string, source: string, container: HTMLElement) {
  return (await loadMermaid()).render(id, source, container);
}
