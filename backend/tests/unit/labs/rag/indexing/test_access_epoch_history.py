"""Synthetic Codex receipts; no original session, account, DB or native control."""

import ast
import hashlib
import importlib
import json
from pathlib import Path

import pytest


def module():
    spec = importlib.util.find_spec("ai_workshop.labs.rag.indexing.access_epoch_history")
    assert spec is not None, "fixed-source history reader is missing"
    return importlib.import_module(spec.name)


@pytest.mark.parametrize(
    "command",
    [
        "@'\nfrom os import system as alias\nalias('synthetic')\n'@ | python.exe -",
    ],
)
def test_metadata_mentions_do_not_hide_actual_control_invocations(command):
    with pytest.raises(module().HistoricalReceiptError, match="history_control"):
        module()._category(command)


def test_actual_public_module_collector_is_not_unknown_python():
    assert (
        module()._category(
            "C:/synthetic/python.exe -m "
            "ai_workshop.labs.rag.indexing.alias_recovery_cli recover --synthetic"
        )
        == "collector"
    )
    assert (
        module()._category(
            '& "C:/synthetic/python.exe" -m '
            "ai_workshop.labs.rag.indexing.alias_recovery_cli recover --synthetic"
        )
        == "collector"
    )


@pytest.mark.parametrize(
    "command",
    [
        "Get-Content synthetic.txt\nStop-Process -Id 999; docker inspect synthetic",
        "docker inspect synthetic; Stop-Process -Id 999",
    ],
)
def test_actual_process_action_is_application_never_readonly(command):
    assert module()._category(command) == "application"


def test_inline_environment_metadata_parse_is_non_control():
    command = (
        "@'\nfrom dotenv import dotenv_values\n"
        "from urllib.parse import urlsplit\n"
        "from pathlib import Path\n"
        "values=dotenv_values(Path('synthetic.env'))\n"
        "print(urlsplit(values.get('SYNTHETIC', '')).scheme)\n'@ | python.exe -"
    )
    assert module()._category(command) == "static_metadata"


def test_readonly_string_inside_python_does_not_hide_actual_process_invocation():
    command = (
        "@'\nimport subprocess\nprint('Get-CimInstance metadata')\n"
        "subprocess.run(['unsafe'])\n'@ | python.exe -"
    )
    with pytest.raises(module().HistoricalReceiptError, match="history_control_grammar_unknown"):
        module()._category(command)


@pytest.mark.parametrize("field", ["worker_pool", "system"])
def test_worker_configuration_metadata_getattr_does_not_allow_control_member(field):
    command = (
        "@'\nfrom ai_workshop.worker import create_celery\n"
        "from dotenv import load_dotenv\nload_dotenv('synthetic.env')\n"
        "app=create_celery()\nprint(getattr(app.conf," + repr(field) + ",None))\n'@ | python.exe -"
    )
    if field == "worker_pool":
        assert module()._category(command) == "static_metadata"
    else:
        with pytest.raises(
            module().HistoricalReceiptError, match="history_control_grammar_unknown"
        ):
            module()._category(command)


@pytest.mark.parametrize("member", ["reserved", "revoke"])
def test_bounded_worker_inspection_getattr_loop_cannot_select_mutation(member):
    command = (
        "@'\nfrom ai_workshop.worker import create_celery\napp=create_celery()\n"
        "i=app.control.inspect()\nfor name in ['active',"
        + repr(member)
        + "]:\n    print(getattr(i,name)())\n'@ | python.exe -"
    )
    if member == "reserved":
        assert module()._category(command) == "static_metadata"
    else:
        with pytest.raises(
            module().HistoricalReceiptError, match="history_control_grammar_unknown"
        ):
            module()._category(command)


def test_inspection_member_names_on_unbound_receiver_are_not_readonly_proof():
    command = (
        "@'\ni=unknown_receiver()\nfor name in ['active','reserved']:\n"
        "    print(getattr(i,name)())\n'@ | python.exe -"
    )
    with pytest.raises(module().HistoricalReceiptError, match="history_control_grammar_unknown"):
        module()._category(command)


@pytest.mark.parametrize("action", ["inspect", "broadcast"])
def test_imported_celery_app_only_supports_inspection_not_worker_control(action):
    prefix = "@'\nfrom ai_workshop.worker import celery_app\n"
    if action == "inspect":
        command = (
            prefix
            + "i=celery_app.control.inspect()\nfor name in ['active','reserved','scheduled']:\n"
            "    fn=getattr(i,name)\n    print(fn())\n'@ | python.exe -"
        )
        assert module()._category(command) == "static_metadata"
    else:
        command = prefix + "celery_app.control.broadcast('shutdown')\n'@ | python.exe -"
        with pytest.raises(
            module().HistoricalReceiptError, match="history_control_grammar_unknown"
        ):
            module()._category(command)


class Protection:
    def protect(self, data):
        return b"protected:" + data

    def unprotect(self, data):
        assert data.startswith(b"protected:")
        return data[len(b"protected:") :]


class Files:
    def __init__(self, data):
        self.data = data

    def read(self, path):
        assert path.endswith("history-recipe.dpapi")
        return self.data


def event(payload, minute=0):
    return {
        "timestamp": f"2026-09-20T00:{minute:02d}:00Z",
        "type": "response_item",
        "payload": payload,
    }


def fixture(tmp_path, monkeypatch, *, command="Get-CimInstance Win32_Process", exit_code=0):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    source = home / ".codex/sessions/2026/09/20/rollout-synthetic.jsonl"
    source.parent.mkdir(parents=True)
    script = "text(await tools.exec_command({cmd:" + json.dumps(command) + "}));"
    rows = [
        event({"type": "custom_tool_call", "name": "exec", "call_id": "call-one", "input": script}),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "call-one",
                "output": [
                    {
                        "type": "text",
                        "text": json.dumps({"exit_code": exit_code, "output": "synthetic"}),
                    }
                ],
            },
            1,
        ),
    ]
    raw = b"".join(json.dumps(v).encode() + b"\n" for v in rows)
    source.write_bytes(raw)
    recipe = {
        "schema_version": 1,
        "scanner_version": 1,
        "sources": [
            {
                "locator": str(source),
                "prefix_bytes": len(raw),
                "prefix_sha256": hashlib.sha256(raw).hexdigest(),
            }
        ],
        "calls": [{"source": 0, "call_id": "call-one", "shell_indices": [0], "supports": []}],
    }
    protected = Protection().protect(json.dumps(recipe).encode())
    reader = module().OriginalHistoricalReceiptReader(tmp_path, Protection(), Files(protected))
    return reader, recipe, source


def test_real_receipt_yields_non_control_facts_without_exposing_private_source(
    tmp_path, monkeypatch
):
    reader, _, source = fixture(tmp_path, monkeypatch)
    facts = reader.read_original()
    manifest = reader.sanitized_manifest(facts)
    assert manifest["categories"] == {"readonly": 1}
    assert manifest["dispositions"] == {"non_control": 1}
    assert manifest["unresolved_accepted_controls"] == 0
    assert str(source) not in json.dumps(manifest)
    assert b"locator" in reader.private_packet(facts)


def test_changed_old_prefix_refuses_but_new_append_is_outside_fixed_cutoff(tmp_path, monkeypatch):
    reader, _, source = fixture(tmp_path, monkeypatch)
    source.write_bytes(source.read_bytes() + b"{}\n")
    assert (
        reader.sanitized_manifest(reader.read_original())["coverage"] == "bounded_recorded_sources"
    )
    raw = source.read_bytes()
    source.write_bytes(b"X" + raw[1:])
    with pytest.raises(module().HistoricalReceiptError, match="history_source_changed"):
        reader.read_original()


def test_missing_terminal_is_not_a_settled_receipt(tmp_path, monkeypatch):
    reader, recipe, source = fixture(tmp_path, monkeypatch)
    raw = source.read_bytes().splitlines(keepends=True)[0]
    source.write_bytes(raw)
    recipe["sources"][0].update(
        prefix_bytes=len(raw), prefix_sha256=hashlib.sha256(raw).hexdigest()
    )
    reader.files.data = Protection().protect(json.dumps(recipe).encode())
    with pytest.raises(module().HistoricalReceiptError, match="history_terminal_missing"):
        reader.read_original()


def test_failed_app_stop_is_classified_failed_never_shutdown_proof(tmp_path, monkeypatch):
    reader, _, _ = fixture(tmp_path, monkeypatch, command="StopBeat", exit_code=1)
    assert reader.sanitized_manifest(reader.read_original())["dispositions"] == {
        "application_failed": 1
    }


def test_docker_success_without_target_observation_refuses(tmp_path, monkeypatch):
    reader, _, _ = fixture(tmp_path, monkeypatch, command="docker start synthetic-elasticsearch")
    with pytest.raises(module().HistoricalReceiptError, match="history_target_evidence_missing"):
        reader.read_original()


def test_exit1_collector_without_contemporaneous_stage_support_refuses(tmp_path, monkeypatch):
    reader, _, _ = fixture(
        tmp_path, monkeypatch, command="python alias_recovery_cli.py recover-local", exit_code=1
    )
    with pytest.raises(module().HistoricalReceiptError, match="history_stage_evidence_missing"):
        reader.read_original()


def test_forged_or_copied_facts_are_not_issued_by_reader(tmp_path, monkeypatch):
    import copy

    reader, _, _ = fixture(tmp_path, monkeypatch)
    facts = reader.read_original()
    reader.assert_issued(facts)
    with pytest.raises(TypeError, match="history_facts_reader_issued_only"):
        copy.copy(facts)
    with pytest.raises(module().HistoricalReceiptError, match="history_facts_not_issued"):
        reader.assert_issued(object.__new__(type(facts)))
    with pytest.raises(module().HistoricalReceiptError, match="history_facts_not_issued"):
        reader.assert_issued(object())


def test_external_recipe_or_source_path_is_not_a_public_read_argument(tmp_path, monkeypatch):
    reader, _, _ = fixture(tmp_path, monkeypatch)
    with pytest.raises(TypeError):
        reader.read_original("/caller/attestation.json")


def rewrite(reader, recipe, source, rows):
    raw = b"".join(json.dumps(v).encode() + b"\n" for v in rows)
    source.write_bytes(raw)
    recipe["sources"][0].update(
        prefix_bytes=len(raw), prefix_sha256=hashlib.sha256(raw).hexdigest()
    )
    reader.files.data = Protection().protect(json.dumps(recipe).encode())


@pytest.mark.parametrize(
    "tamper",
    [
        None,
        "parent",
        "task",
        "cwd",
        "time",
        "header",
        "return",
        "cutoff",
        "purpose",
        "selected",
        "operational",
    ],
)
def test_child_source_requires_actual_parent_spawn_return_and_exact_header(
    tmp_path, monkeypatch, tamper
):
    reader, recipe, source = fixture(tmp_path, monkeypatch)
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows.insert(0, {"type": "session_meta", "payload": {"id": "synthetic-parent"}})
    rows += [
        event(
            {
                "type": "function_call",
                "name": "collaboration.spawn_agent",
                "call_id": "spawn-child",
                "arguments": json.dumps({"task_name": "review"}),
            },
            2,
        ),
        event(
            {
                "type": "function_call_output",
                "call_id": "spawn-child",
                "output": json.dumps({"task_name": "/root/review"}),
            },
            4,
        ),
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "test-child",
                "input": (
                    "text(await tools.exec_command({cmd:"
                    '"python.exe -m pytest tests/synthetic.py"}));'
                ),
            },
            6,
        ),
    ]
    if tamper == "return":
        rows[-2]["payload"]["output"] = json.dumps({"task_name": "/root/other"})
    rewrite(reader, recipe, source, rows)
    meta = {
        "type": "session_meta",
        "payload": {
            "id": "synthetic-child",
            "cwd": str(tmp_path),
            "timestamp": "2026-09-20T00:03:00Z",
            "source": {
                "subagent": {
                    "thread_spawn": {
                        "parent_thread_id": "synthetic-parent",
                        "agent_path": "/root/review",
                    }
                }
            },
        },
    }
    if tamper in {"parent", "task"}:
        key = "parent_thread_id" if tamper == "parent" else "agent_path"
        meta["payload"]["source"]["subagent"]["thread_spawn"][key] = "other"
    if tamper == "cwd":
        meta["payload"]["cwd"] = str(tmp_path / "other")
    if tamper == "time":
        meta["payload"]["timestamp"] = "2026-09-20T00:05:00Z"
    raw = json.dumps(meta).encode() + b"\n"
    header_raw = raw
    if tamper in {"cutoff", "operational"}:
        raw += (
            json.dumps(
                event(
                    {
                        "type": "custom_tool_call",
                        "name": "exec",
                        "call_id": "child-operation",
                        "input": 'await tools.exec_command({cmd:"StopApi"});',
                    },
                    7 if tamper == "cutoff" else 5,
                )
            ).encode()
            + b"\n"
        )
    child = source.with_name("rollout-synthetic-child.jsonl")
    child.write_bytes(raw)
    recipe["sources"].append(
        {
            "locator": str(child),
            "prefix_bytes": len(raw),
            "prefix_sha256": hashlib.sha256(raw).hexdigest(),
            "purpose": "historical_source_writes",
            "parent_spawn": {
                "source": 0,
                "call_id": "spawn-child",
                "first_line_sha256": "0" * 64
                if tamper == "header"
                else hashlib.sha256(header_raw).hexdigest(),
            },
        }
    )
    recipe["calls"].append(
        {"source": 0, "call_id": "test-child", "shell_indices": [0], "supports": []}
    )
    if tamper == "purpose":
        recipe["sources"][-1]["purpose"] = "settled_controls"
    if tamper == "selected":
        recipe["calls"][-1]["source"] = 1
    reader.files.data = Protection().protect(json.dumps(recipe).encode())
    if tamper in {None, "operational"}:
        loaded = reader._sources(reader._recipe())
        assert len(loaded) == 2
        if tamper == "operational":
            assert loaded[-1][-1] == {}
    else:
        reason = {
            "cutoff": "history_child_cutoff_invalid",
            "purpose": "history_receipt_invalid",
            "selected": "history_child_scope_invalid",
        }.get(tamper, "history_child_linkage_invalid")
        with pytest.raises(module().HistoricalReceiptError, match=reason):
            reader._sources(reader._recipe())


def test_unlisted_actual_app_control_cannot_hide_behind_recipe_coverage(tmp_path, monkeypatch):
    reader, recipe, source = fixture(tmp_path, monkeypatch)
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows += [
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "unlisted",
                "input": 'text(await tools.exec_command({cmd:"StopApi"}));',
            },
            2,
        )
    ]
    rewrite(reader, recipe, source, rows)
    with pytest.raises(
        module().HistoricalReceiptError, match="history_inventory_coverage_incomplete"
    ):
        reader.read_original()


def test_source_file_write_mention_is_not_an_actual_shell_call(tmp_path, monkeypatch):
    reader, recipe, source = fixture(tmp_path, monkeypatch)
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    source_body = 'await tools.exec_command({cmd:"docker stop synthetic"})'
    rows += [
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "source-write",
                "input": "await tools.apply_patch(" + json.dumps(source_body) + ");",
            },
            2,
        )
    ]
    rewrite(reader, recipe, source, rows)
    assert reader.sanitized_manifest(reader.read_original())["categories"] == {"readonly": 1}


def test_fork_duplicate_same_call_and_output_deduplicate(tmp_path, monkeypatch):
    reader, recipe, source = fixture(tmp_path, monkeypatch)
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rewrite(reader, recipe, source, rows + rows)
    assert reader.sanitized_manifest(reader.read_original())["categories"] == {"readonly": 1}


