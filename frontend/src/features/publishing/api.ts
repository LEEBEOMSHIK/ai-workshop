import { apiRequest } from "../../shared/api/client";
import { publicApiRequest } from "../../shared/api/public-client";
import { normalizeCatalogQuery, type CatalogQuery } from "./catalog-query";
import type {
  PersonaList,
  PublicationRequest,
  PublicStudyList,
  PublicStudyCatalog,
  StudyAdminList,
  StudyAdminView,
  StudyContent,
  StudyPreview,
  StudySnapshot,
} from "./types";

const adminBase = "/api/v1/admin/publishing";
const mutationHeaders = { "X-Publishing-Request": "1" };

export interface PublishingAdminApi {
  list(offset: number, limit: number): Promise<StudyAdminList>;
  personas(): Promise<PersonaList>;
  detail(slug: string): Promise<StudyAdminView>;
  create(content: StudyContent): Promise<StudyAdminView>;
  update(slug: string, expectedRevision: number, content: StudyContent): Promise<StudyAdminView>;
  preview(slug: string): Promise<StudyPreview>;
  publish(slug: string, request: PublicationRequest): Promise<StudyAdminView>;
  withdraw(slug: string, request: PublicationRequest): Promise<StudyAdminView>;
}

export const publishingAdminApi: PublishingAdminApi = {
  list(offset, limit) {
    return apiRequest(`${adminBase}/studies?offset=${offset}&limit=${limit}`);
  },
  personas() {
    return apiRequest(`${adminBase}/personas`);
  },
  detail(slug) {
    return apiRequest(`${adminBase}/studies/${encodeURIComponent(slug)}`);
  },
  create(content) {
    return apiRequest(`${adminBase}/studies`, {
      method: "POST",
      headers: mutationHeaders,
      json: { content },
    });
  },
  update(slug, expectedRevision, content) {
    return apiRequest(`${adminBase}/studies/${encodeURIComponent(slug)}`, {
      method: "PUT",
      headers: mutationHeaders,
      json: { expected_revision: expectedRevision, content },
    });
  },
  preview(slug) {
    return apiRequest(`${adminBase}/studies/${encodeURIComponent(slug)}/preview`);
  },
  publish(slug, request) {
    return command(slug, "publish", request);
  },
  withdraw(slug, request) {
    return command(slug, "withdraw", request);
  },
};

function command(
  slug: string,
  action: "publish" | "withdraw",
  request: PublicationRequest,
): Promise<StudyAdminView> {
  return apiRequest(`${adminBase}/studies/${encodeURIComponent(slug)}/${action}`, {
    method: "POST",
    headers: mutationHeaders,
    json: request,
  });
}

export function listPublicStudies(topicKey?: string): Promise<PublicStudyList> {
  const query = topicKey ? `?topic_key=${encodeURIComponent(topicKey)}` : "";
  return publicApiRequest(`/api/public/studies${query}`);
}

export function getPublicStudy(slug: string): Promise<StudySnapshot> {
  return publicApiRequest(`/api/public/studies/${encodeURIComponent(slug)}`);
}

export function listPublicStudyCatalog(query: CatalogQuery = { page: 1 }): Promise<PublicStudyCatalog> {
  const valid = normalizeCatalogQuery({ page: String(query.page), topic: query.topic });
  const params = new URLSearchParams({ page: String(valid.page) });
  if (valid.topic) params.set("topic_key", valid.topic);
  return publicApiRequest(`/api/public/study-catalog?${params}`);
}
