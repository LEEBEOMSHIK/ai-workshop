"""Recording contract with actual held-lock bookkeeping and fake private ports."""

import hashlib
import json
from dataclasses import replace
from uuid import uuid4

import pytest

from ai_workshop.infrastructure.local.cutover_control_windows import WindowsControlLock
from ai_workshop.labs.rag.indexing.access_epoch_submission import (
    ControlProcessIdentity,
    ProtectedControlJournal,
    SubmissionJournalError,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    CutoverActionKind,
    ReservedCutoverAction,
    canonical_json,
)


class Kernel:
    def create(self, name):
        return 100

    def wait(self, handle):
        return 0

    def thread_id(self):
        return 1

    def release(self, handle):
        pass

    def close(self, handle):
        pass


class PrivateMemory:
    def __init__(self):
        self.files, self.plain = {}, {}
        self.writes = 0
        self.lost_ack = False

    def protect(self, content):
        key = uuid4().bytes
        self.plain[key] = content
        return key

    def unprotect(self, content):
        return self.plain[content]

    def read(self, path):
        return self.files.get(path)

    def write(self, path, content):
        self.writes += 1
        self.files[path] = content
        if self.lost_ack:
            raise OSError("private-marker")

    def remove(self, path):
        raise AssertionError("Journal never deletes records")


@pytest.fixture
def journal_case():
    execution, generation = uuid4(), str(uuid4())
    lock = WindowsControlLock(uuid4().hex * 2, "synthetic-journal", native=Kernel())
    owner = lock.acquire(execution, generation)
    storage = PrivateMemory()
    journal = ProtectedControlJournal(
        "C:/synthetic-workshop", storage, storage, lock, owner, lock.scope_sha256
    )
    yield journal, storage, lock, owner
    lock.close(owner)


def reserved(journal, kind=CutoverActionKind.STOP_OLD, sequence=1):
    ticket = journal.prepare_expected(kind, sequence - 1, "a" * 64)
    action = ReservedCutoverAction(
        uuid4(), ticket.execution_id, sequence, kind, ticket.expected, ticket.executor_generation
    )
    return action, ticket


def child():
    return ControlProcessIdentity(101, "133700000000000000", uuid4())


def test_nonce_bound_intent_then_same_child_finished_is_not_daemon_settlement(journal_case):
    journal, storage, _, _ = journal_case
    action, ticket = reserved(journal)
    assert ticket.submission_id.hex not in repr(storage.files)
    intent = journal.begin(action, ticket)
    assert intent.state == "intent" and intent.child is None
    created = journal.process_created(intent, child())
    finished = journal.process_finished(created, created.child, 0)
    assert finished.state == "process_finished" and finished.revision == 3
    assert finished.child == created.child and finished.exit_code == 0
    assert journal.read(action) == finished
    assert storage.writes == 3 and len(storage.files) == 1
    decoded = json.loads(storage.plain[next(iter(storage.files.values()))])
    assert not any(k in decoded for k in ("argv", "stdout", "secret", "daemon_settled"))
    assert "/control/" in next(iter(storage.files)).replace("\\", "/")


def test_ticket_copy_or_reuse_never_writes(journal_case):
    journal, storage, _, _ = journal_case
    action, ticket = reserved(journal)
    with pytest.raises(SubmissionJournalError):
        journal.begin(action, replace(ticket))
    assert storage.writes == 0
    journal.begin(action, ticket)
    with pytest.raises(SubmissionJournalError):
        journal.begin(action, ticket)
    assert storage.writes == 1


def test_missing_file_does_not_make_old_pending_action_fresh(journal_case):
    journal, storage, _, _ = journal_case
    old_action, _ = reserved(journal)
    assert journal.read(old_action) is None
    new_ticket = journal.prepare_expected(CutoverActionKind.STOP_OLD, 1, "a" * 64)
    with pytest.raises(SubmissionJournalError):
        journal.begin(old_action, new_ticket)
    assert storage.writes == 0


def test_lost_write_ack_consumes_ticket_and_readback_preserves_intent(journal_case):
    journal, storage, _, _ = journal_case
    action, ticket = reserved(journal)
    storage.lost_ack = True
    with pytest.raises(SubmissionJournalError) as error:
        journal.begin(action, ticket)
    assert "private-marker" not in str(error.value)
    with pytest.raises(SubmissionJournalError):
        journal.begin(action, ticket)
    assert storage.writes == 1 and journal.read(action).state == "intent"