def test_batch_selects_failed_stop_not_other_commands_exit0(tmp_path, monkeypatch):
    reader, recipe, source = fixture(tmp_path, monkeypatch)
    script = (
        'text(await tools.exec_command({cmd:"Get-CimInstance Win32_Process"}));'
        'text(await tools.exec_command({cmd:"StopBeat"}));'
    )
    rows = [
        event({"type": "custom_tool_call", "name": "exec", "call_id": "call-one", "input": script}),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "call-one",
                "output": [
                    {"type": "text", "text": json.dumps({"exit_code": 0, "output": "synthetic"})},
                    {"type": "text", "text": json.dumps({"exit_code": 1, "output": "synthetic"})},
                ],
            },
            1,
        ),
    ]
    recipe["calls"][0]["shell_indices"] = [1]
    rewrite(reader, recipe, source, rows)
    assert reader.sanitized_manifest(reader.read_original())["dispositions"] == {
        "application_failed": 1
    }


def scoped_batch_fixture(tmp_path, monkeypatch, *, commands=None, parts=None):
    reader, recipe, source = fixture(tmp_path, monkeypatch)
    commands = commands or ["Get-CimInstance Win32_Process", "python ordinary_metadata.py"]
    parts = parts or [{"exit_code": 0, "output": ""}, {"session_id": 51, "output": ""}]
    script = "".join(
        "text(await tools.exec_command({cmd:" + json.dumps(cmd) + "}));" for cmd in commands
    )
    rows = [
        event({"type": "custom_tool_call", "name": "exec", "call_id": "call-one", "input": script}),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "call-one",
                "output": [{"type": "text", "text": json.dumps(part)} for part in parts],
            },
            1,
        ),
    ]
    return reader, recipe, source, rows


def test_scoped_chain_settles_target_without_manufacturing_other_terminal(tmp_path, monkeypatch):
    reader, recipe, source, rows = scoped_batch_fixture(tmp_path, monkeypatch)
    results = reader._chain("call-one", rows, required_shell_indices=(0,))
    assert results == [{"exit_code": 0, "output": ""}, {"session_id": 51, "output": ""}]
    for required in (None, (1,), (0, 1)):
        with pytest.raises(module().HistoricalReceiptError, match="history_terminal_missing"):
            reader._chain("call-one", rows, required_shell_indices=required)
    rewrite(reader, recipe, source, rows)
    facts = reader.read_original()
    assert reader.sanitized_manifest(facts)["categories"] == {"readonly": 1}
    assert len(json.loads(reader.private_packet(facts))["derived_receipts"]) == 1


@pytest.mark.parametrize("selected", [(1,), (0, 2), (2, 0)])
def test_scoped_chain_preserves_full_source_ordinal_order(tmp_path, monkeypatch, selected):
    parts = [
        {"exit_code": i + 1, "output": ""}
        if i in selected
        else {"session_id": 51 + i, "output": ""}
        for i in range(3)
    ]
    reader, _, _, rows = scoped_batch_fixture(
        tmp_path, monkeypatch, commands=["Get-CimInstance Win32_Process"] * 3, parts=parts
    )
    assert reader._chain("call-one", rows, required_shell_indices=selected) == parts


@pytest.mark.parametrize(
    "required", [(), [], [0], {0}, "0", 0, (True,), (-1,), (2,), (0, 0), (0.0,), ("0",), (None,)]
)
def test_scoped_chain_rejects_invalid_required_indices(tmp_path, monkeypatch, required):
    reader, _, _, rows = scoped_batch_fixture(tmp_path, monkeypatch)
    with pytest.raises(module().HistoricalReceiptError, match="history_batch_ambiguous"):
        reader._chain("call-one", rows, required_shell_indices=required)


def test_scoped_chain_rejects_int_subclass_and_generator(tmp_path, monkeypatch):
    class SubInt(int):
        pass

    reader, _, _, rows = scoped_batch_fixture(tmp_path, monkeypatch)
    for required in ((SubInt(0),), (v for v in [0])):
        with pytest.raises(module().HistoricalReceiptError, match="history_batch_ambiguous"):
            reader._chain("call-one", rows, required_shell_indices=required)


@pytest.mark.parametrize("indices", [[], [True], [-1], [2], [0, 0], [0.0], ["0"], (0,), "0"])
def test_read_original_validates_selection_before_chain(tmp_path, monkeypatch, indices):
    reader, recipe, source, rows = scoped_batch_fixture(tmp_path, monkeypatch)
    recipe["calls"][0]["shell_indices"] = indices
    # JSON serializes tuples as lists, so directly use a parsed-recipe seam for this shape.
    rewrite(reader, recipe, source, rows)
    if type(indices) is tuple:
        monkeypatch.setattr(reader, "_recipe", lambda: recipe)
    called = []

    def forbidden(*args, **kwargs):
        called.append(True)
        raise AssertionError("chain must not run")

    monkeypatch.setattr(reader, "_chain", forbidden)
    with pytest.raises(module().HistoricalReceiptError):
        reader.read_original()
    assert called == []


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "nontext",
        "unknown_text",
        "rejected",
        "nested",
        "reordered",
        "conflicting_call",
        "conflicting_output",
    ],
)
def test_scoped_chain_requires_complete_unambiguous_batch(tmp_path, monkeypatch, mutation):
    reader, _, _, rows = scoped_batch_fixture(tmp_path, monkeypatch)
    output = rows[1]["payload"]["output"]
    if mutation == "missing":
        output.pop()
    elif mutation == "extra":
        output.append(output[0])
    elif mutation == "nontext":
        output.append({"type": "image", "data": "synthetic"})
    elif mutation == "unknown_text":
        output.insert(0, {"type": "text", "text": "not a result"})
    elif mutation == "rejected":
        output[1]["text"] = '{"status":"rejected","reason":"synthetic"}'
    elif mutation == "nested":
        output[1]["text"] = '{"value":{"session_id":51,"output":""}}'
    elif mutation == "reordered":
        output.reverse()
    elif mutation == "conflicting_call":
        clone = json.loads(json.dumps(rows[0]))
        clone["payload"]["input"] = 'text(await tools.exec_command({cmd:"other"}));'
        rows.append(clone)
    elif mutation == "conflicting_output":
        clone = json.loads(json.dumps(rows[1]))
        clone["payload"]["output"][1]["text"] = '{"exit_code":0,"output":""}'
        rows.append(clone)
    with pytest.raises(module().HistoricalReceiptError):
        reader._chain("call-one", rows, required_shell_indices=(0,))


@pytest.mark.parametrize("code", [True, 0.0, "0"])
def test_scoped_target_terminal_type_is_exact(tmp_path, monkeypatch, code):
    reader, _, _, rows = scoped_batch_fixture(
        tmp_path,
        monkeypatch,
        parts=[{"exit_code": code, "output": ""}, {"session_id": 51, "output": ""}],
    )
    with pytest.raises(module().HistoricalReceiptError):
        reader._chain("call-one", rows, required_shell_indices=(0,))


@pytest.mark.parametrize(
    "command,reason",
    [
        ("StopBeat", "history_inventory_coverage_incomplete"),
        ("python alias_recovery_cli.py opaque", "history_inventory_control_grammar_unknown"),
    ],
)
def test_scoped_unrequired_control_is_still_an_omission(tmp_path, monkeypatch, command, reason):
    reader, recipe, source, rows = scoped_batch_fixture(
        tmp_path, monkeypatch, commands=["Get-CimInstance Win32_Process", command]
    )
    rewrite(reader, recipe, source, rows)
    with pytest.raises(module().HistoricalReceiptError, match=reason):
        reader.read_original()


@pytest.mark.parametrize("group", range(1, 16))
def test_scoped_selection_does_not_admit_finite15_result_grammar(tmp_path, monkeypatch, group):
    reader, _, _, rows = scoped_batch_fixture(tmp_path, monkeypatch)
    rows[0]["payload"]["input"] = batch_settled_script(group)
    with pytest.raises(module().HistoricalReceiptError):
        reader._chain("call-one", rows, required_shell_indices=(0,))


@pytest.mark.parametrize(
    "mutation",
    [
        "unclosed",
        "wrong_cell",
        "wrong_result_cell",
        "duplicate_conflict",
        "failed",
        "unknown_header",
    ],
)
def test_scoped_selection_does_not_bypass_outer_cell_completion(tmp_path, monkeypatch, mutation):
    reader, _, _, rows = scoped_batch_fixture(tmp_path, monkeypatch)
    second = rows[1]["payload"]["output"].pop()
    rows[1]["payload"]["output"].insert(
        0, {"type": "text", "text": "Script running with cell ID synthetic-cell"}
    )
    wait = event(
        {
            "type": "custom_tool_call",
            "name": "wait",
            "call_id": "cell-wait",
            "input": '{"cell_id":"synthetic-cell"}',
        },
        2,
    )
    output = event(
        {
            "type": "custom_tool_call_output",
            "call_id": "cell-wait",
            "output": [{"type": "text", "text": "Script completed"}, second],
        },
        3,
    )
    if mutation == "unclosed":
        output["payload"]["output"][0]["text"] = "Script running with cell ID synthetic-cell"
    elif mutation == "wrong_cell":
        wait["payload"]["input"] = '{"cell_id":"other-cell"}'
    elif mutation == "wrong_result_cell":
        output["payload"]["output"][0]["text"] = "Script running with cell ID other-cell"
    elif mutation == "failed":
        output["payload"]["output"][0]["text"] = "Script failed\nWall time 1 seconds\nOutput:\n"
    elif mutation == "unknown_header":
        output["payload"]["output"][0]["text"] = "Script completed forged"
    rows.extend([wait, output])
    if mutation == "duplicate_conflict":
        clone = json.loads(json.dumps(output))
        clone["payload"]["output"][1]["text"] = '{"exit_code":0,"output":""}'
        rows.append(clone)
    with pytest.raises(module().HistoricalReceiptError):
        reader._chain("call-one", rows, required_shell_indices=(0,))


def test_scoped_selection_preserves_complete_cell_packet_order(tmp_path, monkeypatch):
    reader, _, _, rows = scoped_batch_fixture(tmp_path, monkeypatch)
    parts = rows[1]["payload"]["output"]
    rows[1]["payload"]["output"] = (
        "Script running with cell ID synthetic-cell\nWall time 0.1 seconds\nOutput:\n"
    )
    for i, (state, emitted) in enumerate(
        [
            ("Script running with cell ID synthetic-cell", parts[:1]),
            ("Script completed", parts[1:]),
        ]
    ):
        call_id = f"wait-{i}"
        rows.extend(
            [
                event(
                    {
                        "type": "custom_tool_call",
                        "name": "wait",
                        "call_id": call_id,
                        "input": '{"cell_id":"synthetic-cell"}',
                    },
                    2 + i * 2,
                ),
                event(
                    {
                        "type": "custom_tool_call_output",
                        "call_id": call_id,
                        "output": [{"type": "text", "text": state}, *emitted],
                    },
                    3 + i * 2,
                ),
            ]
        )
    assert reader._chain("call-one", rows, required_shell_indices=(0,)) == [
        {"exit_code": 0, "output": ""},
        {"session_id": 51, "output": ""},
    ]


@pytest.mark.parametrize(
    "mutation",
    ["wrong_session", "unrelated_poll", "duplicate_conflict", "bool_exit", "missing", "valid"],
)
def test_scoped_required_yielded_part_still_needs_its_terminal(tmp_path, monkeypatch, mutation):
    reader, _, _, rows = scoped_batch_fixture(
        tmp_path,
        monkeypatch,
        parts=[{"session_id": 42, "output": ""}, {"session_id": 51, "output": ""}],
    )
    poll = event(
        {
            "type": "custom_tool_call",
            "name": "exec",
            "call_id": "poll",
            "input": "text(await tools.write_stdin({session_id:42}));",
        },
        2,
    )
    response = {"exit_code": 1, "output": ""}
    if mutation == "wrong_session":
        response = {"session_id": 99, "output": ""}
    elif mutation == "unrelated_poll":
        poll["payload"]["input"] = "text(await tools.write_stdin({session_id:99}));"
    elif mutation == "bool_exit":
        response["exit_code"] = True
    output = event(
        {
            "type": "custom_tool_call_output",
            "call_id": "poll",
            "output": [{"type": "text", "text": json.dumps(response)}],
        },
        3,
    )
    rows.append(poll)
    if mutation != "missing":
        rows.append(output)
    if mutation == "duplicate_conflict":
        clone = json.loads(json.dumps(output))
        clone["payload"]["output"][0]["text"] = '{"exit_code":0,"output":""}'
        rows.append(clone)
    if mutation == "valid":
        assert reader._chain("call-one", rows, required_shell_indices=(0,)) == [
            {"exit_code": 1, "output": ""},
            {"session_id": 51, "output": ""},
        ]
    else:
        with pytest.raises(module().HistoricalReceiptError):
            reader._chain("call-one", rows, required_shell_indices=(0,))


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_id", True),
        ("session_id", 0),
        ("session_id", 2**31),
        ("exit_code", False),
        ("error", "denied"),
        ("wall_time_seconds", True),
        ("wall_time_seconds", float("nan")),
        ("wall_time_seconds", -1),
        ("original_token_count", False),
        ("chunk_id", "has space"),
        ("output", None),
    ],
)
def test_scoped_unrequired_slot_still_requires_valid_physical_envelope(
    tmp_path, monkeypatch, field, value
):
    reader, _, _, rows = scoped_batch_fixture(tmp_path, monkeypatch)
    part = {"session_id": 51, "output": ""}
    part[field] = value
    rows[1]["payload"]["output"][1]["text"] = json.dumps(part)
    with pytest.raises(module().HistoricalReceiptError):
        reader._chain("call-one", rows, required_shell_indices=(0,))


@pytest.mark.parametrize(
    "mutation",
    [
        "conditional",
        "callback",
        "stdout",
        "computed",
        "extra_text",
        "duplicate_key",
        "dynamic_option",
    ],
)
def test_scoped_selection_requires_full_sequential_source_emission(tmp_path, monkeypatch, mutation):
    reader, _, _, rows = scoped_batch_fixture(tmp_path, monkeypatch)
    script = rows[0]["payload"]["input"]
    if mutation == "conditional":
        script = "if(flag){" + script + "}"
    elif mutation == "callback":
        script = "unknown(()=>{" + script + "});"
    elif mutation == "stdout":
        script = script.replace("text(await", "text((await").replace("}));", "})).output);")
    elif mutation == "computed":
        script = script.replace("tools.exec_command", "tools['exec_command']")
    elif mutation == "extra_text":
        script = "text('extra');" + script
    elif mutation == "duplicate_key":
        script = script.replace("{cmd:", "{cmd:'synthetic',cmd:")
    elif mutation == "dynamic_option":
        script = script.replace("{cmd:", "{workdir:unknown,cmd:")
    rows[0]["payload"]["input"] = script
    with pytest.raises(module().HistoricalReceiptError):
        reader._chain("call-one", rows, required_shell_indices=(0,))


def test_scoped_existing_structured_tail_keeps_poll_slot_validation(tmp_path, monkeypatch):
    reader, _, source = fixture(tmp_path, monkeypatch)
    rows = [json.loads(row) for row in source.read_bytes().splitlines()]
    rows[0]["payload"]["input"] = structured_two_poll_script()
    rows[1]["payload"]["output"] = structured_two_poll_output()
    assert reader._chain("call-one", rows, required_shell_indices=(0,)) == [
        {"exit_code": 0, "output": ""}
    ]
    rows[1]["payload"]["output"][1]["text"] = '{"session_id":99}'
    with pytest.raises(module().HistoricalReceiptError):
        reader._chain("call-one", rows, required_shell_indices=(0,))


