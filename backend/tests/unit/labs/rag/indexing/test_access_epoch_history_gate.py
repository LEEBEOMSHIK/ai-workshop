"""History prerequisite issuance cannot launch, settle, release, or mint a proof."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tests.unit.labs.rag.indexing.test_access_epoch_process import process_case  # noqa: F401


@pytest.fixture
def history_case(process_case):  # noqa: F811
    from ai_workshop.labs.rag.indexing.access_epoch_history_gate import OriginalHistoryGate

    c = process_case

    class Reader:
        def __init__(self):
            self.fact = object()
            self.calls = 0
            self.after = None
            self.manifest = {
                "schema_version": 1,
                "scope": "bounded_original_recorded_controls",
                "categories": {"original_docker": 1, "application": 13, "readonly": 4},
                "dispositions": {
                    "original_terminal": 1,
                    "application_terminal": 13,
                    "non_control": 4,
                },
                "unresolved_accepted_controls": 0,
                "coverage": "bounded_recorded_sources",
                "startup_initiator": "unrecorded_observed_start",
            }

        def read_original(self):
            self.calls += 1
            if self.after:
                self.after()
            return self.fact

        def assert_issued(self, facts):
            if facts is not self.fact:
                raise ValueError("private-error-marker")

        def assert_original(self, facts, original, origin):
            self.assert_issued(facts)
            if original != c.epoch.original or origin != identity.original_origin:
                raise ValueError("private-error-marker")

        def private_packet(self, facts):
            self.assert_issued(facts)
            return b"private-source-locator-and-hash-marker"

        def sanitized_manifest(self, facts):
            self.assert_issued(facts)
            return self.manifest

    class Identity:
        def __init__(self):
            self.calls = 0
            self.value = c.epoch.original
            from ai_workshop.labs.rag.indexing.access_epoch_types import OriginalTargetOrigin

            self.original_origin = OriginalTargetOrigin(
                self.value.container_id,
                self.value.daemon_sha256,
                "ai-workshop-elasticsearch",
                datetime(2026, 9, 1, tzinfo=UTC),
            )
            self.after = None

        async def observe_original(self, snapshot):
            self.calls += 1
            assert snapshot == c.epoch.binding.claim.snapshot
            if self.after:
                self.after()
            return self.value

    reader, identity = Reader(), Identity()
    gate = OriginalHistoryGate(c.epoch, c.repo, c.journal, reader, identity)
    return SimpleNamespace(c=c, gate=gate, reader=reader, identity=identity)


@pytest.mark.parametrize(
    "change", ["missing_origin", "other_container", "other_daemon", "binding_denied"]
)
async def test_history_requires_fresh_target_origin_and_reader_correlation(history_case, change):
    h = history_case
    if change == "missing_origin":
        h.identity.original_origin = None
    elif change == "other_container":
        h.identity.original_origin = replace(h.identity.original_origin, container_id="f" * 64)
    elif change == "other_daemon":
        h.identity.original_origin = replace(h.identity.original_origin, daemon_sha256="f" * 64)
    else:

        def denied(*args):
            raise ValueError("private-error-marker")

        h.reader.assert_original = denied
    with pytest.raises(ValueError, match="cutover_historical_controls_denied"):
        await h.gate.verify()
    assert h.c.storage.writes == 0


async def test_issued_history_is_exact_epoch_owned_and_private_provenance_stays_private(
    history_case,
):
    h = history_case
    ticket = await h.gate.verify()
    await h.gate.assert_verified(ticket)
    assert h.reader.calls == 1 and h.identity.calls == 2
    assert h.c.storage.writes == 1
    assert "private-source" not in ticket.manifest_json
    assert h.c.native.calls == []
    assert h.c.repo.state.operation_state == "open" and h.c.repo.state.gate_state == "frozen"


@pytest.mark.parametrize(
    "change",
    [
        "pending",
        "private_extra",
        "wrong_scope",
        "bool_count",
        "bool_version",
        "negative_count",
        "private_category",
        "wrong_identity",
        "wrong_generation",
        "lost_owner_read",
        "lost_owner_identity",
        "lost_write_ack",
        "copied_fact",
    ],
)
async def test_unsafe_or_unissued_history_never_issues_a_capability(history_case, change):
    h = history_case
    if change == "pending":
        h.reader.manifest["unresolved_accepted_controls"] = 1
    elif change == "private_extra":
        h.reader.manifest["private"] = "private-error-marker"
    elif change == "wrong_scope":
        h.reader.manifest["scope"] = "all_machine"
    elif change == "bool_count":
        h.reader.manifest["categories"]["original_docker"] = True
    elif change == "bool_version":
        h.reader.manifest["schema_version"] = True
    elif change == "negative_count":
        h.reader.manifest["dispositions"]["original_terminal"] = -1
    elif change == "private_category":
        h.reader.manifest["categories"]["private/path/marker"] = 1
    elif change == "wrong_identity":
        h.identity.value = replace(h.c.epoch.original, container_id="f" * 64)
    elif change == "wrong_generation":
        h.c.repo.state = replace(h.c.repo.state, executor_generation="private-error-marker")
    elif change == "lost_owner_read":
        h.reader.after = lambda: h.c.lock.close(h.c.owner)
    elif change == "lost_owner_identity":
        h.identity.after = lambda: h.c.lock.close(h.c.owner)
    elif change == "lost_write_ack":
        h.c.storage.lost_ack = True
    else:
        h.reader.read_original = lambda: object()
    with pytest.raises(ValueError, match="cutover_historical_controls_denied") as error:
        await h.gate.verify()
    assert "private-error-marker" not in str(error.value)
    assert h.c.native.calls == []


async def test_copied_ticket_and_owner_loss_do_not_authorize_progress(history_case):
    h = history_case
    ticket = await h.gate.verify()
    with pytest.raises(ValueError, match="cutover_historical_controls_denied"):
        await h.gate.assert_verified(replace(ticket))
    h.c.lock.close(h.c.owner)
    with pytest.raises(ValueError, match="cutover_historical_controls_denied"):
        await h.gate.assert_verified(ticket)


async def test_verification_is_one_shot_even_after_lost_protected_write_ack(history_case):
    h = history_case
    h.c.storage.lost_ack = True
    with pytest.raises(ValueError, match="cutover_historical_controls_denied"):
        await h.gate.verify()
    h.c.storage.lost_ack = False
    with pytest.raises(ValueError, match="cutover_historical_controls_denied"):
        await h.gate.verify()
    assert h.c.storage.writes == 1 and h.c.native.calls == []
