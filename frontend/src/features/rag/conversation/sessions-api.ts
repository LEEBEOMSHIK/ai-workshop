import { apiRequest } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";

export type ConversationSummary = components["schemas"]["ConversationSummary"];
export type ConversationTurn = components["schemas"]["ConversationTurnResponse"];
export type ConversationDetail = components["schemas"]["ConversationDetail"];
export type TurnRequest = components["schemas"]["ConversationTurnCreate"];
export const conversationPath = (slug: string, id?: string) => `/api/v1/rag/domains/${encodeURIComponent(slug)}/conversations${id ? `/${encodeURIComponent(id)}` : ""}`;
export const listConversations = (slug: string, signal?: AbortSignal) => apiRequest<ConversationSummary[]>(conversationPath(slug), {signal, cache: "no-store"});
export const createConversation = (slug: string) => apiRequest<ConversationDetail>(conversationPath(slug), {method: "POST", json: {}, cache: "no-store"});
export const getConversation = (slug: string, id: string, signal?: AbortSignal) => apiRequest<ConversationDetail>(conversationPath(slug, id), {signal, cache: "no-store"});
export const renameConversation = (slug: string, session: ConversationSummary, title: string) => apiRequest<ConversationDetail>(conversationPath(slug, session.id), {method: "PATCH", json: {title, expected_revision: session.revision}, cache: "no-store"});
export const deleteConversation = (slug: string, session: ConversationSummary) => apiRequest<void>(`${conversationPath(slug, session.id)}?expected_revision=${session.revision}`, {method: "DELETE", cache: "no-store"});
export const sendConversationTurn = (slug: string, id: string, request: TurnRequest, signal?: AbortSignal) => apiRequest<ConversationDetail>(`${conversationPath(slug, id)}/turns`, {method: "POST", json: request, signal, cache: "no-store", ...(request.codex_input_approval ? {headers: {"x-codex-request": "1"}} : {})});
export const cancelConversationTurn = (slug: string, id: string, requestId: string) => apiRequest<ConversationDetail>(`${conversationPath(slug, id)}/turns/${encodeURIComponent(requestId)}/cancel`, {method: "POST", json: {}, cache: "no-store"});

export type Attachment = components["schemas"]["ConversationAttachmentResponse"];
export type AttachmentOptions = components["schemas"]["AttachmentOptionsResponse"];
export const getAttachmentOptions = (slug: string, id: string) => apiRequest<AttachmentOptions>(`${conversationPath(slug, id)}/attachment-options`, {cache: "no-store"});
export const listAttachments = (slug: string, id: string, signal?: AbortSignal) => apiRequest<Attachment[]>(`${conversationPath(slug, id)}/attachments`, {signal, cache: "no-store"});
export function uploadAttachment(slug: string, id: string, workspaceId: string, file: File) {
  const body = new FormData(); body.append("file", file);
  return apiRequest<Attachment>(`${conversationPath(slug, id)}/attachments?workspace_id=${encodeURIComponent(workspaceId)}`, {method: "POST", body, cache: "no-store"});
}