def test_yielded_session_requires_exact_poll_terminal(tmp_path, monkeypatch):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[1]["payload"]["output"][0]["text"] = json.dumps(
        {"session_id": 42, "exit_code": None, "output": ""}
    )
    rows += [
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "poll-one",
                "input": "text(await tools.write_stdin({session_id:42}));",
            },
            2,
        ),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "poll-one",
                "output": [{"type": "text", "text": json.dumps({"exit_code": 0, "output": ""})}],
            },
            3,
        ),
    ]
    rewrite(reader, recipe, source, rows)
    assert reader.sanitized_manifest(reader.read_original())["dispositions"] == {
        "application_terminal": 1
    }


@pytest.mark.parametrize("related", [False, True])
def test_literal_poll_loop_preserves_expanded_terminal_slots(tmp_path, monkeypatch, related):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[1]["payload"]["output"][0]["text"] = json.dumps({"session_id": 42, "output": ""})
    sessions = "[41,42,43]" if related else "[51,52,53]"
    script = (
        "for (const id of " + sessions + ") "
        "text(await tools.write_stdin({session_id:id,chars:'',"
        "yield_time_ms:1000,max_output_tokens:20}));"
    )
    rows += [
        event({"type": "custom_tool_call", "name": "exec", "call_id": "loop", "input": script}, 2),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "loop",
                "output": [
                    {"type": "text", "text": json.dumps({"exit_code": code, "output": ""})}
                    for code in (0, 1, 0)
                ],
            },
            3,
        ),
    ]
    if not related:
        rows += [
            event(
                {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "later",
                    "input": "text(await tools.write_stdin({session_id:42,chars:''}));",
                },
                4,
            ),
            event(
                {
                    "type": "custom_tool_call_output",
                    "call_id": "later",
                    "output": [
                        {"type": "text", "text": json.dumps({"exit_code": 0, "output": ""})}
                    ],
                },
                5,
            ),
        ]
    rewrite(reader, recipe, source, rows)
    assert reader.sanitized_manifest(reader.read_original())["dispositions"] == {
        "application_failed" if related else "application_terminal": 1
    }


@pytest.mark.parametrize(
    "script",
    [
        "for(const id of [41,42,43]) text(await tools.write_stdin({session_id:other,chars:''}));",
        "for(const id of [41,42,42]) text(await tools.write_stdin({session_id:id,chars:''}));",
        "for(const id of sessions) text(await tools.write_stdin({session_id:id,chars:''}));",
        "for(const id of [41,42,43]) text(await tools.write_stdin({session_id:id,chars:'input'}));",
        "for(const id of [41,42,43]) if(true) "
        "text(await tools.write_stdin({session_id:id,chars:''}));",
        "for(const id of [41,42,43]) {let id=42;"
        "text(await tools.write_stdin({session_id:id,chars:''}));}",
        "for(const id of [41,42,43]) {id=42;"
        "text(await tools.write_stdin({session_id:id,chars:''}));}",
        "const id=42; text(await tools.write_stdin({session_id:id,chars:''}));",
        "for(const id of [4 1,42,43]) text(await tools.write_stdin({session_id:id,chars:''}));",
        "for(const id of [0,42,43]) text(await tools.write_stdin({session_id:id,chars:''}));",
        "for(const id of [41,42,2147483648]) "
        "text(await tools.write_stdin({session_id:id,chars:''}));",
        "for(const id of [41,42,43]) "
        "text(await tools.write_stdin({session_id:id,chars:'',extra:1}));",
        "for(const id of [41,42,43]) text(await tools.write_stdin({session_id:id,session_id:id}));",
        "for(const id of [41,42,43]) "
        "text(await tools.write_stdin({session_id:id,chars:''})); id++;",
        "tools.write_stdin(unknown);",
        "for(const id of [41,42,43]) "
        "text(await tools.write_stdin({session_id:id,chars:'',max_tokens:20}));",
    ],
)
def test_unclosed_poll_binding_remains_refused(script):
    with pytest.raises(module().HistoricalReceiptError, match="history_result_linkage_invalid"):
        module()._poll_sessions(script)


def test_expanded_poll_loop_result_count_mismatch_refuses(tmp_path, monkeypatch):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[1]["payload"]["output"][0]["text"] = json.dumps({"session_id": 42, "output": ""})
    rows += [
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "loop",
                "input": "for(const id of [41,42,43]) "
                "text(await tools.write_stdin({session_id:id,chars:''}));",
            },
            2,
        ),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "loop",
                "output": [{"type": "text", "text": json.dumps({"exit_code": 0, "output": ""})}],
            },
            3,
        ),
    ]
    rewrite(reader, recipe, source, rows)
    with pytest.raises(module().HistoricalReceiptError, match="history_result_linkage_invalid"):
        reader.read_original()


@pytest.mark.parametrize("kind,name", [("message", "exec"), ("custom_tool_call", "other")])
def test_non_exec_record_does_not_inject_poll_tokens(tmp_path, monkeypatch, kind, name):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[1]["payload"]["output"][0]["text"] = json.dumps({"session_id": 42, "output": ""})
    rows += [
        event({"type": kind, "name": name, "input": "tools.write_stdin({session_id:unknown})"}, 2),
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "poll",
                "input": "text(await tools.write_stdin({session_id:42}));",
            },
            3,
        ),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "poll",
                "output": [{"type": "text", "text": json.dumps({"exit_code": 0, "output": ""})}],
            },
            4,
        ),
    ]
    rewrite(reader, recipe, source, rows)
    assert reader.sanitized_manifest(reader.read_original())["dispositions"] == {
        "application_terminal": 1
    }


@pytest.mark.parametrize("ending", ["\n", "\r", "\u2028", "\u2029"])
@pytest.mark.parametrize("decoder", ["_poll_sessions", "_result_slots", "_shells"])
def test_js_line_comment_cannot_hide_trailing_execution(ending, decoder):
    script = (
        "for(const id of [41,42,43]) text(await tools.write_stdin({session_id:id,chars:''}));"
        " // bounded comment" + ending + "await tools.exec_command({cmd:'StopApi'});"
    )
    decode = getattr(module(), decoder)
    if decoder == "_shells":
        assert decode(script) == ["StopApi"]
    else:
        with pytest.raises(module().HistoricalReceiptError, match="history_result_linkage_invalid"):
            decode(script)


def mixed_poll_script(sessions="[41,42,43]", tail=None):
    return (
        "for(const id of " + sessions + ") "
        "text(await tools.write_stdin({session_id:id,chars:''}));"
        + (tail or "text((await tools.exec_command({cmd:'StopApi',max_output_tokens:20})).output);")
    )


def mixed_poll_output(tail="ordinary stdout"):
    return [
        {"type": "text", "text": "Script completed"},
        *[
            {"type": "text", "text": json.dumps({"exit_code": code, "output": ""})}
            for code in (0, 1, 0)
        ],
        {"type": "text", "text": tail},
    ]


@pytest.mark.parametrize("related", [False, True])
def test_mixed_poll_physical_slots_preserve_exact_session_terminal(tmp_path, monkeypatch, related):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[1]["payload"]["output"][0]["text"] = json.dumps({"session_id": 42, "output": ""})
    script = mixed_poll_script("[41,42,43]" if related else "[51,52,53]")
    rows += [
        event({"type": "custom_tool_call", "name": "exec", "call_id": "mixed", "input": script}, 2),
        event(
            {"type": "custom_tool_call_output", "call_id": "mixed", "output": mixed_poll_output()},
            3,
        ),
    ]
    if not related:
        rows += [
            event(
                {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "later",
                    "input": "text(await tools.write_stdin({session_id:42}));",
                },
                4,
            ),
            event(
                {
                    "type": "custom_tool_call_output",
                    "call_id": "later",
                    "output": [
                        {"type": "text", "text": json.dumps({"exit_code": 0, "output": ""})}
                    ],
                },
                5,
            ),
        ]
    rewrite(reader, recipe, source, rows)
    assert reader._chain("call-one", rows)[0]["exit_code"] == (1 if related else 0)
    with pytest.raises(
        module().HistoricalReceiptError, match="history_inventory_coverage_incomplete"
    ):
        reader.read_original()


@pytest.mark.parametrize("stdout", ["ordinary stdout", '{"exit_code":0}', '{"session_id":42}'])
def test_stdout_only_emission_never_becomes_terminal_proof(stdout):
    script = mixed_poll_script()
    assert module()._poll_results(script, mixed_poll_output(stdout)) == [
        {"exit_code": 0, "output": ""},
        {"exit_code": 1, "output": ""},
        {"exit_code": 0, "output": ""},
        None,
    ]
    assert module()._shells(script) == ["StopApi"]
    assert module()._result_slots(script) == [
        "write_stdin",
        "write_stdin",
        "write_stdin",
        "exec_command",
    ]


@pytest.mark.parametrize("stdout", ["ordinary stdout", '{"exit_code":0}', '{"session_id":42}'])
def test_selected_stdout_only_tail_refuses_missing_terminal(tmp_path, monkeypatch, stdout):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[0]["payload"]["input"] = mixed_poll_script()
    rows[1]["payload"]["output"] = mixed_poll_output(stdout)
    rewrite(reader, recipe, source, rows)
    with pytest.raises(module().HistoricalReceiptError, match="history_terminal_missing"):
        reader.read_original()


@pytest.mark.parametrize(
    "mutation", ["missing_tail", "extra_text", "swapped_raw", "poll_array", "wrong_session"]
)
def test_mixed_poll_physical_shape_cannot_compact_unknown_text(mutation):
    output = mixed_poll_output()
    if mutation == "missing_tail":
        output.pop()
    elif mutation == "extra_text":
        output.insert(2, {"type": "text", "text": "unrecognized"})
    elif mutation == "swapped_raw":
        output[1], output[4] = output[4], output[1]
    elif mutation == "poll_array":
        output[2]["text"] = '[{"exit_code":0}]'
    else:
        output[2]["text"] = '{"session_id":99}'
    with pytest.raises(module().HistoricalReceiptError, match="history_result_linkage_invalid"):
        module()._poll_results(mixed_poll_script(), output)


@pytest.mark.parametrize(
    "tail",
    [
        "text((await tools.exec_command({cmd:unknown,max_output_tokens:20})).output);",
        "text((await tools.exec_command({cmd:'StopApi',max_output_tokens:unknown})).output);",
        "text((await tools.exec_command({cmd:'StopApi',max_output_tokens:20})).exit_code);",
        "text((await tools.exec_command({cmd:'StopApi',max_output_tokens:20,"
        "workdir:'elsewhere'})).output);",
        "text((await tools.exec_command({cmd:'StopApi',max_output_tokens:20})).output); "
        "text('extra');",
    ],
)
def test_mixed_poll_tail_requires_exact_literal_member_projection(tail):
    with pytest.raises(module().HistoricalReceiptError, match="history_result_linkage_invalid"):
        module()._poll_sessions(mixed_poll_script(tail=tail))


@pytest.mark.parametrize(
    "invalid",
    [
        {"type": "image", "data": "synthetic"},
        {"type": "text", "text": 123},
        {"type": "unrecognized_text", "text": "synthetic"},
    ],
)
def test_mixed_physical_decoder_cannot_drop_invalid_original_element(invalid):
    output = mixed_poll_output()
    output.insert(2, invalid)
    with pytest.raises(module().HistoricalReceiptError, match="history_result_linkage_invalid"):
        module()._poll_results(mixed_poll_script(), output)


def structured_two_poll_script(sessions="[41,42]", tail=None):
    return (
        "for(const id of " + sessions + ") "
        "text(await tools.write_stdin({session_id:id,chars:''}));"
        + (tail or "text(await tools.exec_command({cmd:'StopApi',max_output_tokens:20}));")
    )


def structured_two_poll_output(tail=None):
    return [
        {"type": "text", "text": "Script completed"},
        {"type": "text", "text": '{"session_id":41}'},
        {"type": "text", "text": '{"session_id":42}'},
        {
            "type": "text",
            "text": json.dumps(tail if tail is not None else {"exit_code": 0, "output": ""}),
        },
    ]


@pytest.mark.parametrize("code", [0, 1])
async def test_selected_structured_tail_uses_exec_slot_not_poll_terminal(
    tmp_path, monkeypatch, code
):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[0]["payload"]["input"] = structured_two_poll_script()
    rows[1]["payload"]["output"] = structured_two_poll_output({"exit_code": code, "output": ""})
    rewrite(reader, recipe, source, rows)
    assert reader.sanitized_manifest(reader.read_original())["dispositions"] == {
        "application_terminal" if code == 0 else "application_failed": 1,
    }


def test_selected_structured_tail_follows_only_its_own_yielded_session(tmp_path, monkeypatch):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[0]["payload"]["input"] = structured_two_poll_script()
    rows[1]["payload"]["output"] = structured_two_poll_output({"session_id": 93})
    rows += [
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "tailpoll",
                "input": "text(await tools.write_stdin({session_id:93}));",
            },
            2,
        ),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "tailpoll",
                "output": [{"type": "text", "text": '{"exit_code":1,"output":""}'}],
            },
            3,
        ),
    ]
    rewrite(reader, recipe, source, rows)
    assert reader.sanitized_manifest(reader.read_original())["dispositions"] == {
        "application_failed": 1
    }


@pytest.mark.parametrize("related", [False, True])
def test_two_poll_source_never_matches_exec_tail_as_poll(tmp_path, monkeypatch, related):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[1]["payload"]["output"][0]["text"] = '{"session_id":93}'
    script = structured_two_poll_script("[41,93]" if related else "[41,42]")
    output = structured_two_poll_output({"session_id": 94})
    output[1]["text"] = '{"exit_code":0}'
    output[2]["text"] = '{"exit_code":1}'
    rows += [
        event({"type": "custom_tool_call", "name": "exec", "call_id": "two", "input": script}, 2),
        event({"type": "custom_tool_call_output", "call_id": "two", "output": output}, 3),
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "later",
                "input": "text(await tools.write_stdin({session_id:93}));",
            },
            4,
        ),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "later",
                "output": [{"type": "text", "text": '{"exit_code":0}'}],
            },
            5,
        ),
    ]
    rewrite(reader, recipe, source, rows)
    assert reader._chain("call-one", rows)[0]["exit_code"] == (1 if related else 0)
    assert module()._poll_sessions(script) == ([41, 93] if related else [41, 42])
    assert module()._result_slots(script) == ["write_stdin", "write_stdin", "exec_command"]


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_kind",
        "image",
        "nonstr",
        "extra",
        "missing",
        "swap",
        "duplicate_session",
        "tail_collision",
        "unknown_tail",
        "bool_code",
    ],
)
def test_two_poll_all_structured_path_still_requires_exact_physical_elements(mutation):
    output = structured_two_poll_output()
    if mutation == "unknown_kind":
        output.insert(2, {"type": "unknown", "text": "synthetic"})
    elif mutation == "image":
        output.insert(2, {"type": "image", "data": "synthetic"})
    elif mutation == "nonstr":
        output.insert(2, {"type": "text", "text": 1})
    elif mutation == "extra":
        output.insert(2, {"type": "text", "text": "synthetic"})
    elif mutation == "missing":
        output.pop()
    elif mutation == "swap":
        output[1], output[2] = output[2], output[1]
    elif mutation == "duplicate_session":
        output[2]["text"] = '{"session_id":41}'
    elif mutation == "tail_collision":
        output[3]["text"] = '{"session_id":42}'
    elif mutation == "unknown_tail":
        output[3]["text"] = '{"output":"unknown"}'
    else:
        output[3]["text"] = '{"exit_code":true}'
    with pytest.raises(module().HistoricalReceiptError, match="history_result_linkage_invalid"):
        module()._poll_results(structured_two_poll_script(), output)


