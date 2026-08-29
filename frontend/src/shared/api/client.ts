import type { components } from "./schema";

type ErrorEnvelope = components["schemas"]["ErrorEnvelope"];

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const detail = value.error;
  return (
    typeof detail === "object" &&
    detail !== null &&
    "code" in detail &&
    typeof detail.code === "string" &&
    "message" in detail &&
    typeof detail.message === "string" &&
    "correlation_id" in detail &&
    typeof detail.correlation_id === "string"
  );
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string,
    public readonly correlationId?: string,
  ) {
    super(message);
  }
}

export interface ApiRequestOptions extends Omit<RequestInit, "body"> {
  body?: BodyInit | null;
  json?: unknown;
}

export async function apiRequest<T = void>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const { body, json, ...init } = options;
  let requestBody = body;
  let headers = init.headers;

  if (json !== undefined) {
    requestBody = JSON.stringify(json);
    headers = {
      "content-type": "application/json",
      ...Object.fromEntries(new Headers(headers)),
    };
  }

  const response = await fetch(path, {
    ...init,
    credentials: "include",
    ...(headers ? { headers } : {}),
    ...(requestBody !== undefined ? { body: requestBody } : {}),
  });

  if (!response.ok) {
    const candidate: unknown = await response.json().catch(() => undefined);
    const envelope = isErrorEnvelope(candidate) ? candidate : undefined;
    throw new ApiError(
      envelope?.error.message ?? "요청을 완료하지 못했습니다.",
      response.status,
      envelope?.error.code ?? "request_failed",
      envelope?.error.correlation_id,
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
