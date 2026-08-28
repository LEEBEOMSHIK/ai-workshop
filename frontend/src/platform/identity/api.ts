import { ApiError, type ApiErrorBody, type SessionUser } from "./session";

async function readJson<T>(response: Response): Promise<T> {
  if (response.ok) {
    return (await response.json()) as T;
  }
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody;
  throw new ApiError(
    body.error?.message ?? "요청을 완료하지 못했습니다.",
    response.status,
    body.error?.correlation_id,
  );
}

export async function login(email: string, password: string): Promise<SessionUser> {
  const response = await fetch("/api/v1/auth/login", {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  return readJson<SessionUser>(response);
}

export async function getCurrentUser(): Promise<SessionUser> {
  const response = await fetch("/api/v1/auth/me", { credentials: "include" });
  return readJson<SessionUser>(response);
}

export async function logout(): Promise<void> {
  const response = await fetch("/api/v1/auth/logout", {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    await readJson<never>(response);
  }
}