@pytest.mark.parametrize(
    "script",
    [
        structured_two_poll_script("[41,42,43]"),
        structured_two_poll_script("[41]"),
        structured_two_poll_script("[41,41]"),
        structured_two_poll_script(
            tail="text(await tools.exec_command({cmd:unknown,max_output_tokens:20}));"
        ),
        structured_two_poll_script(
            tail="text(await tools.exec_command({cmd:'StopApi',max_output_tokens:unknown}));"
        ),
        structured_two_poll_script(
            tail="text(await tools.exec_command({cmd:'StopApi',max_output_tokens:20,tty:true}));"
        ),
        structured_two_poll_script(
            tail="text((await tools.exec_command({cmd:'StopApi',max_output_tokens:20})).output);"
        ),
        structured_two_poll_script() + "text('extra');",
    ],
)
def test_two_poll_tail_does_not_widen_count_fields_or_projection(script):
    with pytest.raises(module().HistoricalReceiptError, match="history_result_linkage_invalid"):
        module()._poll_sessions(script)


def test_duplicate_recipe_keys_refuse_without_private_error(tmp_path, monkeypatch):
    reader, _, _ = fixture(tmp_path, monkeypatch)
    reader.files.data = Protection().protect(b'{"schema_version":1,"schema_version":1}')
    with pytest.raises(module().HistoricalReceiptError, match="history_receipt_invalid"):
        reader.read_original()


def test_actual_output_text_and_outer_cell_wait_preserve_batch_order(tmp_path, monkeypatch):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    script = (
        'text(await tools.exec_command({cmd:"Get-CimInstance Win32_Process"}));'
        'text(await tools.exec_command({cmd:"StopApi"}));'
    )
    rows = [
        event({"type": "custom_tool_call", "name": "exec", "call_id": "call-one", "input": script}),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "call-one",
                "output": [
                    {"type": "output_text", "text": "Script running with cell ID 42"},
                    {"type": "output_text", "text": json.dumps({"exit_code": 0, "output": ""})},
                ],
            },
            1,
        ),
        event(
            {
                "type": "custom_tool_call",
                "name": "wait",
                "call_id": "wait-one",
                "input": '{"cell_id":"42"}',
            },
            2,
        ),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "wait-one",
                "output": [
                    {"type": "output_text", "text": "Script completed"},
                    {"type": "output_text", "text": json.dumps({"exit_code": 1, "output": ""})},
                ],
            },
            3,
        ),
    ]
    recipe["calls"][0]["shell_indices"] = [1]
    rewrite(reader, recipe, source, rows)
    assert reader.sanitized_manifest(reader.read_original())["dispositions"] == {
        "application_failed": 1
    }


def add_support(reader, recipe, source, *, patch_wrapped=False, wrong_target=False):
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    patch = (
        "*** Begin Patch\n*** Update File: docs/worklogs/2026-09-30-rag-alias-recovery.md\n"
        "@@\n+cluster_node_changed ephemeral 동일 거부 미실행 stop revision\n*** End Patch"
    )
    script = "await tools.apply_patch(" + json.dumps(patch) + ");"
    if patch_wrapped:
        script = "text(" + json.dumps(script) + ");"
    rows += [
        event({"type": "custom_tool_call", "name": "exec", "call_id": "stage", "input": script}, 2),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "stage",
                "output": [
                    {"type": "input_text", "text": "Script completed\nWall time: 0.01 seconds"},
                    {"type": "input_text", "text": "{}"},
                ],
            },
            3,
        ),
    ]
    target = "other-elasticsearch" if wrong_target else reader.root.name + "-elasticsearch-1"
    shell = (
        '& "C:/synthetic/docker.exe" --context synthetic inspect --format '
        "'{{.Id}} {{.State.Running}} {{.State.StartedAt}} {{.State.FinishedAt}}' " + target
    )
    rows += [
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "inspect",
                "input": "text(await tools.exec_command({cmd:" + json.dumps(shell) + "}));",
            },
            4,
        ),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "inspect",
                "output": [
                    {
                        "type": "input_text",
                        "text": json.dumps(
                            {
                                "exit_code": 0,
                                "output": "a" * 64
                                + " true 2026-09-20T00:00:00.000Z 0001-01-01T00:00:00Z\n",
                            }
                        ),
                    }
                ],
            },
            5,
        ),
    ]
    supports = []
    for line, kind in ((3, "contemporaneous_stage"), (5, "target_observation")):
        sha = hashlib.sha256(
            json.dumps(rows[line - 1], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        supports.append({"source": 0, "line": line, "payload_sha256": sha, "kind": kind})
    recipe["calls"][0]["supports"] = supports
    rewrite(reader, recipe, source, rows)


def test_recorded_awaited_worklog_refusal_and_same_target_inspect_are_derived(
    tmp_path, monkeypatch
):
    reader, recipe, source = fixture(
        tmp_path, monkeypatch, command="python recover-local", exit_code=1
    )
    add_support(reader, recipe, source)
    manifest = reader.sanitized_manifest(reader.read_original())
    assert manifest["dispositions"] == {"collector_refused": 1}


@pytest.mark.parametrize("mutation", ["quoted_patch", "wrong_target"])
def test_generic_patch_mentions_or_other_target_cannot_authorize(tmp_path, monkeypatch, mutation):
    reader, recipe, source = fixture(
        tmp_path, monkeypatch, command="python recover-local", exit_code=1
    )
    add_support(
        reader,
        recipe,
        source,
        patch_wrapped=mutation == "quoted_patch",
        wrong_target=mutation == "wrong_target",
    )
    with pytest.raises(module().HistoricalReceiptError):
        reader.read_original()


def test_unreviewed_python_helper_is_unknown_not_silently_non_control(tmp_path, monkeypatch):
    reader, _, _ = fixture(tmp_path, monkeypatch, command="python undisclosed_helper.py")
    with pytest.raises(module().HistoricalReceiptError, match="history_helper_source_missing"):
        reader.read_original()


def test_later_reused_cell_number_does_not_extend_finished_original_chain(tmp_path, monkeypatch):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[1]["payload"]["output"] = [
        {"type": "input_text", "text": "Script running with cell ID 42"}
    ]
    for suffix, minute in (("original", 2), ("later", 4)):
        rows += [
            event(
                {
                    "type": "custom_tool_call",
                    "name": "wait",
                    "call_id": suffix,
                    "input": '{"cell_id":"42"}',
                },
                minute,
            ),
            event(
                {
                    "type": "custom_tool_call_output",
                    "call_id": suffix,
                    "output": [
                        {"type": "input_text", "text": "Script completed"},
                        {"type": "input_text", "text": json.dumps({"exit_code": 0, "output": ""})},
                    ],
                },
                minute + 1,
            ),
        ]
    rewrite(reader, recipe, source, rows)
    assert reader.sanitized_manifest(reader.read_original())["dispositions"] == {
        "application_terminal": 1
    }


def test_batched_poll_uses_exact_session_result_not_other_exit_zero(tmp_path, monkeypatch):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[1]["payload"]["output"] = [
        {"type": "input_text", "text": json.dumps({"session_id": 41, "output": ""})}
    ]
    rows += [
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "poll",
                "input": "text(await tools.write_stdin({session_id:41,chars:''}));"
                "text(await tools.write_stdin({session_id:42,chars:''}));",
            },
            2,
        ),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "poll",
                "output": [
                    {"type": "input_text", "text": json.dumps({"exit_code": 1, "output": ""})},
                    {"type": "input_text", "text": json.dumps({"exit_code": 0, "output": ""})},
                ],
            },
            3,
        ),
    ]
    rewrite(reader, recipe, source, rows)
    assert reader.sanitized_manifest(reader.read_original())["dispositions"] == {
        "application_failed": 1
    }


def test_poll_and_unrelated_shell_batch_preserve_actual_result_slot(tmp_path, monkeypatch):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[1]["payload"]["output"] = [
        {"type": "input_text", "text": json.dumps({"session_id": 41, "output": ""})}
    ]
    rows += [
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "poll",
                "input": "text(await tools.exec_command({cmd:'Get-CimInstance Win32_Process'}));"
                "text(await tools.write_stdin({session_id:41,chars:''}));",
            },
            2,
        ),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "poll",
                "output": [
                    {"type": "input_text", "text": json.dumps({"exit_code": 0, "output": ""})},
                    {"type": "input_text", "text": json.dumps({"exit_code": 1, "output": ""})},
                ],
            },
            3,
        ),
    ]
    rewrite(reader, recipe, source, rows)
    assert reader.sanitized_manifest(reader.read_original())["dispositions"] == {
        "application_failed": 1
    }


@pytest.mark.parametrize(
    "mutation", [None, "container", "daemon", "name", "created_later", "naive"]
)
def test_current_origin_binds_literal_start_targets_and_created_time(
    tmp_path, monkeypatch, mutation
):
    from dataclasses import replace
    from datetime import UTC, datetime

    from ai_workshop.labs.rag.indexing.access_epoch_types import (
        OriginalDeploymentIdentity,
        OriginalTargetOrigin,
    )

    reader, recipe, source = fixture(
        tmp_path, monkeypatch, command="python recover-local", exit_code=1
    )
    add_support(reader, recipe, source)
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    targets = [
        reader.root.name + suffix for suffix in ("-elasticsearch-1", "-postgres-1", "-redis-1")
    ]
    start = (
        "text(await tools.exec_command({cmd:"
        + json.dumps("docker start " + " ".join(targets))
        + "}));"
    )
    rows = [
        event({"type": "custom_tool_call", "name": "exec", "call_id": "start", "input": start}),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "start",
                "output": [
                    {
                        "type": "input_text",
                        "text": json.dumps({"exit_code": 0, "output": "\n".join(targets)}),
                    }
                ],
            },
            1,
        ),
    ] + rows
    for support in recipe["calls"][0]["supports"]:
        support["line"] += 2
    recipe["calls"].insert(
        0, {"source": 0, "call_id": "start", "shell_indices": [0], "supports": []}
    )
    rewrite(reader, recipe, source, rows)
    facts = reader.read_original()
    original = OriginalDeploymentIdentity(
        "b" * 64,
        "a" * 64,
        "cluster",
        "node",
        "ephemeral",
        *(["c" * 64] * 5),
        datetime(2026, 9, 20, tzinfo=UTC),
    )
    origin = OriginalTargetOrigin("a" * 64, "b" * 64, targets[0], datetime(2026, 9, 1, tzinfo=UTC))
    changes = {
        "container": {"container_id": "d" * 64},
        "daemon": {"daemon_sha256": "d" * 64},
        "name": {"name": "other-elasticsearch"},
        "created_later": {"created_at": datetime(2026, 9, 21, tzinfo=UTC)},
        "naive": {"created_at": datetime(2026, 9, 1)},
    }
    if mutation is None:
        reader.assert_original(facts, original, origin)
    else:
        with pytest.raises(
            module().HistoricalReceiptError, match="history_original_binding_invalid"
        ):
            reader.assert_original(facts, original, replace(origin, **changes[mutation]))


@pytest.mark.parametrize("bound", [False, True])
def test_unselected_helper_is_unjudged_unless_bound_to_original_control(
    tmp_path, monkeypatch, bound
):
    reader, recipe, source = fixture(tmp_path, monkeypatch)
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    command = "python alias_recovery_cli.py opaque" if bound else "python ordinary_metadata.py"
    rows.append(
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "unselected",
                "input": "text(await tools.exec_command({cmd:" + json.dumps(command) + "}));",
            },
            2,
        )
    )
    rewrite(reader, recipe, source, rows)
    if bound:
        with pytest.raises(
            module().HistoricalReceiptError, match="history_inventory_control_grammar_unknown"
        ):
            reader.read_original()
    else:
        facts = reader.read_original()
        assert reader.sanitized_manifest(facts)["categories"] == {"readonly": 1}
        assert json.loads(reader.private_packet(facts))["unselected_helpers_outside_judgment"] == 1


@pytest.mark.parametrize("mixed_metadata", [False, True])
@pytest.mark.parametrize("duplicate_fork", [False, True])
def test_helper_classification_uses_completed_prior_source_write_not_current_file(
    tmp_path, monkeypatch, mixed_metadata, duplicate_fork
):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="python recorded_helper.py")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    patch = "*** Begin Patch\n*** Add File: recorded_helper.py\n+print('synthetic')\n*** End Patch"
    rows = [
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "write",
                "input": "await tools.apply_patch(" + json.dumps(patch) + ");",
            }
        ),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "write",
                "output": [
                    {"type": "input_text", "text": "Script completed"},
                    {"type": "input_text", "text": "{}"},
                ],
            },
            1,
        ),
    ] + rows
    (tmp_path / "recorded_helper.py").write_text("import subprocess\nsubprocess.run(['unsafe'])")
    if mixed_metadata:
        rows[0]["payload"]["input"] += (
            "text(await tools.exec_command({cmd:'Get-Content synthetic.txt'}));"
        )
        rows[1]["payload"]["output"].append(
            {"type": "input_text", "text": json.dumps({"output": "synthetic metadata"})}
        )
    if duplicate_fork:
        copies = json.loads(json.dumps(rows[:2]))
        copies[0]["timestamp"] = "2026-09-20T00:00:01Z"
        copies[1]["timestamp"] = "2026-09-20T00:01:01Z"
        rows = rows[:2] + copies + rows[2:]
    rewrite(reader, recipe, source, rows)
    assert reader.sanitized_manifest(reader.read_original())["categories"] == {"static_metadata": 1}


def test_historical_patch_reconstruction_preserves_jump_and_sequential_seek(tmp_path, monkeypatch):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="python recorded_helper.py")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    add = (
        "*** Begin Patch\n*** Add File: recorded_helper.py\n+def first():\n"
        "+    print('synthetic')\n+def second():\n+    print('synthetic')\n*** End Patch"
    )
    update = (
        "*** Begin Patch\n*** Update File: recorded_helper.py\n@@ def second():\n"
        "-    print('synthetic')\n+    print('changed')\n*** End Patch"
    )
    writes = []
    for number, patch in enumerate((add, update)):
        writes += [
            event(
                {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": f"write-{number}",
                    "input": "await tools.apply_patch(" + json.dumps(patch) + ");",
                }
            ),
            event(
                {
                    "type": "custom_tool_call_output",
                    "call_id": f"write-{number}",
                    "output": [
                        {"type": "text", "text": "Script completed"},
                        {"type": "text", "text": "{}"},
                    ],
                }
            ),
        ]
    rewrite(reader, recipe, source, writes + rows)
    actual = reader._recorded_python_category(
        "python recorded_helper.py", writes + rows, "call-one", source_only=True
    )
    assert actual == "def first():\n    print('synthetic')\ndef second():\n    print('changed')"


def test_unverified_historical_seek_cannot_choose_one_of_duplicate_exact_spans(
    tmp_path, monkeypatch
):
    reader, _, _ = fixture(tmp_path, monkeypatch)
    add = (
        "*** Begin Patch\n*** Add File: repeated.py\n+print('synthetic')\n"
        "+print('synthetic')\n*** End Patch"
    )
    update = (
        "*** Begin Patch\n*** Update File: repeated.py\n@@\n"
        "-print('synthetic')\n+print('changed')\n*** End Patch"
    )
    rows = []
    for number, patch in enumerate((add, update)):
        rows += [
            event(
                {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": f"write-{number}",
                    "input": "await tools.apply_patch(" + json.dumps(patch) + ");",
                }
            ),
            event(
                {
                    "type": "custom_tool_call_output",
                    "call_id": f"write-{number}",
                    "output": [
                        {"type": "text", "text": "Script completed"},
                        {"type": "text", "text": "{}"},
                    ],
                }
            ),
        ]
    rows.append(event({"type": "custom_tool_call", "call_id": "caller"}))
    with pytest.raises(module().HistoricalReceiptError, match="history_helper_source_ambiguous"):
        reader._recorded_python_category("python repeated.py", rows, "caller", source_only=True)


