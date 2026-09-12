export type FrontendRuntimeMode = "combined" | "public";

export interface FrontendRuntimeDecision {
  mode: FrontendRuntimeMode;
  loadRootEnvironment: boolean;
  allowPrivateRoutes: boolean;
}

const frontendInstancePattern = /^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/u;

export function resolveFrontendDistDir(value: string | undefined): string | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (!frontendInstancePattern.test(value)) {
    throw new Error(
      "AI_WORKSHOP_FRONTEND_INSTANCE must start with an ASCII letter or digit and contain only 1-32 letters, digits, underscores, or hyphens",
    );
  }
  return `.next/instances/${value}`;
}

export function decideFrontendRuntime(value: string | undefined): FrontendRuntimeDecision {
  if (value === "public") {
    return { mode: "public", loadRootEnvironment: false, allowPrivateRoutes: false };
  }
  if (value !== undefined && value !== "combined") {
    throw new Error("AI_WORKSHOP_FRONTEND_RUNTIME must be combined or public");
  }
  return { mode: "combined", loadRootEnvironment: true, allowPrivateRoutes: true };
}

export function resolvePublicApiTarget(
  environment: Record<string, string | undefined>,
): string {
  const configured = environment.AI_WORKSHOP_PUBLIC_API_TARGET?.trim();
  if (configured) {
    const url = new URL(configured);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      throw new Error("AI_WORKSHOP_PUBLIC_API_TARGET must use HTTP or HTTPS");
    }
    if (url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
      throw new Error("AI_WORKSHOP_PUBLIC_API_TARGET must be an origin without credentials or a path");
    }
    return url.origin;
  }

  const port = environment.PUBLIC_API_PORT?.trim() || "18001";
  if (!/^\d+$/u.test(port) || Number(port) < 1 || Number(port) > 65535) {
    throw new Error("PUBLIC_API_PORT must be a valid TCP port");
  }
  return `http://127.0.0.1:${port}`;
}
