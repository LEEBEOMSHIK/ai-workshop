import { ApiError } from "../../../shared/api/client";
import { cancelConversationTurn, getConversationStart, type ConversationDetail, type StartRequest } from "./sessions-api";

// A pending first question owns its immutable payload even after its screen leaves.
// GET 404 is only an observation: the original POST may still commit later.
const detachedStarts = new Set<PendingStart>();
// Only these exact start validation failures occur before acceptance writes.
// Generic authority errors (including POST404) can also follow commit.
const unacceptedStartErrors = new Map<string, number>([
  ["draft_upload_busy", 409],
  ["draft_revision_conflict", 409],
  ["draft_unavailable", 410],
  ["attachment_workspace_forbidden", 403],
  ["domain_connection_changed", 409],
  ["domain_inactive", 409],
  ["domain_not_ready", 409],
  ["search_scope_empty", 422],
  ["selected_documents_not_ready", 409],
  ["codex_input_approval_required", 422],
  ["validation_error", 422],
]);

export class PendingStart {
  cancelIntent = false;
  settled = false;
  rejected = false;
  private accepted: ConversationDetail | null = null;
  private uncertain = false;
  private rejectedDraftDisposition: (() => void) | undefined;
  private cancelling = false;
  private cancelled = false;
  private polling = false;
  private timer: ReturnType<typeof setTimeout> | undefined;

  constructor(readonly slug: string, readonly request: StartRequest,
    private receive: ((detail: ConversationDetail) => void) | undefined,
    private failed: ((error: unknown) => void) | undefined) {}

  async accept(detail: ConversationDetail) {
    if (this.rejected || this.cancelled || (this.settled && this.accepted && !this.cancelIntent)) return;
    this.accepted = detail;
    this.rejectedDraftDisposition = undefined;
    if (this.cancelIntent) await this.cancelAccepted();
    else {
      this.settled = !detail.turns.some(turn => turn.status === "running");
      if (this.settled) this.finish();
      this.receive?.(detail);
    }
  }

  reject(error: unknown) {
    if (this.cancelled || this.rejected) return;
    if (!this.accepted && !this.uncertain && error instanceof ApiError && unacceptedStartErrors.get(error.code) === error.status) {
      this.rejected = true;
      this.settled = true; this.finish();
      const dispose = this.rejectedDraftDisposition;
      this.rejectedDraftDisposition = undefined;
      dispose?.();
    } else if (!this.settled) this.uncertain = true;
    this.failed?.(error);
    if (!this.settled) void this.recover();
  }

  // Leaving may precede the original POST's definitive denial. Keep this intent
  // separate from presentation, and never dispose a possibly accepted draft.
  disposeDraftOnRejection(dispose: () => void) {
    if (this.accepted || this.cancelled) return;
    if (this.rejected) dispose();
    else this.rejectedDraftDisposition ??= dispose;
  }

  cancel() {
    if (this.cancelled || (this.settled && !this.accepted)) return;
    this.cancelIntent = true;
    this.settled = false;
    if (this.accepted) void this.cancelAccepted(); else void this.recover();
  }

  // In-app unmount detaches presentation, not the uncertain server operation.
  // This owner remains alive until original rejection or accepted-ID cancellation.
  detach() {
    this.receive = undefined;
    this.failed = undefined;
    if (this.settled) { this.finish(); return; }
    detachedStarts.add(this);
    this.cancel();
  }

  private finish() { clearTimeout(this.timer); detachedStarts.delete(this); }

  async recover() {
    if (this.polling || this.settled) return;
    clearTimeout(this.timer);
    this.polling = true;
    try {
      const detail = await getConversationStart(this.slug, this.request.request_id);
      await this.accept(detail);
    } catch (error) {
      if (error instanceof ApiError && error.status === 410) { this.settled = true; this.finish(); this.failed?.(error); }
      // Authentication/network/404 errors retain both request and cancel intent.
    } finally {
      this.polling = false;
      if (!this.settled) { clearTimeout(this.timer); this.timer = setTimeout(() => void this.recover(), 2000); }
    }
  }

  private async cancelAccepted() {
    if (this.cancelling || this.settled || !this.accepted) return;
    this.cancelling = true;
    try {
      const detail = await cancelConversationTurn(this.slug, this.accepted.id, this.request.request_id);
      this.cancelled = true; this.settled = true; this.finish(); this.receive?.(detail);
    } catch (error) { this.failed?.(error); }
    finally {
      this.cancelling = false;
      if (!this.settled) { clearTimeout(this.timer); this.timer = setTimeout(() => void this.recover(), 2000); }
    }
  }
}