def test_copied_recipe_or_files_changed_during_derivation_cannot_issue_facts(tmp_path, monkeypatch):
    reader, recipe, source = fixture(tmp_path, monkeypatch)
    original = reader._sources
    reads = 0

    def changing(value):
        nonlocal reads
        result = original(value)
        reads += 1
        if reads == 1:
            raw = source.read_bytes()
            source.write_bytes(raw.replace(b"synthetic", b"tampered!", 1))
        return result

    monkeypatch.setattr(reader, "_sources", changing)
    with pytest.raises(module().HistoricalReceiptError, match="history_source_changed"):
        reader.read_original()


@pytest.mark.parametrize("mode", ["inspect", "migrate", "tests"])
def test_literal_helper_dispatch_stops_at_selected_inspect_exit(mode):
    source = """import argparse
import subprocess
parser = argparse.ArgumentParser()
parser.add_argument("phase", choices=["inspect", "migrate", "tests"])
args = parser.parse_args()
if args.phase == "inspect":
    raise SystemExit(0)
if args.phase == "migrate":
    subprocess.run(["unsafe"])
else:
    import pytest
    pytest.main([])
"""
    tree = module()._literal_helper_dispatch(source, [mode])
    command = "@'\n" + ast.unparse(tree) + "\n'@ | python.exe -"
    if mode == "inspect":
        assert module()._category(command) == "static_metadata"
    else:
        with pytest.raises(module().HistoricalReceiptError):
            module()._category(command)


@pytest.mark.parametrize("sql", ["SELECT count(*) FROM synthetic", "DELETE FROM synthetic"])
def test_readonly_sql_requires_bound_connection_and_literal_safe_sql(sql):
    source = f"""from sqlalchemy import create_engine, text
engine = create_engine("synthetic")
with engine.connect() as connection:
    connection.execute(text({sql!r}))
"""
    if sql.startswith("SELECT"):
        assert module()._category("@'\n" + source + "\n'@ | python.exe -") == "static_metadata"
    else:
        with pytest.raises(module().HistoricalReceiptError):
            module()._category("@'\n" + source + "\n'@ | python.exe -")


@pytest.mark.parametrize("sql", ["SELECT pg_backend_pid()", "SELECT pg_terminate_backend(1)"])
def test_recorded_sql_metadata_function_is_distinct_from_process_control(sql):
    command = (
        "@'\nfrom sqlalchemy import create_engine, text\nengine=create_engine('synthetic')\n"
        "with engine.connect() as connection:\n    connection.execute(text(" + repr(sql) + "))"
        "\n'@ | python.exe -"
    )
    if "pg_backend_pid" in sql:
        assert module()._category(command) == "static_metadata"
    else:
        with pytest.raises(module().HistoricalReceiptError):
            module()._category(command)


def test_inspect_dispatch_cannot_ignore_rebound_namespace():
    source = """import argparse
parser=argparse.ArgumentParser()
parser.add_argument("phase",choices=["inspect","migrate","tests"])
args=parser.parse_args()
args=other_namespace()
if args.phase == "inspect":
    raise SystemExit(0)
import subprocess
subprocess.run(["unsafe"])
"""
    with pytest.raises(module().HistoricalReceiptError):
        module()._literal_helper_dispatch(source, ["inspect"])


@pytest.mark.parametrize("dynamic", [False, True])
def test_sql_interpolation_is_limited_to_literal_tuple_inventory(dynamic):
    value = "unknown_inventory()" if dynamic else "{'synthetic':('synthetic_table','id')}"
    command = (
        "@'\nfrom sqlalchemy import create_engine,text\nengine=create_engine('synthetic')\n"
        "columns=" + value + "\nwith engine.connect() as connection:\n"
        "    for label,(table,fields) in columns.items():\n"
        "        connection.execute(text(f'SELECT {fields} FROM {table} ORDER BY id'))"
        "\n'@ | python.exe -"
    )
    if dynamic:
        with pytest.raises(module().HistoricalReceiptError):
            module()._category(command)
    else:
        assert module()._category(command) == "static_metadata"


@pytest.mark.parametrize("bound", [False, True])
def test_async_shared_session_builder_requires_same_bound_engine(bound):
    receiver = "create_session_factory(engine)()" if bound else "unknown_factory()"
    command = (
        "@'\nfrom sqlalchemy import text\n"
        "from ai_workshop.shared.db import create_engine,create_session_factory\n"
        "engine=create_engine(settings)\nasync def check():\n    async with "
        + receiver
        + " as session:\n        await session.scalar(text('SELECT count(*) FROM synthetic'))"
        "\n'@ | python.exe -"
    )
    if bound:
        assert module()._category(command) == "static_metadata"
    else:
        with pytest.raises(module().HistoricalReceiptError):
            module()._category(command)


@pytest.mark.parametrize("invoked", [False, True])
def test_dataclass_metadata_alias_does_not_authorize_callable_field(invoked):
    tail = (
        "    fn=getattr(attempt.binding,key)\n    fn()"
        if invoked
        else "    print(getattr(attempt.binding,key))"
    )
    command = (
        "@'\nbinding=attempt.binding\nfor key in binding.__dataclass_fields__:\n"
        + tail
        + "\n'@ | python.exe -"
    )
    if invoked:
        with pytest.raises(module().HistoricalReceiptError):
            module()._category(command)
    else:
        assert module()._category(command) == "static_metadata"


@pytest.mark.parametrize(
    "sql",
    [
        "SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ ONLY;",
        "SHOW transaction_read_only",
        "SET TRANSACTION READ WRITE",
    ],
)
def test_only_readonly_transaction_modes_and_metadata_show_are_admitted(sql):
    command = (
        "@'\nfrom sqlalchemy import create_engine,text\nengine=create_engine('synthetic')\n"
        "with engine.connect() as connection:\n    connection.execute(text(" + repr(sql) + "))"
        "\n'@ | python.exe -"
    )
    if "READ WRITE" in sql:
        with pytest.raises(module().HistoricalReceiptError):
            module()._category(command)
    else:
        assert module()._category(command) == "static_metadata"


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess as sp\nsp.getoutput('docker stop synthetic')",
        "import os\nos.popen('docker stop synthetic')",
        "import os\nos.spawnv(0,'synthetic',[])",
    ],
)
def test_process_alias_or_alternate_launcher_cannot_hide_as_metadata(source):
    with pytest.raises(module().HistoricalReceiptError):
        module()._category("@'\n" + source + "\n'@ | python.exe -")


def test_quoted_sql_process_function_is_not_hidden_by_identifier_stripping():
    command = (
        "@'\nfrom sqlalchemy import create_engine,text\nengine=create_engine('synthetic')\n"
        "with engine.connect() as connection:\n"
        "    connection.execute(text('SELECT 1, \"pg_terminate_backend\"(1)'))"
        "\n'@ | python.exe -"
    )
    with pytest.raises(module().HistoricalReceiptError):
        module()._category(command)


def unrelated_settled_poll(sessions="[51,52,53]"):
    return (
        "const values=await Promise.allSettled("
        + sessions
        + ".map(session_id=>tools.write_stdin({session_id,chars:'',"
        "yield_time_ms:1000,max_output_tokens:20})));values.forEach(text);"
    )


@pytest.mark.parametrize("related", [False, True])
def test_closed_settled_poll_only_excludes_an_unaddressed_session(tmp_path, monkeypatch, related):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[1]["payload"]["output"][0]["text"] = json.dumps({"session_id": 42, "output": ""})
    rows += [
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "unrelated",
                "input": unrelated_settled_poll("[41,42,43]" if related else "[51,52,53]"),
            },
            2,
        ),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "unrelated",
                "output": [{"type": "image", "data": "synthetic"}],
            },
            3,
        ),
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "later",
                "input": "text(await tools.write_stdin({session_id:42}));",
            },
            4,
        ),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "later",
                "output": [{"type": "text", "text": json.dumps({"exit_code": 0, "output": ""})}],
            },
            5,
        ),
    ]
    rewrite(reader, recipe, source, rows)
    if related:
        with pytest.raises(module().HistoricalReceiptError, match="history_result_linkage_invalid"):
            reader.read_original()
    else:
        assert reader.sanitized_manifest(reader.read_original())["dispositions"] == {
            "application_terminal": 1
        }


@pytest.mark.parametrize(
    "change", ["extra", "variable", "duplicate", "chars", "key", "binding", "shadow", "related"]
)
def test_unknown_settled_source_cannot_exclude_a_session(change):
    script = unrelated_settled_poll()
    if change == "extra":
        script += "text(await tools.exec_command({cmd:'StopApi'}));"
    elif change == "variable":
        script = script.replace("[51,52,53]", "unknown")
    elif change == "duplicate":
        script = script.replace("[51,52,53]", "[51,51,53]")
    elif change == "chars":
        script = script.replace("chars:''", "chars:'x'")
    elif change == "key":
        script = script.replace("max_output_tokens:20", "unexpected:20")
    elif change == "binding":
        script = script.replace("values.forEach", "other.forEach")
    elif change == "shadow":
        script = script.replace("values", "text")
    else:
        script = script.replace("[51,52,53]", "[41,42,43]")
    assert module()._definitely_unrelated_settled_poll(script, 42) is False


def stored_poll_rows(session=51):
    producer = (
        "const result=await tools.exec_command({cmd:'Stop-Process -Id 999',"
        "yield_time_ms:1000,max_output_tokens:20});store('synthetic-key',result);text(result)"
    )
    poll = (
        "const held=load('synthetic-key');text(await tools.write_stdin({"
        "session_id:held.session_id,chars:'',yield_time_ms:1000,max_output_tokens:20}))"
    )
    return [
        event(
            {"type": "custom_tool_call", "name": "exec", "call_id": "producer", "input": producer},
            2,
        ),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "producer",
                "output": [
                    {"type": "text", "text": "Script completed"},
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"session_id": session, "exit_code": None, "output": ""}
                        ),
                    },
                ],
            },
            3,
        ),
        event({"type": "custom_tool_call", "name": "exec", "call_id": "dynamic", "input": poll}, 4),
    ]


def test_stored_poll_exclusion_preserves_terminal_and_omission_duties(tmp_path, monkeypatch):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[1]["payload"]["output"][0]["text"] = json.dumps({"session_id": 42, "output": ""})
    rows[1]["payload"]["output"].insert(0, {"type": "text", "text": "Script completed"})
    rows += stored_poll_rows()
    rows += [
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "dynamic",
                "output": [{"type": "image", "data": "synthetic-unused"}],
            },
            5,
        ),
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "later",
                "input": "text(await tools.write_stdin({session_id:42}));",
            },
            6,
        ),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "later",
                "output": [{"type": "text", "text": json.dumps({"exit_code": 0, "output": ""})}],
            },
            7,
        ),
    ]
    assert reader._chain("call-one", rows) == [{"exit_code": 0, "output": ""}]
    with pytest.raises(module().HistoricalReceiptError):
        reader._chain("dynamic", rows)
    rewrite(reader, recipe, source, rows)
    with pytest.raises(
        module().HistoricalReceiptError, match="history_inventory_coverage_incomplete"
    ):
        reader.read_original()


@pytest.mark.parametrize(
    "change",
    [
        "same_session",
        "no_producer",
        "other_key",
        "other_load",
        "poll_binding",
        "stored_binding",
        "text_binding",
        "poll_chars",
        "producer_dynamic",
        "producer_extra",
        "poll_extra",
        "shadow",
        "intervening",
        "intervening_store",
        "missing_output",
        "foreign_output",
        "duplicate_output",
        "output_after_poll",
        "nontext",
        "bad_text",
        "extra_text",
        "duplicate_json",
        "stdout_forgery",
        "bool_session",
        "float_session",
        "zero_session",
        "large_session",
        "terminal",
        "outer_running",
        "duplicate_option",
        "negative_option",
        "unknown_option",
    ],
)
def test_stored_poll_exclusion_never_infers_unknown_store_or_result(change):
    rows = stored_poll_rows(42 if change == "same_session" else 51)
    producer = rows[0]["payload"]
    output = rows[1]["payload"]
    poll = rows[2]["payload"]
    if change == "no_producer":
        rows = rows[1:]
    elif change == "other_key":
        poll["input"] = poll["input"].replace("synthetic-key", "different-key")
    elif change == "other_load":
        poll["input"] = poll["input"].replace("=load(", "=unknown(")
    elif change == "poll_binding":
        poll["input"] = poll["input"].replace("held.session_id", "other.session_id")
    elif change == "stored_binding":
        producer["input"] = producer["input"].replace("key',result", "key',other")
    elif change == "text_binding":
        producer["input"] = producer["input"].replace("text(result)", "text(other)")
    elif change == "poll_chars":
        poll["input"] = poll["input"].replace("chars:''", "chars:'x'")
    elif change == "producer_dynamic":
        producer["input"] = producer["input"].replace("'Stop-Process -Id 999'", "unknown")
    elif change == "producer_extra":
        producer["input"] += ";store(dynamic,other)"
    elif change == "poll_extra":
        poll["input"] += ";store(dynamic,other)"
    elif change == "shadow":
        producer["input"] = producer["input"].replace("result", "store")
    elif change in {"intervening", "intervening_store"}:
        rows.insert(
            2,
            event(
                {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "middle",
                    "input": "store('synthetic-key',unknown)"
                    if change == "intervening_store"
                    else "text(1)",
                }
            ),
        )
    elif change == "missing_output":
        del rows[1]
    elif change == "foreign_output":
        output["call_id"] = "foreign"
    elif change == "duplicate_output":
        rows.insert(2, rows[1])
    elif change == "output_after_poll":
        rows[1:] = [rows[2], rows[1]]
    elif change == "nontext":
        output["output"].append({"type": "image", "data": "synthetic"})
    elif change == "bad_text":
        output["output"].append({"type": "text", "text": 42})
    elif change == "extra_text":
        output["output"].append({"type": "text", "text": "extra"})
    elif change == "duplicate_json":
        output["output"][1]["text"] = '{"session_id":51,"session_id":42}'
    elif change == "stdout_forgery":
        output["output"][1]["text"] = json.dumps({"exit_code": 0, "output": '{"session_id":51}'})
    elif change in {"bool_session", "float_session", "zero_session", "large_session"}:
        value = {
            "bool_session": True,
            "float_session": 51.0,
            "zero_session": 0,
            "large_session": 2**31,
        }[change]
        output["output"][1]["text"] = json.dumps({"session_id": value, "output": ""})
    elif change == "terminal":
        output["output"][1]["text"] = json.dumps({"session_id": 51, "exit_code": 0, "output": ""})
    elif change == "outer_running":
        output["output"][0]["text"] = "Script running with cell ID synthetic"
    elif change == "duplicate_option":
        poll["input"] = poll["input"].replace(
            "max_output_tokens:20", "max_output_tokens:20,max_output_tokens:20"
        )
    elif change == "negative_option":
        poll["input"] = poll["input"].replace("max_output_tokens:20", "max_output_tokens:-1")
    elif change == "unknown_option":
        poll["input"] = poll["input"].replace("max_output_tokens:20", "unknown:20")
    position = next(i for i, row in enumerate(rows) if row["payload"].get("call_id") == "dynamic")
    assert module()._definitely_unrelated_stored_poll(rows, position, 42) is False


def test_stored_poll_same_session_does_not_gain_parser_or_receipt_support(tmp_path, monkeypatch):
    reader, _, _ = fixture(tmp_path, monkeypatch)
    rows = stored_poll_rows(42)
    script = rows[-1]["payload"]["input"]
    for decode in (module()._poll_sessions, module()._result_slots):
        with pytest.raises(module().HistoricalReceiptError):
            decode(script)
    with pytest.raises(module().HistoricalReceiptError):
        reader._chain("dynamic", rows)


