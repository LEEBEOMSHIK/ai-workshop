import { decodeApiResponse } from "./client";
import { resolvePublicApiTarget } from "../config/public-runtime";

export async function publicApiRequest<T>(path: string): Promise<T> {
  if (!path.startsWith("/api/public/")) {
    throw new Error("public_api_path_required");
  }
  const target = resolvePublicApiTarget(process.env);
  const response = await fetch(`${target}${path}`, {
    cache: "no-store",
    credentials: "omit",
  });
  return decodeApiResponse<T>(response);
}
