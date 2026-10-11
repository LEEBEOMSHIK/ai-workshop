"""Transaction/replay fake for application tests; SQL behavior tested separately."""

from copy import deepcopy

from ai_workshop.shared.errors import AppError


def attach_memory_starts(repo):
    repo.starts = {}

    async def lookup(owner, domain, request_id, digest):
        entry = repo.starts.get((owner, domain, request_id))
        if entry is None:
            return None
        stored_digest, id = entry
        if digest is not None and stored_digest != digest:
            raise AppError("conversation_request_conflict", "Conflict", 409)
        item = repo.items[id]
        if item.deleted_at:
            raise AppError("conversation_start_deleted", "Deleted", 410)
        return deepcopy(item)

    async def start(item, request, digest):
        async with repo.lock:
            replay = await lookup(item.owner_id, item.domain_id, request.request_id, digest)
            if replay is not None:
                return replay, False
            repo.items[item.id] = deepcopy(item)
            repo.starts[(item.owner_id, item.domain_id, request.request_id)] = (digest, item.id)
            return deepcopy(item), True

    repo.find_start = lookup
    repo.start = start
