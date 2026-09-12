import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { serverApiRequest } from "../../../../../shared/api/server-client";
import { incomingCookieHeader, requireOwner } from "../../../../../shared/auth/server-session";
import RagModelsRoute from "./page";

vi.mock("../../../../../shared/api/server-client", () => ({ serverApiRequest: vi.fn() }));
vi.mock("../../../../../shared/auth/server-session", () => ({ incomingCookieHeader: vi.fn(), requireOwner: vi.fn() }));
// Exercise the server handoff without invoking the client-only administration effect.
vi.mock("../../../../../features/rag/models/ModelLabPage", () => ({ ModelLabPage: ({ initialProfiles }: { initialProfiles: { name: string }[] }) => <div>{initialProfiles.map((profile) => <p key={profile.name}>{profile.name}</p>)}</div> }));
beforeEach(() => vi.clearAllMocks());

it("requires owner then hands document-processing profiles to the registry", async () => {
  vi.mocked(incomingCookieHeader).mockResolvedValue("synthetic-session");
  vi.mocked(serverApiRequest).mockImplementation(async (path) => path === "/api/v1/rag/profiles/document_processing" ? [{ name: "synthetic-processing" }] : []);
  render(await RagModelsRoute());
  expect(requireOwner).toHaveBeenCalledWith("/admin/rag/models");
  expect(screen.getByText("synthetic-processing")).toBeVisible();
  expect(vi.mocked(serverApiRequest).mock.calls.map(([path]) => path)).toEqual(["/api/v1/rag/models", "/api/v1/rag/profiles/document_processing", "/api/v1/rag/profiles/indexing", "/api/v1/rag/profiles/retrieval", "/api/v1/rag/profiles/generation"]);
  expect(serverApiRequest).toHaveBeenCalledWith("/api/v1/rag/profiles/document_processing", {}, "synthetic-session");
});