@pytest.mark.parametrize(
    "fault", ["running", "missing", "nontext", "duplicate", "unknown_header", "wait_between"]
)
def test_stored_poll_requires_proved_absence_of_prior_outer_cells(fault):
    rows = stored_poll_rows()
    prior = [
        event({"type": "custom_tool_call", "name": "exec", "call_id": "prior", "input": "text(1)"}),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "prior",
                "output": [
                    {"type": "text", "text": "Script completed"},
                    {"type": "text", "text": "1"},
                ],
            }
        ),
    ]
    if fault == "running":
        prior[1]["payload"]["output"][0]["text"] = "Script running with cell ID synthetic"
    elif fault == "missing":
        prior.pop()
    elif fault == "nontext":
        prior[1]["payload"]["output"].append({"type": "image", "data": "synthetic"})
    elif fault == "duplicate":
        prior.append(prior[1])
    elif fault == "unknown_header":
        prior[1]["payload"]["output"][0]["text"] = "Script completed arbitrary tail"
    else:
        rows.insert(
            2,
            event(
                {
                    "type": "custom_tool_call",
                    "name": "functions.wait",
                    "call_id": "wait",
                    "input": "{}",
                }
            ),
        )
    rows = prior + rows
    assert module()._definitely_unrelated_stored_poll(rows, len(rows) - 1, 42) is False


def test_stored_poll_prior_completed_outer_cell_is_not_an_active_writer():
    rows = [
        event({"type": "custom_tool_call", "name": "exec", "call_id": "prior", "input": "text(1)"}),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "prior",
                "output": [
                    {"type": "text", "text": "Script completed"},
                    {"type": "text", "text": "1"},
                ],
            }
        ),
    ] + stored_poll_rows()
    assert module()._definitely_unrelated_stored_poll(rows, len(rows) - 1, 42) is True


@pytest.mark.parametrize("change", ["quoted_keys", "semicolons", "no_header"])
def test_stored_poll_exact_source_variants_keep_different_session_binding(change):
    rows = stored_poll_rows()
    if change == "quoted_keys":
        for index in (0, 2):
            for name in ("yield_time_ms", "max_output_tokens"):
                rows[index]["payload"]["input"] = rows[index]["payload"]["input"].replace(
                    name + ":", json.dumps(name) + ":"
                )
    elif change == "semicolons":
        rows[0]["payload"]["input"] += ";"
        rows[2]["payload"]["input"] += ";"
    else:
        rows[1]["payload"]["output"].pop(0)
    assert module()._definitely_unrelated_stored_poll(rows, 2, 42) is True


@pytest.mark.parametrize(
    "extra",
    [
        {"unknown": True},
        {"isError": True},
        {"isError": False},
        {"errors": []},
        {"partial": True},
        {"wall_time_seconds": float("nan")},
        {"wall_time_seconds": float("inf")},
        {"wall_time_seconds": True},
        {"wall_time_seconds": -1},
        {"wall_time_seconds": "1"},
        {"original_token_count": True},
        {"original_token_count": -1},
        {"original_token_count": 1.0},
        {"original_token_count": 2**31},
        {"chunk_id": ""},
        {"chunk_id": "bad/chunk"},
        {"chunk_id": "x" * 129},
        {"chunk_id": True},
        {"chunk_id": "한글"},
    ],
)
def test_stored_result_exclusion_rejects_unknown_error_or_malformed_envelope(extra):
    rows = stored_poll_rows()
    rows[1]["payload"]["output"][1]["text"] = json.dumps(
        {"session_id": 51, "exit_code": None, "output": "", **extra}
    )
    assert module()._definitely_unrelated_stored_poll(rows, 2, 42) is False


@pytest.mark.parametrize("wall_time", [0, 0.125])
def test_stored_result_known_optional_metadata_retains_exact_session(wall_time):
    rows = stored_poll_rows()
    rows[1]["payload"]["output"][1]["text"] = json.dumps(
        {
            "session_id": 51,
            "output": "",
            "chunk_id": "synthetic-1_A",
            "wall_time_seconds": wall_time,
            "original_token_count": 0,
        }
    )
    assert module()._definitely_unrelated_stored_poll(rows, 2, 42) is True


@pytest.mark.parametrize("late_text", ["Script completed", "Script running with cell ID synthetic"])
def test_prior_outer_response_uniqueness_extends_through_current_poll(late_text):
    prior = [
        event({"type": "custom_tool_call", "name": "exec", "call_id": "prior", "input": "text(1)"}),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "prior",
                "output": [
                    {"type": "text", "text": "Script completed"},
                    {"type": "text", "text": "1"},
                ],
            }
        ),
    ]
    rows = prior + stored_poll_rows()
    rows.insert(
        4,
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "prior",
                "output": [{"type": "text", "text": late_text}],
            }
        ),
    )
    assert module()._definitely_unrelated_stored_poll(rows, 5, 42) is False


def full_outer_header(kind="completed", cell="cellA", newline="\n"):
    first = "Script running with cell ID " + cell if kind == "running" else "Script " + kind
    return newline.join((first, "Wall time 0.125 seconds", "Output:", ""))


def literal_nonwriter(count=1):
    return "text(await tools.exec_command({cmd:'synthetic',max_output_tokens:20}));" * count


def prior_outer_rows(script=None, kind="completed", raw=False):
    header = full_outer_header(kind)
    return [
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "prior",
                "input": literal_nonwriter() if script is None else script,
            }
        ),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "prior",
                "output": header if raw else [{"type": "input_text", "text": header}],
            }
        ),
    ]


def outer_wait_rows(call_id="waitA", cell="cellA", kind="completed"):
    return [
        event(
            {
                "type": "function_call",
                "name": "functions.wait",
                "call_id": call_id,
                "arguments": json.dumps({"cell_id": cell, "yield_time_ms": 1000, "max_tokens": 20}),
            }
        ),
        event(
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": [{"type": "input_text", "text": full_outer_header(kind, cell)}],
            }
        ),
    ]


@pytest.mark.parametrize(
    "shape",
    [
        "completed",
        "failed",
        "crlf",
        "image",
        "running_wait",
        "raw_running_wait",
        "continued",
        "reused",
        "active_one",
        "active_three",
    ],
)
def test_closed_outer_protocol_or_exact_nonwriter_allows_only_source_exclusion(shape):
    prefix = prior_outer_rows()
    if shape == "failed":
        prefix = prior_outer_rows(script="store(key, unknown)", kind="failed")
    elif shape == "crlf":
        prefix[1]["payload"]["output"][0]["text"] = full_outer_header(newline="\r\n")
    elif shape == "image":
        prefix[1]["payload"]["output"].append(
            {"type": "input_image", "image_url": "data:image/png;base64,YQ==", "detail": "original"}
        )
    elif shape in {"running_wait", "raw_running_wait", "continued", "reused"}:
        prefix = prior_outer_rows(
            script="store(key, unknown)", kind="running", raw=shape == "raw_running_wait"
        )
        if shape == "continued":
            prefix += outer_wait_rows("waitFirst", kind="running")
        prefix += outer_wait_rows()
        if shape == "reused":
            extra = prior_outer_rows(kind="running")
            extra[0]["payload"]["call_id"] = "second"
            extra[1]["payload"]["call_id"] = "second"
            prefix += extra + outer_wait_rows("waitSecond")
    elif shape.startswith("active_"):
        prefix = prior_outer_rows(
            literal_nonwriter(3 if shape == "active_three" else 1), kind="running"
        )
    rows = prefix + stored_poll_rows()
    assert module()._definitely_unrelated_stored_poll(rows, len(rows) - 1, 42) is True


@pytest.mark.parametrize(
    "change",
    [
        "unknown_header",
        "header_suffix",
        "negative_time",
        "nan_time",
        "bare_cr",
        "mixed_newline",
        "raw_body",
        "raw_completed",
        "unknown_block",
        "image_key",
        "image_detail",
        "image_http",
        "image_base64",
        "active_unknown",
        "active_store",
        "active_other_store",
        "active_count_two",
        "active_extra",
        "active_dynamic",
        "active_alias",
        "active_duplicate_option",
        "wait_orphan",
        "wait_wrong_cell",
        "wait_running_wrong_cell",
        "wait_duplicate_key",
        "wait_unknown_arg",
        "wait_bool_bound",
        "wait_terminate",
        "wait_duplicate_output",
        "wait_response_before_call",
        "active_cell_collision",
        "overlapping_waits",
    ],
)
def test_outer_protocol_or_nonwriter_uncertainty_cannot_exclude_stored_poll(change):
    prefix = prior_outer_rows()
    if change in {
        "unknown_header",
        "header_suffix",
        "negative_time",
        "nan_time",
        "bare_cr",
        "mixed_newline",
    }:
        value = full_outer_header()
        value = {
            "unknown_header": value.replace("completed", "unknown"),
            "header_suffix": value + "extra",
            "negative_time": value.replace("0.125", "-1"),
            "nan_time": value.replace("0.125", "NaN"),
            "bare_cr": value.replace("\n", "\r"),
            "mixed_newline": value.replace("\n", "\r\n", 1),
        }[change]
        prefix[1]["payload"]["output"][0]["text"] = value
    elif change in {"raw_body", "raw_completed"}:
        prefix[1]["payload"]["output"] = full_outer_header(
            "running" if change == "raw_body" else "completed"
        )
        if change == "raw_body":
            prefix[1]["payload"]["output"] += "extra"
    elif change == "unknown_block":
        prefix[1]["payload"]["output"].append({"type": "unknown"})
    elif change.startswith("image_"):
        image = {
            "type": "input_image",
            "image_url": "data:image/png;base64,YQ==",
            "detail": "original",
        }
        if change == "image_key":
            image["extra"] = "unknown"
        elif change == "image_detail":
            image["detail"] = "unknown"
        elif change == "image_http":
            image["image_url"] = "https://example.invalid/synthetic.png"
        else:
            image["image_url"] = "data:image/png;base64,?"
        prefix[1]["payload"]["output"].append(image)
    elif change.startswith("active_") and change != "active_cell_collision":
        script = literal_nonwriter()
        if change == "active_unknown":
            script = "unknown()"
        elif change == "active_store":
            script += "store('synthetic-key',unknown)"
        elif change == "active_other_store":
            script += "store('another-key',unknown)"
        elif change == "active_count_two":
            script = literal_nonwriter(2)
        elif change == "active_extra":
            script += "text(1)"
        elif change == "active_dynamic":
            script = script.replace("'synthetic'", "unknown")
        elif change == "active_alias":
            script = script.replace("tools.exec_command", "alias.exec_command")
        else:
            script = script.replace(
                "max_output_tokens:20", "max_output_tokens:20,max_output_tokens:20"
            )
        prefix = prior_outer_rows(script, kind="running")
    else:
        prefix = prior_outer_rows("store(key, unknown)", kind="running")
        wait = outer_wait_rows()
        if change == "wait_orphan":
            prefix = prior_outer_rows()
        elif change == "wait_wrong_cell":
            wait = outer_wait_rows(cell="cellB")
        elif change == "wait_running_wrong_cell":
            wait[1]["payload"]["output"][0]["text"] = full_outer_header("running", "cellB")
        elif change == "wait_duplicate_key":
            wait[0]["payload"]["arguments"] = '{"cell_id":"cellA","cell_id":"cellB"}'
        elif change == "wait_unknown_arg":
            wait[0]["payload"]["arguments"] = '{"cell_id":"cellA","unknown":1}'
        elif change == "wait_bool_bound":
            wait[0]["payload"]["arguments"] = '{"cell_id":"cellA","max_tokens":true}'
        elif change == "wait_terminate":
            wait[0]["payload"]["arguments"] = '{"cell_id":"cellA","terminate":true}'
        elif change == "wait_duplicate_output":
            wait.append(wait[1])
        elif change == "wait_response_before_call":
            wait.reverse()
        elif change == "active_cell_collision":
            extra = prior_outer_rows(kind="running")
            extra[0]["payload"]["call_id"] = "second"
            extra[1]["payload"]["call_id"] = "second"
            prefix += extra
        elif change == "overlapping_waits":
            other = outer_wait_rows("waitB")
            wait = [wait[0], other[0], wait[1], other[1]]
        prefix += wait
    rows = prefix + stored_poll_rows()
    assert module()._definitely_unrelated_stored_poll(rows, len(rows) - 1, 42) is False


def test_formatted_producer_header_still_binds_one_actual_exec_result():
    rows = stored_poll_rows()
    rows[1]["payload"]["output"][0]["text"] = full_outer_header()
    assert module()._definitely_unrelated_stored_poll(rows, 2, 42) is True


def test_outer_envelope_text_aggregate_is_bounded_before_closure():
    rows = prior_outer_rows()
    rows[1]["payload"]["output"].append({"type": "text", "text": "x" * (16 * 1024 * 1024)})
    rows += stored_poll_rows()
    assert module()._definitely_unrelated_stored_poll(rows, len(rows) - 1, 42) is False


@pytest.mark.parametrize(
    "script",
    [
        "text(await tools.exec_command({cmd:'synthetic',max_output_tokens:20,"
        "yield_time_ms:1,workdir:'synthetic',sandbox_permissions:'use_default',"
        "justification:'synthetic'}));",
        "text(await tools.exec_command({cmd:'synthetic',max_output_tokens:20,"
        "sandbox_permissions:'require_escalated',justification:'synthetic'}));",
    ],
)
def test_active_nonwriter_finite_literal_options_are_not_shell_authorization(script):
    rows = prior_outer_rows(script, kind="running") + stored_poll_rows()
    assert module()._definitely_unrelated_stored_poll(rows, len(rows) - 1, 42) is True


@pytest.mark.parametrize(
    "script",
    [
        "const alias=tools.exec_command;text(await alias({cmd:'synthetic',max_output_tokens:20}));",
        "text(await tools['exec_command']({cmd:'synthetic',max_output_tokens:20}));",
        "text(await tools.exec_command({cmd:`${unknown}`,max_output_tokens:20}));",
        "text(await tools.exec_command({cmd:'synthetic',max_output_tokens:20,env:{}}));",
        "text(await tools.exec_command({cmd:'synthetic',max_output_tokens:20,"
        "sandbox_permissions:'unknown'}));",
        "text(await tools.exec_command({cmd:'synthetic',max_output_tokens:true}));",
        "text(await tools.exec_command({cmd:'synthetic',max_output_tokens:20,yield_time_ms:0}));",
        "text(await tools.exec_command({cmd:'synthetic',max_output_tokens:20}));eval('synthetic');",
    ],
)
def test_active_unknown_callable_or_value_cannot_be_declared_nonwriter(script):
    rows = prior_outer_rows(script, kind="running") + stored_poll_rows()
    assert module()._definitely_unrelated_stored_poll(rows, len(rows) - 1, 42) is False


def mixed_settled_script():
    return (
        "const results=await Promise.allSettled(["
        "tools.write_stdin({session_id:51,chars:'',yield_time_ms:10,max_output_tokens:20}),"
        "tools.exec_command({cmd:'StopApi',yield_time_ms:10,max_output_tokens:20}),"
        "tools.exec_command({cmd:'StopApi',max_output_tokens:20})]);"
        "for(let idx=0;idx<results.length;idx++)text({idx,result:results[idx]});"
    )


def test_mixed_settled_closed_source_excludes_only_other_session():
    assert module()._definitely_unrelated_mixed_settled_poll(mixed_settled_script(), 42)
    quoted = mixed_settled_script().replace("cmd:'StopApi'", "'cmd':'text(); store(unknown)' ")
    assert module()._definitely_unrelated_mixed_settled_poll(quoted, 42)


