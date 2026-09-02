export function resolveApiTarget(configuredPort: string | undefined): string {
  const port = configuredPort?.trim() || "8000";
  if (!/^\d+$/.test(port)) throw new Error("API_PORT must be a valid TCP port.");
  const numericPort = Number(port);
  if (numericPort < 1 || numericPort > 65535) {
    throw new Error("API_PORT must be a valid TCP port.");
  }
  return `http://127.0.0.1:${numericPort}`;
}