@pytest.mark.parametrize("field", ["execution_id", "executor_generation", "sequence", "kind"])
def test_changed_reserved_binding_consumes_ticket_without_write(journal_case, field):
    journal, storage, _, _ = journal_case
    action, ticket = reserved(journal)
    values = {
        "execution_id": uuid4(),
        "executor_generation": str(uuid4()),
        "sequence": 2,
        "kind": CutoverActionKind.RETIRE_OLD,
    }
    with pytest.raises(SubmissionJournalError):
        journal.begin(replace(action, **{field: values[field]}), ticket)
    with pytest.raises(SubmissionJournalError):
        journal.begin(action, ticket)
    assert storage.writes == 0


def test_other_lock_scope_cannot_back_a_journal(journal_case):
    _, storage, lock, owner = journal_case
    with pytest.raises(SubmissionJournalError):
        ProtectedControlJournal("C:/synthetic-workshop", storage, storage, lock, owner, "f" * 64)
    assert storage.writes == 0


@pytest.mark.parametrize("change", ["pid", "creation", "job", "copy_record"])
def test_foreign_process_or_reconstructed_record_cannot_append(journal_case, change):
    journal, storage, _, _ = journal_case
    action, ticket = reserved(journal)
    created = journal.process_created(journal.begin(action, ticket), child())
    changes = {
        "pid": {"pid": 102},
        "creation": {"creation_time": "133700000000000001"},
        "job": {"job_id": uuid4()},
        "copy_record": {},
    }
    with pytest.raises(SubmissionJournalError):
        journal.process_finished(
            replace(created) if change == "copy_record" else created,
            replace(created.child, **changes[change]),
            0,
        )
    assert storage.writes == 2


def test_unknown_is_terminal_and_cannot_become_finished(journal_case):
    journal, storage, _, _ = journal_case
    action, ticket = reserved(journal)
    unknown = journal.unknown(journal.begin(action, ticket))
    with pytest.raises(SubmissionJournalError):
        journal.process_created(unknown, child())
    assert journal.read(action) == unknown and storage.writes == 2


def test_fresh_journal_can_read_but_cannot_resume_or_append_old_record(journal_case):
    journal, storage, lock, owner = journal_case
    action, ticket = reserved(journal)
    intent = journal.begin(action, ticket)
    fresh = ProtectedControlJournal(
        "C:/synthetic-workshop", storage, storage, lock, owner, lock.scope_sha256
    )
    readback = fresh.read(action)
    assert readback == intent
    with pytest.raises(SubmissionJournalError):
        fresh.process_created(readback, child())
    assert storage.writes == 1


@pytest.mark.parametrize("corruption", ["extra", "duplicate", "binding", "state", "boolean"])
def test_corrupt_protected_record_never_overwrites_history(journal_case, corruption):
    journal, storage, _, _ = journal_case
    action, ticket = reserved(journal)
    journal.begin(action, ticket)
    opaque = next(iter(storage.files.values()))
    payload = json.loads(storage.plain[opaque])
    if corruption == "extra":
        payload["private-marker"] = "never expose"
    elif corruption == "binding":
        payload["action_id"] = str(uuid4())
    elif corruption == "state":
        payload["state"] = "daemon_settled"
    elif corruption == "boolean":
        payload["revision"] = True
    body = json.dumps(payload)
    if corruption == "duplicate":
        body = '{"schema_version":1,' + body[1:]
    storage.plain[opaque] = body.encode()
    with pytest.raises(SubmissionJournalError) as error:
        journal.read(action)
    assert "private-marker" not in str(error.value) and storage.writes == 1


@pytest.mark.parametrize("revision,has_child", [(1, False), (2, True), (3, False)])
def test_unknown_record_has_only_reachable_state_shape(journal_case, revision, has_child):
    journal, storage, _, _ = journal_case
    action, ticket = reserved(journal)
    journal.begin(action, ticket)
    opaque = next(iter(storage.files.values()))
    payload = json.loads(storage.plain[opaque])
    payload.update(state="unknown", revision=revision)
    if has_child:
        payload.update(child_pid=101, child_creation_time="133700000000000000", job_id=str(uuid4()))
    storage.plain[opaque] = json.dumps(payload).encode()
    with pytest.raises(SubmissionJournalError):
        journal.read(action)
    assert storage.writes == 1


def test_append_lost_ack_is_readable_but_cannot_append_again(journal_case):
    journal, storage, _, _ = journal_case
    action, ticket = reserved(journal)
    intent = journal.begin(action, ticket)
    storage.lost_ack = True
    with pytest.raises(SubmissionJournalError):
        journal.process_created(intent, child())
    with pytest.raises(SubmissionJournalError):
        journal.unknown(intent)
    created = journal.read(action)
    assert created.state == "process_created" and created.revision == 2
    with pytest.raises(SubmissionJournalError):
        journal.process_finished(created, created.child, 0)
    assert storage.writes == 2