@pytest.mark.parametrize("sought", [51, 0, -1, True, 2**31, "42", None])
def test_mixed_settled_invalid_or_equal_sought_denied(sought):
    assert not module()._definitely_unrelated_mixed_settled_poll(mixed_settled_script(), sought)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("session_id:51", "session_id:42"),
        ("session_id:51", "session_id:unknown"),
        ("session_id:51", "session_id:true"),
        ("session_id:51", "session_id:0"),
        ("session_id:51", "session_id:-1"),
        ("session_id:51", "session_id:2147483648"),
        ("chars:''", "chars:'x'"),
        ("session_id:51", "session_id:51,session_id:51"),
        ("yield_time_ms:10", "unknown:10"),
        ("yield_time_ms:10", "yield_time_ms:0"),
        ("max_output_tokens:20", "max_output_tokens:true"),
        ("cmd:'StopApi'", "cmd:unknown"),
        ("tools.exec_command", "tools.unknown"),
        ("tools.exec_command", "tools['exec_command']"),
        ("Promise.allSettled", "Promise.all"),
        ("idx=0", "idx=1"),
        ("idx<results.length", "idx<=results.length"),
        ("idx<results.length", "idx<other.length"),
        ("idx++", "++idx"),
        ("results[idx]", "results[other]"),
        ("text({idx,", "text({other,"),
        ("result:results", "idx:results"),
        ("result:results", "[unknown]:results"),
        ("text({idx,", "text({...idx,"),
        ("results", "Promise"),
        ("results", "idx"),
        ("idx", "text"),
        (";for", ";unknown();for"),
        ("});", '});store("synthetic",unknown);'),
        ("});", '});eval("synthetic");'),
        ("const results", "let results"),
        ("text({idx,result:results[idx]});", "{text({idx,result:results[idx]});}"),
        ("tools.exec_command({cmd:'StopApi',max_output_tokens:20})", "...unknown"),
        ("tools.exec_command({cmd:'StopApi',max_output_tokens:20})", "unknown()"),
    ],
)
def test_mixed_settled_mutated_whole_grammar_denied(old, new):
    assert not module()._definitely_unrelated_mixed_settled_poll(
        mixed_settled_script().replace(old, new), 42
    )


def test_mixed_settled_array_exact_count_and_order():
    script = mixed_settled_script()
    first = "tools.write_stdin({session_id:51,chars:'',yield_time_ms:10,max_output_tokens:20})"
    second = "tools.exec_command({cmd:'StopApi',yield_time_ms:10,max_output_tokens:20})"
    for mutated in (
        script.replace(first + "," + second, second + "," + first),
        script.replace(first + ",", ""),
        script.replace(first, first + "," + first),
        script[:-1],
        script + "text(1);",
        "x" * (1024 * 1024 + 1),
    ):
        assert not module()._definitely_unrelated_mixed_settled_poll(mutated, 42)


@pytest.mark.parametrize("grammar", ["mixed", "patched", "pair", "polls"])
@pytest.mark.parametrize("later", [False, True])
@pytest.mark.parametrize("forged", [False, True])
def test_mixed_settled_cannot_supply_terminal_or_omit_controls(
    tmp_path, monkeypatch, later, forged, grammar
):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[1]["payload"]["output"][0]["text"] = json.dumps({"session_id": 42, "output": ""})
    mixed = event(
        {
            "type": "custom_tool_call",
            "name": "exec",
            "call_id": "mixed",
            "input": settled_fixture_script(grammar),
        },
        2,
    )
    output = event(
        {
            "type": "custom_tool_call_output",
            "call_id": "mixed",
            "output": [
                {
                    "type": "text",
                    "text": json.dumps({"exit_code": 0, "output": "", "session_id": 42}),
                }
            ],
        },
        3,
    )
    rows.append(mixed)
    if grammar == "polls":
        rows.append(
            event(
                {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "omitted",
                    "input": 'text(await tools.exec_command({cmd:"StopBeat"}));',
                },
                3,
            )
        )
    if forged:
        rows.extend([output, output])
    if later:
        rows += [
            event(
                {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "later",
                    "input": "text(await tools.write_stdin({session_id:42}));",
                },
                4,
            ),
            event(
                {
                    "type": "custom_tool_call_output",
                    "call_id": "later",
                    "output": [
                        {"type": "text", "text": json.dumps({"exit_code": 0, "output": ""})}
                    ],
                },
                5,
            ),
        ]
        assert reader._chain("call-one", rows) == [{"exit_code": 0, "output": ""}]
    else:
        with pytest.raises(module().HistoricalReceiptError):
            reader._chain("call-one", rows)
    with pytest.raises(module().HistoricalReceiptError):
        reader._chain("mixed", rows)
    rewrite(reader, recipe, source, rows)
    reason = "history_inventory_coverage_incomplete" if later else "history_terminal_missing"
    with pytest.raises(module().HistoricalReceiptError, match=reason):
        reader.read_original()


@pytest.mark.parametrize("grammar", ["mixed", "patched", "pair", "polls"])
@pytest.mark.parametrize("session", ["42", "unknown"])
def test_mixed_settled_related_or_unknown_poll_never_uses_forged_output(
    tmp_path, monkeypatch, session, grammar
):
    reader, _, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[1]["payload"]["output"][0]["text"] = json.dumps({"session_id": 42, "output": ""})
    rows += [
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "mixed",
                "input": (settled_fixture_script(grammar)).replace(
                    "session_id:51", "session_id:" + session
                ),
            },
            2,
        ),
        event(
            {
                "type": "custom_tool_call_output",
                "call_id": "mixed",
                "output": [
                    {
                        "type": "text",
                        "text": json.dumps({"exit_code": 0, "session_id": 42, "output": ""}),
                    }
                ],
            },
            3,
        ),
    ]
    with pytest.raises(module().HistoricalReceiptError, match="history_result_linkage_invalid"):
        reader._chain("call-one", rows)


def test_mixed_settled_execs_remain_discoverable_but_slots_unsupported():
    script = mixed_settled_script()
    assert module()._shells(script) == ["StopApi", "StopApi"]
    with pytest.raises(module().HistoricalReceiptError):
        module()._result_slots(script)


def patched_settled_script():
    patch = (
        "*** Begin Patch\n*** Update File: synthetic-private/runtime.env\n"
        "@@\n-old\n+new\n*** End Patch"
    )
    return (
        "text(await tools.apply_patch(" + json.dumps(patch) + "));"
        "const results=await Promise.allSettled(["
        "tools.exec_command({cmd:'StopApi',yield_time_ms:10,max_output_tokens:20}),"
        "tools.write_stdin({session_id:51,chars:'',yield_time_ms:10,max_output_tokens:20})]);"
        "for(let idx=0;idx<results.length;idx++)text({idx,result:results[idx]});"
    )


def test_patched_settled_sensitive_edit_is_only_source_nonmembership():
    script = patched_settled_script()
    assert module()._definitely_unrelated_patched_settled_poll(script, 42)
    assert len(module()._patches(script)) == 1
    assert module()._shells(script) == ["StopApi"]
    with pytest.raises(module().HistoricalReceiptError):
        module()._result_slots(script)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("apply_patch", "unknown"),
        ("tools.apply_patch", "tools['apply_patch']"),
        ("session_id:51", "session_id:42"),
        ("session_id:51", "session_id:unknown"),
        ("session_id:51", "session_id:0"),
        ("session_id:51", "session_id:true"),
        ("chars:''", "chars:'x'"),
        ("idx=0", "idx=1"),
        ("idx<results.length", "idx<=results.length"),
        ("results[idx]", "other[idx]"),
        ("idx++", "++idx"),
        ("result:results", "idx:results"),
        ("max_output_tokens:20", "max_output_tokens:20,extra:1"),
        ("Promise.allSettled", "Promise.all"),
        ("const results", "const Promise"),
        (";const results", ";text(1);const results"),
        ("});", '});eval("synthetic");'),
    ],
)
def test_patched_settled_unknown_or_equal_grammar_denied(old, new):
    assert not module()._definitely_unrelated_patched_settled_poll(
        patched_settled_script().replace(old, new), 42
    )


@pytest.mark.parametrize("sought", [51, True, 0, -1, 2**31, None, "42"])
def test_patched_settled_invalid_sought_denied(sought):
    assert not module()._definitely_unrelated_patched_settled_poll(patched_settled_script(), sought)


def test_patched_settled_dynamic_patch_or_array_change_denied():
    script = patched_settled_script()
    prefix, rest = script.split(";const", 1)
    command = "tools.exec_command({cmd:'StopApi',yield_time_ms:10,max_output_tokens:20})"
    poll = "tools.write_stdin({session_id:51,chars:'',yield_time_ms:10,max_output_tokens:20})"
    for changed in (
        "text(await tools.apply_patch(unknown));const" + rest,
        "const" + rest,
        script.replace(command + "," + poll, poll + "," + command),
        script.replace(command, command + "," + command),
        script.replace(command + ",", ""),
        script + prefix + ";",
        script[:-1],
    ):
        assert not module()._definitely_unrelated_patched_settled_poll(changed, 42)


def test_patched_settled_never_issues_stage_support(tmp_path, monkeypatch):
    reader, _, _ = fixture(tmp_path, monkeypatch, command="StopApi")
    row = event(
        {
            "type": "custom_tool_call",
            "name": "exec",
            "call_id": "patched",
            "input": patched_settled_script(),
        },
        2,
    )
    output = event(
        {
            "type": "custom_tool_call_output",
            "call_id": "patched",
            "output": [
                {"type": "text", "text": "Script completed"},
                {"type": "text", "text": "{}"},
                {"type": "text", "text": json.dumps({"exit_code": 0, "output": ""})},
                {"type": "text", "text": json.dumps({"exit_code": 0, "output": ""})},
            ],
        },
        3,
    )
    assert module()._definitely_unrelated_patched_settled_poll(patched_settled_script(), 42)
    with pytest.raises(module().HistoricalReceiptError, match="history_support_invalid"):
        reader._recorded_stage(row, [row, output])


def add_synthetic_history_source(reader, recipe, source, rows):
    raw = b"".join(json.dumps(row).encode() + b"\n" for row in rows)
    second = source.with_name("rollout-synthetic-other.jsonl")
    second.write_bytes(raw)
    recipe["sources"].append(
        {
            "locator": str(second),
            "prefix_bytes": len(raw),
            "prefix_sha256": hashlib.sha256(raw).hexdigest(),
        }
    )
    reader.files.data = Protection().protect(json.dumps(recipe).encode())


@pytest.mark.parametrize("selected", [False, True])
def test_cross_source_conflicting_call_cannot_cover_or_collapse_control(
    tmp_path, monkeypatch, selected
):
    reader, recipe, source = fixture(tmp_path, monkeypatch)
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[0]["payload"]["input"] = 'text(await tools.exec_command({cmd:"StopBeat"}));'
    add_synthetic_history_source(reader, recipe, source, rows)
    if selected:
        recipe["calls"].append(dict(recipe["calls"][0], source=1))
        reader.files.data = Protection().protect(json.dumps(recipe).encode())
    with pytest.raises(module().HistoricalReceiptError):
        reader.read_original()


@pytest.mark.parametrize(
    "change",
    [
        "timestamp",
        "result",
        "missing_result",
        "reversed",
        "row_type",
        "extra_result",
        "output_timestamp",
        "support",
    ],
)
def test_cross_source_row_provenance_or_output_conflict_denied(tmp_path, monkeypatch, change):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    if change == "timestamp":
        rows[0]["timestamp"] = "2026-09-20T00:02:00Z"
    elif change == "result":
        rows[1]["payload"]["output"][0]["text"] = json.dumps(
            {"exit_code": 1, "output": "synthetic"}
        )
    elif change == "missing_result":
        rows.pop()
    elif change == "reversed":
        rows.reverse()
    elif change == "row_type":
        rows[0]["type"] = "other"
    elif change == "extra_result":
        extra = json.loads(json.dumps(rows[1]))
        extra["timestamp"] = "2026-09-20T00:03:00Z"
        rows.append(extra)
    elif change == "output_timestamp":
        rows[1]["timestamp"] = "2026-09-20T00:03:00Z"
    else:
        rows[0]["payload"]["input"] = 'text(await tools.exec_command({cmd:"Get-CimInstance"}));'
        recipe["calls"][0]["supports"] = [
            {
                "source": 1,
                "line": 1,
                "payload_sha256": hashlib.sha256(
                    json.dumps(rows[0], sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "kind": "target_observation",
            }
        ]
    add_synthetic_history_source(reader, recipe, source, rows)
    with pytest.raises(module().HistoricalReceiptError):
        reader.read_original()


@pytest.mark.parametrize("selected_mirror", [False, True])
def test_exact_full_row_fork_mirror_retains_one_control_receipt(
    tmp_path, monkeypatch, selected_mirror
):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    add_synthetic_history_source(reader, recipe, source, rows)
    if selected_mirror:
        recipe["calls"].append(dict(recipe["calls"][0], source=1))
        reader.files.data = Protection().protect(json.dumps(recipe).encode())
    manifest = reader.sanitized_manifest(reader.read_original())
    assert manifest["dispositions"] == {"application_terminal": 1}


def test_exact_duplicate_rows_within_one_source_keep_existing_dedup(tmp_path, monkeypatch):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rewrite(reader, recipe, source, rows + rows)
    assert reader.sanitized_manifest(reader.read_original())["dispositions"] == {
        "application_terminal": 1
    }


def pair_settled_script():
    return (
        "const results=await Promise.allSettled(["
        "tools.write_stdin({session_id:51,chars:'',yield_time_ms:10,max_output_tokens:20}),"
        "tools.exec_command({cmd:'StopApi',max_output_tokens:20})]);"
        "for(let idx=0;idx<results.length;idx++)text({idx,result:results[idx]});"
    )


def settled_fixture_script(grammar):
    return {
        "mixed": mixed_settled_script,
        "patched": patched_settled_script,
        "pair": pair_settled_script,
        "polls": two_polls_settled_script,
    }[grammar]()


def test_pair_settled_exact_source_excludes_only_other_session():
    script = pair_settled_script()
    assert module()._definitely_unrelated_pair_settled_poll(script, 42)
    assert module()._definitely_unrelated_pair_settled_poll(
        script.replace("results", "values").replace("idx", "offset").replace("cmd:", "'cmd':"), 42
    )
    assert module()._shells(script) == ["StopApi"]
    assert module()._patches(script) == []
    with pytest.raises(module().HistoricalReceiptError):
        module()._result_slots(script)


@pytest.mark.parametrize("sought", [51, True, False, 0, -1, 2**31, None, "42"])
def test_pair_settled_equal_invalid_sought_denied(sought):
    assert not module()._definitely_unrelated_pair_settled_poll(pair_settled_script(), sought)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("session_id:51", "session_id:42"),
        ("session_id:51", "session_id:unknown"),
        ("session_id:51", "session_id:true"),
        ("session_id:51", "session_id:2147483648"),
        ("chars:''", "chars:'x'"),
        ("yield_time_ms:10", "yield_time_ms:0"),
        ("cmd:'StopApi',max", "cmd:'StopApi',yield_time_ms:10,max"),
        ("max_output_tokens:20", "max_output_tokens:20,max_output_tokens:20"),
        ("max_output_tokens:20", "unknown:20"),
        ("idx=0", "idx=1"),
        ("idx++", "++idx"),
        ("idx<results.length", "idx<=results.length"),
        ("results[idx]", "other[idx]"),
        ("result:results", "idx:results"),
        ("results", "text"),
        ("idx", "results"),
        ("text({idx,", "text({...idx,"),
        ("tools.exec_command", "unknown"),
        ("Promise.allSettled", "Promise.all"),
        ("});", '});store("synthetic",unknown);'),
    ],
)
def test_pair_settled_closed_grammar_mutations_deny(old, new):
    assert not module()._definitely_unrelated_pair_settled_poll(
        pair_settled_script().replace(old, new), 42
    )


