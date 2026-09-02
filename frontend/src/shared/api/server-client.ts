import { decodeApiResponse, type ApiRequestOptions } from "./client";
import { resolveApiTarget } from "../config/api-target";

export async function serverApiRequest<T = void>(
  path: string,
  options: ApiRequestOptions = {},
  cookieHeader?: string,
): Promise<T> {
  const { body, json, ...init } = options;
  const headers = new Headers(init.headers);
  let requestBody = body;

  if (json !== undefined) {
    requestBody = JSON.stringify(json);
    headers.set("content-type", "application/json");
  }
  if (cookieHeader) headers.set("cookie", cookieHeader);

  const apiTarget = process.env.AI_WORKSHOP_API_TARGET ?? resolveApiTarget(process.env.API_PORT);
  const response = await fetch(`${apiTarget}${path}`, {
    ...init,
    cache: "no-store",
    headers,
    ...(requestBody !== undefined ? { body: requestBody } : {}),
  });
  return decodeApiResponse<T>(response);
}
