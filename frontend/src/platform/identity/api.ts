import { apiRequest } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";
import type { SessionUser } from "./session";

type LoginRequest = components["schemas"]["LoginRequest"];

export async function login(email: string, password: string): Promise<SessionUser> {
  const request: LoginRequest = { email, password };
  return apiRequest<SessionUser>("/api/v1/auth/login", {
    method: "POST",
    json: request,
  });
}

export async function getCurrentUser(): Promise<SessionUser> {
  return apiRequest<SessionUser>("/api/v1/auth/me");
}

export async function logout(): Promise<void> {
  return apiRequest<void>("/api/v1/auth/logout", {
    method: "POST",
  });
}