def test_interrupted_write_never_reuses_ticket(journal_case):
    journal, storage, _, _ = journal_case
    action, ticket = reserved(journal)
    old_write = storage.write

    def interrupted(path, content):
        old_write(path, content)
        raise KeyboardInterrupt

    storage.write = interrupted
    with pytest.raises(KeyboardInterrupt):
        journal.begin(action, ticket)
    with pytest.raises(SubmissionJournalError):
        journal.begin(action, ticket)
    readback = journal.read(action)
    with pytest.raises(SubmissionJournalError):
        journal.process_created(readback, child())
    assert storage.writes == 1


def test_ownership_loss_during_write_does_not_return_or_authorize_append(journal_case):
    journal, storage, lock, _ = journal_case
    action, ticket = reserved(journal)
    old_write, old_tid = storage.write, lock._native.thread_id

    def lost_owner(path, content):
        old_write(path, content)
        lock._native.thread_id = lambda: 2

    storage.write = lost_owner
    try:
        with pytest.raises(SubmissionJournalError):
            journal.begin(action, ticket)
    finally:
        lock._native.thread_id = old_tid
    readback = journal.read(action)
    with pytest.raises(SubmissionJournalError):
        journal.process_created(readback, child())
    assert storage.writes == 1


def test_protection_and_unprotect_errors_are_body_free(journal_case):
    journal, storage, _, _ = journal_case
    action, ticket = reserved(journal)

    def denied(_content):
        raise OSError("private-marker")

    old_protect = storage.protect
    storage.protect = denied
    with pytest.raises(SubmissionJournalError) as error:
        journal.begin(action, ticket)
    assert "private-marker" not in str(error.value) and storage.writes == 0
    storage.protect = old_protect
    next_action, next_ticket = reserved(journal, sequence=2)
    journal.begin(next_action, next_ticket)
    storage.unprotect = denied
    with pytest.raises(SubmissionJournalError) as error:
        journal.read(next_action)
    assert "private-marker" not in str(error.value) and storage.writes == 1


@pytest.mark.parametrize(
    "name,value",
    [
        ("schema_version", True),
        ("scope_sha256", "f" * 64),
        ("target_sha256", "invalid"),
        ("preceding_sequence", False),
        ("execution_id", str(uuid4())),
        ("kind", "retire_old"),
    ],
)
def test_read_checks_full_expected_payload_not_only_nonce_and_digest(journal_case, name, value):
    journal, storage, _, _ = journal_case
    action, ticket = reserved(journal)
    journal.begin(action, ticket)
    expected = json.loads(action.expected.identity_json)
    expected[name] = value
    text = canonical_json(expected)
    altered = replace(action, expected=replace(action.expected, identity_json=text))
    opaque = next(iter(storage.files.values()))
    payload = json.loads(storage.plain[opaque])
    payload["expected_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    storage.plain[opaque] = canonical_json(payload).encode()
    with pytest.raises(SubmissionJournalError):
        journal.read(altered)
    assert storage.writes == 1


def test_created_unknown_is_reachable_and_terminal(journal_case):
    journal, storage, _, _ = journal_case
    action, ticket = reserved(journal)
    created = journal.process_created(journal.begin(action, ticket), child())
    unknown = journal.unknown(created)
    assert journal.read(action) == unknown and unknown.revision == 3
    with pytest.raises(SubmissionJournalError):
        journal.process_finished(unknown, unknown.child, 0)
    assert storage.writes == 3


def test_string_subclass_generation_is_not_exact_reserved_identity(journal_case):
    journal, storage, _, _ = journal_case
    action, ticket = reserved(journal)

    class Generation(str):
        pass

    with pytest.raises(SubmissionJournalError):
        journal.begin(
            replace(action, executor_generation=Generation(action.executor_generation)), ticket
        )
    assert storage.writes == 0


def test_ownership_loss_during_protect_prevents_file_write(journal_case):
    journal, storage, lock, _ = journal_case
    action, ticket = reserved(journal)
    old_protect, old_tid = storage.protect, lock._native.thread_id

    def lost_owner(content):
        encrypted = old_protect(content)
        lock._native.thread_id = lambda: 2
        return encrypted

    storage.protect = lost_owner
    try:
        with pytest.raises(SubmissionJournalError):
            journal.begin(action, ticket)
    finally:
        lock._native.thread_id = old_tid
    assert storage.writes == 0
    with pytest.raises(SubmissionJournalError):
        journal.begin(action, ticket)