def test_pair_settled_fixed_cardinality_order_prefix_and_size():
    script = pair_settled_script()
    poll = "tools.write_stdin({session_id:51,chars:'',yield_time_ms:10,max_output_tokens:20})"
    command = "tools.exec_command({cmd:'StopApi',max_output_tokens:20})"
    for value in (
        script.replace(poll + "," + command, command + "," + poll),
        script.replace(poll + ",", ""),
        script.replace(command, command + "," + command),
        'text(await tools.apply_patch("synthetic"));' + script,
        script[:-1],
        script + "text(1);",
        "x" * (1024 * 1024 + 1),
    ):
        assert not module()._definitely_unrelated_pair_settled_poll(value, 42)


def test_fixed_settled_internal_grammar_dispatch_unknown_denied():
    assert not module()._unrelated_fixed_settled_poll(pair_settled_script(), 42, grammar="unknown")


def two_polls_settled_script():
    return (
        "const results=await Promise.allSettled(["
        "tools.write_stdin({session_id:51,chars:'',yield_time_ms:10,max_output_tokens:20}),"
        "tools.write_stdin({session_id:52,chars:'',yield_time_ms:10,max_output_tokens:20})]);"
        "for(let idx=0;idx<results.length;idx++)text({idx,result:results[idx]});"
    )


def batch_settled_script(group):
    """Synthetic whole forms, independent from the production matcher table."""

    def poll(session, reverse=False):
        options = (
            "max_output_tokens:7,yield_time_ms:10"
            if reverse
            else "yield_time_ms:10,max_output_tokens:7"
        )
        return f"tools.write_stdin({{session_id:{session},chars:'',{options}}})"

    p, p2, p3 = (poll(session) for session in (51, 52, 53))
    e = 'tools.exec_command({cmd:"StopBeat",max_output_tokens:7})'
    y = 'tools.exec_command({cmd:"StopBeat",yield_time_ms:10,max_output_tokens:7})'
    f = (
        'tools.exec_command({cmd:"StopBeat",workdir:"synthetic",'
        'sandbox_permissions:"require_escalated",login:false,max_output_tokens:7})'
    )
    g = f[:-2] + ",yield_time_ms:10})"
    c = "tools.clock__curr_time({})"
    a = 'text(await tools.apply_patch("synthetic sensitive edit"));'
    arrays = {
        1: [p, p2, p3, e],
        2: [p, p2, p3],
        3: [p, p2, p3],
        4: [p, p2, e],
        5: [p, p2, c],
        6: [p, p2],
        7: [p, e],
        8: [e, e, p],
        9: [e, p],
        10: [c, e, p],
        11: [e, poll(51, True)],
        12: [y, e],
        14: [p, p2],
        15: [g, p],
    }
    if group == 13:
        return f"for(const sid of [51,52])text(await {poll('sid')});text(await {y});"
    prefix = f"text(await {e});" if group == 2 else a + f"text(await {f});" if group == 14 else ""
    tail = f"text(await {p});" if group == 12 else ""
    value = "...results[i]" if group in {6, 7, 11, 14, 15} else "value:results[i]"
    return (
        prefix
        + "const results=await Promise.allSettled(["
        + ",".join(arrays[group])
        + "]);for(let i=0;i<results.length;i++)text({i,"
        + value
        + "});"
        + tail
    )


@pytest.mark.parametrize("group", range(1, 16))
def test_batch_finite_forms_are_source_only(group):
    script = batch_settled_script(group)
    assert module()._definitely_unrelated_batch_settled_poll(script, 42)
    renamed = script.replace("results", "answers").replace("sid", "target")
    renamed = renamed.replace("session_id:", '"session_id":').replace("cmd:", '"cmd":')
    assert module()._definitely_unrelated_batch_settled_poll(renamed, 43)
    with pytest.raises(module().HistoricalReceiptError):
        module()._result_slots(script)


@pytest.mark.parametrize("group", range(1, 16))
@pytest.mark.parametrize("bad", ["42", "unknown", "true", "0", "-1", "2147483648", "1.0", "01"])
def test_batch_every_poll_target_is_strict_unrelated(group, bad):
    script = batch_settled_script(group)
    for session in (51, 52, 53):
        if str(session) in script:
            assert not module()._definitely_unrelated_batch_settled_poll(
                script.replace(str(session), bad), 42
            )


@pytest.mark.parametrize("group", range(1, 16))
def test_batch_distinct_targets_and_whole_script(group):
    script = batch_settled_script(group)
    for first, second in ((51, 52), (51, 53), (52, 53)):
        if str(second) in script:
            assert not module()._definitely_unrelated_batch_settled_poll(
                script.replace(str(second), str(first)), 42
            )
    for suffix in (
        "text(1);",
        "store('x',1);",
        "text(await tools.write_stdin({session_id:42}));",
        "catch(e){}",
        "finally{}",
    ):
        assert not module()._definitely_unrelated_batch_settled_poll(script + suffix, 42)
        assert not module()._definitely_unrelated_batch_settled_poll(suffix + script, 42)
    assert not module()._definitely_unrelated_batch_settled_poll(script[:-1], 42)


@pytest.mark.parametrize("sought", [True, None, 0, -1, 2**31, 42.0, "42"])
def test_batch_sought_is_strict(sought):
    assert not module()._definitely_unrelated_batch_settled_poll(batch_settled_script(1), sought)


@pytest.mark.parametrize(
    "group,old,new",
    [
        (1, "i=0", "i=1"),
        (1, "i<results.length", "i<=results.length"),
        (1, "i++", "++i"),
        (1, "results[i]", "answers[i]"),
        (1, "results[i]", "results[0]"),
        (1, "value:", "i:"),
        (1, "const results", "const i"),
        (1, "text({", "notify({"),
        (1, "chars:''", "chars:'x'"),
        (1, "max_output_tokens:7", "max_output_tokens:0"),
        (1, 'cmd:"StopBeat"', "cmd:command"),
        (1, 'cmd:"StopBeat"', 'cmd:"StopBeat",env:{}'),
        (1, 'cmd:"StopBeat"', 'cmd:"StopBeat",cmd:"again"'),
        (5, "clock__curr_time({})", "clock__curr_time({now:true})"),
        (5, "clock__curr_time", "other_clock"),
        (6, "...results[i]", "...other[i]"),
        (6, "...results[i]", "...results"),
        (6, "...results[i]", "...results[i],extra:1"),
        (6, "...results[i]", "...results[i]()"),
        (6, "...results[i]", "get x(){return results[i]}"),
        (11, "max_output_tokens:7,yield_time_ms:10", "yield_time_ms:10,max_output_tokens:7"),
        (12, "text(await tools.write_stdin", "text(await tools.exec_command"),
        (13, "session_id:sid", "session_id:other"),
        (13, "[51,52]", "[51,52,53]"),
        (13, "for(const sid", "for(let sid"),
        (13, "text(await tools.exec_command", "{text(await tools.exec_command"),
        (14, "login:false", "login:true"),
        (14, "require_escalated", "use_default"),
        (14, 'workdir:"synthetic"', "workdir:directory"),
        (14, 'apply_patch("synthetic sensitive edit")', "apply_patch(patch)"),
        (15, "max_output_tokens:7,yield_time_ms:10", "yield_time_ms:10,max_output_tokens:7"),
        (15, "...results[i]", "value:results[i]"),
    ],
)
def test_batch_closed_options_bindings_and_emissions(group, old, new):
    script = batch_settled_script(group)
    assert old in script
    assert not module()._definitely_unrelated_batch_settled_poll(script.replace(old, new), 42)


@pytest.mark.parametrize("group", range(1, 16))
def test_batch_has_no_optional_cross_product_or_extra_body(group):
    script = batch_settled_script(group)
    for mutated in (
        "text(await tools.clock__curr_time({}));" + script,
        script + "text(await tools.clock__curr_time({}));",
        script.replace("text({", "{text({"),
        script.replace("tools.write_stdin", "other.write_stdin"),
        script.replace("chars:''", "chars:`${unknown}`"),
        script.replace("max_output_tokens:7", "max_output_tokens:7,unknown:1"),
    ):
        if mutated != script:
            assert not module()._definitely_unrelated_batch_settled_poll(mutated, 42)
    if group != 13:
        extra = ",tools.write_stdin({session_id:54,chars:'',yield_time_ms:10,max_output_tokens:7})"
        assert not module()._definitely_unrelated_batch_settled_poll(
            script.replace("]);for", extra + "]);for"), 42
        )


@pytest.mark.parametrize("group", range(1, 16))
@pytest.mark.parametrize("target", ["42", "unknown"])
def test_batch_related_poll_cannot_consume_forged_terminal(tmp_path, monkeypatch, group, target):
    reader, _, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[1]["payload"]["output"][0]["text"] = json.dumps({"session_id": 42, "output": ""})
    rows.extend(
        [
            event(
                {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "batch",
                    "input": batch_settled_script(group).replace("51", target),
                },
                2,
            ),
            event(
                {
                    "type": "custom_tool_call_output",
                    "call_id": "batch",
                    "output": [
                        {
                            "type": "text",
                            "text": json.dumps({"exit_code": 0, "session_id": 42, "output": ""}),
                        }
                    ],
                },
                3,
            ),
        ]
    )
    with pytest.raises(module().HistoricalReceiptError, match="history_result_linkage_invalid"):
        reader._chain("call-one", rows)


def test_batch_group14_patch_and_unknown_control_remain_unjudged(tmp_path, monkeypatch):
    reader, recipe, source = fixture(tmp_path, monkeypatch)
    script = batch_settled_script(14).replace("StopBeat", "python alias_recovery_cli.py opaque")
    assert module()._definitely_unrelated_batch_settled_poll(script, 42)
    assert module()._patches(script) == ["synthetic sensitive edit"]
    assert module()._shells(script) == ["python alias_recovery_cli.py opaque"]
    row = event(
        {"type": "custom_tool_call", "name": "exec", "call_id": "unjudged", "input": script}, 2
    )
    output = event(
        {
            "type": "custom_tool_call_output",
            "call_id": "unjudged",
            "output": [
                {"type": "text", "text": "Script completed"},
                {"type": "text", "text": "{}"},
                {"type": "text", "text": json.dumps({"exit_code": 0, "output": ""})},
                {"type": "text", "text": json.dumps({"exit_code": 0, "output": ""})},
            ],
        },
        3,
    )
    with pytest.raises(module().HistoricalReceiptError, match="history_support_invalid"):
        reader._recorded_stage(row, [row, output])
    rows = [json.loads(v) for v in source.read_bytes().splitlines()] + [row, output]
    rewrite(reader, recipe, source, rows)
    with pytest.raises(
        module().HistoricalReceiptError, match="history_inventory_control_grammar_unknown"
    ):
        reader.read_original()


@pytest.mark.parametrize(
    "output",
    [
        [],
        [{"type": "text", "text": "{}"}],
        [{"type": "text", "text": '{"exit_code":0,"output":""}'}],
    ],
)
def test_batch_group15_selected_exec_still_requires_own_supported_terminal(
    tmp_path, monkeypatch, output
):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopBeat")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[0]["payload"]["input"] = batch_settled_script(15)
    rows[1]["payload"]["output"] = output
    assert module()._definitely_unrelated_batch_settled_poll(rows[0]["payload"]["input"], 42)
    rewrite(reader, recipe, source, rows)
    with pytest.raises(module().HistoricalReceiptError):
        reader.read_original()


@pytest.mark.parametrize("group", range(1, 16))
@pytest.mark.parametrize("later", [False, True])
def test_batch_cannot_supply_terminal_or_hide_omission(tmp_path, monkeypatch, group, later):
    reader, recipe, source = fixture(tmp_path, monkeypatch, command="StopApi")
    rows = [json.loads(v) for v in source.read_bytes().splitlines()]
    rows[1]["payload"]["output"][0]["text"] = json.dumps({"session_id": 42, "output": ""})
    rows.append(
        event(
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "batch",
                "input": batch_settled_script(group),
            },
            2,
        )
    )
    forged = event(
        {
            "type": "custom_tool_call_output",
            "call_id": "batch",
            "output": [
                {
                    "type": "text",
                    "text": json.dumps({"exit_code": 0, "session_id": 42, "output": ""}),
                }
            ],
        },
        3,
    )
    rows.extend([forged, forged])
    if group in {3, 5, 6}:
        rows.append(
            event(
                {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "omitted",
                    "input": 'text(await tools.exec_command({cmd:"StopBeat"}));',
                },
                3,
            )
        )
    if later:
        rows.append(
            event(
                {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "later",
                    "input": "text(await tools.write_stdin({session_id:42}));",
                },
                4,
            )
        )
        rows.append(
            event(
                {
                    "type": "custom_tool_call_output",
                    "call_id": "later",
                    "output": [
                        {"type": "text", "text": json.dumps({"exit_code": 0, "output": ""})}
                    ],
                },
                5,
            )
        )
        assert reader._chain("call-one", rows) == [{"exit_code": 0, "output": ""}]
    else:
        with pytest.raises(module().HistoricalReceiptError):
            reader._chain("call-one", rows)
    with pytest.raises(module().HistoricalReceiptError):
        reader._chain("batch", rows)
    rewrite(reader, recipe, source, rows)
    reason = "history_inventory_coverage_incomplete" if later else "history_terminal_missing"
    with pytest.raises(module().HistoricalReceiptError, match=reason):
        reader.read_original()


def test_two_polls_fixed_source_nonmembership_only():
    script = two_polls_settled_script()
    assert module()._definitely_unrelated_two_polls_settled_poll(script, 42)
    assert module()._definitely_unrelated_two_polls_settled_poll(
        script.replace("results", "values")
        .replace("idx", "offset")
        .replace("session_id:", "'session_id':"),
        42,
    )
    assert module()._shells(script) == []
    assert module()._patches(script) == []
    with pytest.raises(module().HistoricalReceiptError):
        module()._result_slots(script)


@pytest.mark.parametrize("sought", [51, 52, True, False, 0, -1, 2**31, None, "42"])
def test_two_polls_equal_or_invalid_sought_denied(sought):
    assert not module()._definitely_unrelated_two_polls_settled_poll(
        two_polls_settled_script(), sought
    )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("session_id:51", "session_id:42"),
        ("session_id:52", "session_id:42"),
        ("session_id:52", "session_id:51"),
        ("session_id:51", "session_id:unknown"),
        ("session_id:52", "session_id:unknown"),
        ("session_id:52", "session_id:true"),
        ("session_id:51", "session_id:0"),
        ("session_id:52", "session_id:2147483648"),
        ("chars:''", "chars:'x'"),
        ("yield_time_ms:10", "yield_time_ms:0"),
        ("max_output_tokens:20", "max_output_tokens:20,extra:1"),
        ("session_id:51", "session_id:51,session_id:51"),
        ("idx=0", "idx=1"),
        ("idx++", "++idx"),
        ("idx<results.length", "idx<=results.length"),
        ("results[idx]", "results[other]"),
        ("result:results", "idx:results"),
        ("results", "tools"),
        ("idx", "results"),
        ("Promise.allSettled", "Promise.all"),
        ("write_stdin", "unknown"),
        ("text({idx,", "text({...idx,"),
        ("});", '});store("synthetic",unknown);'),
    ],
)
def test_two_polls_whole_finite_grammar_mutations_deny(old, new):
    assert not module()._definitely_unrelated_two_polls_settled_poll(
        two_polls_settled_script().replace(old, new), 42
    )


def test_two_polls_exact_two_no_extra_calls_or_prefix():
    script = two_polls_settled_script()
    second = "tools.write_stdin({session_id:52,chars:'',yield_time_ms:10,max_output_tokens:20})"
    for changed in (
        script.replace("," + second, ""),
        script.replace(second, second + "," + second),
        script.replace(second, "tools.exec_command({cmd:'StopApi',max_output_tokens:20})"),
        'text(await tools.apply_patch("synthetic"));' + script,
        script + 'text(await tools.exec_command({cmd:"StopApi"}));',
        script[:-1],
        "x" * (1024 * 1024 + 1),
    ):
        assert not module()._definitely_unrelated_two_polls_settled_poll(changed, 42)
