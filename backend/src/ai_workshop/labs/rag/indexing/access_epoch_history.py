"""Re-derive bounded original Codex receipts; never accept an H catalog as proof.

The reviewed recipe is private, fixed-name and protected. Its selectors locate
records; dispositions are derived from the actual commands and result chains.
Unknown linkage or missing contemporary support refuses rather than certifies.
"""

import ast
import base64
import hashlib
import json
import math
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from ai_workshop.infrastructure.local.credential_store_windows import (
    PrivateFilePort,
    ProtectionPort,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    OriginalDeploymentIdentity,
    OriginalTargetOrigin,
)


class HistoricalReceiptError(ValueError):
    """Fixed body-free refusal only."""


class DerivedHistoricalFacts:
    __slots__ = ()

    def __new__(cls) -> "DerivedHistoricalFacts":
        raise TypeError("history_facts_reader_issued_only")


def _fail(code: str = "history_receipt_invalid") -> HistoricalReceiptError:
    return HistoricalReceiptError(code)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise _fail()
        result[key] = value
    return result


def _json(raw: bytes | str) -> Any:
    return json.loads(raw, object_pairs_hook=_pairs)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_cross_source_call_equivalence(sources: list[list[dict[str, Any]]]) -> None:
    """Shared IDs may deduplicate only exact ordered invocation/output row mirrors."""
    kinds = {"custom_tool_call", "function_call", "custom_tool_call_output", "function_call_output"}
    occurrences: Counter[str] = Counter()
    for rows in sources:
        identifiers = set()
        for row in rows:
            payload = row.get("payload", {})
            identifier = payload.get("call_id")
            if payload.get("type") in kinds and type(identifier) is str:
                identifiers.add(identifier)
        occurrences.update(identifiers)
    shared = {identifier for identifier, count in occurrences.items() if count > 1}
    mirrors: dict[str, tuple[str, ...]] = {}
    for rows in sources:
        # First-occurrence order preserves the existing exact-row duplicate rule.
        local: dict[str, dict[str, None]] = {}
        for row in rows:
            payload = row.get("payload", {})
            identifier = payload.get("call_id")
            if (
                payload.get("type") not in kinds
                or type(identifier) is not str
                or identifier not in shared
            ):
                continue
            canonical = json.dumps(row, sort_keys=True, separators=(",", ":"))
            local.setdefault(identifier, {})[canonical] = None
        for identifier, ordered in local.items():
            sequence = tuple(ordered)
            if identifier in mirrors and mirrors[identifier] != sequence:
                raise _fail("history_source_call_conflict")
            mirrors[identifier] = sequence


def _timestamp(value: Any) -> datetime:
    if type(value) is not str:
        raise _fail()
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise _fail()
    return result


def _texts(value: Any) -> list[str]:
    if type(value) is str:
        return [value]
    if type(value) is list:
        return [
            v["text"]
            for v in value
            if type(v) is dict
            and v.get("type") in {"text", "output_text", "input_text"}
            and type(v.get("text")) is str
        ]
    raise _fail("history_result_linkage_invalid")


def _tokens(script: str) -> list[tuple[str, str]]:
    # Lex outside strings/comments; a source/test mention is not a tool call.
    pattern = (
        r"""//[^\n\r\u2028\u2029]*|/\*.*?\*/|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`|"""
        r"[A-Za-z_$][A-Za-z0-9_$]*|[0-9]+|\s+|."
    )
    tokens: list[tuple[str, str]] = []
    for match in re.finditer(pattern, script, re.S):
        raw = match.group()
        if raw.isspace() or raw.startswith("//") or raw.startswith("/*"):
            continue
        if raw[0] in {'"', "'", "`"}:
            if raw[0] == "`":
                if "${" in raw:
                    tokens.append(("expression", raw))
                    continue
                value = _json(
                    '"'
                    + raw[1:-1]
                    .replace("\\`", "`")
                    .replace('"', '\\"')
                    .replace("\n", "\\n")
                    .replace("\r", "\\r")
                    + '"'
                )
            else:
                value = _json(raw) if raw[0] == '"' else ast.literal_eval(raw)
            tokens.append(("string", value))
        else:
            tokens.append(("code", raw))
    return tokens


def _shells(script: str) -> list[str]:
    tokens = _tokens(script)
    values: list[str] = []
    for index in range(len(tokens) - 4):
        if tokens[index : index + 4] != [
            ("code", "tools"),
            ("code", "."),
            ("code", "exec_command"),
            ("code", "("),
        ]:
            continue
        if tokens[index + 4] != ("code", "{"):
            raise _fail("history_command_grammar_unknown")
        depth, command = 1, None
        cursor = index + 5
        while cursor < len(tokens) and depth:
            kind, value = tokens[cursor]
            if kind == "code" and value in {"{", "["}:
                depth += 1
            elif kind == "code" and value in {"}", "]"}:
                depth -= 1
            elif depth == 1 and value == "cmd" and kind in {"code", "string"}:
                if (
                    cursor + 3 >= len(tokens)
                    or tokens[cursor + 1] != ("code", ":")
                    or tokens[cursor + 2][0] != "string"
                    or tokens[cursor + 3] not in {("code", ","), ("code", "}")}
                    or command is not None
                ):
                    raise _fail("history_command_grammar_unknown")
                command = tokens[cursor + 2][1]
            cursor += 1
        if depth or command is None:
            raise _fail("history_command_grammar_unknown")
        values.append(command)
    return values


def _patches(script: str) -> list[str]:
    tokens = _tokens(script)
    result = []
    prefix = [("code", value) for value in ("await", "tools", ".", "apply_patch", "(")]
    for index in range(len(tokens) - 6):
        if tokens[index : index + 5] != prefix:
            continue
        if tokens[index + 5][0] != "string" or tokens[index + 6] != ("code", ")"):
            raise _fail("history_command_grammar_unknown")
        result.append(tokens[index + 5][1])
    return result


def _literal_poll_sessions(tokens: list[tuple[str, str]]) -> list[int]:
    sessions = []
    prefix = [("code", value) for value in ("tools", ".", "write_stdin", "(", "{")]
    for index in range(len(tokens) - 5):
        if tokens[index : index + 5] != prefix:
            continue
        cursor, depth, session = index + 5, 1, None
        while cursor < len(tokens) and depth:
            kind, value = tokens[cursor]
            if kind == "code" and value == "{":
                depth += 1
            elif kind == "code" and value == "}":
                depth -= 1
            elif depth == 1 and value == "session_id":
                if tokens[cursor + 1] != ("code", ":") or session is not None:
                    raise _fail("history_result_linkage_invalid")
                number = ""
                cursor += 2
                while (
                    cursor < len(tokens)
                    and tokens[cursor][0] == "code"
                    and tokens[cursor][1].isdigit()
                ):
                    number += tokens[cursor][1]
                    cursor += 1
                if not number or tokens[cursor] not in {("code", ","), ("code", "}")}:
                    raise _fail("history_result_linkage_invalid")
                session = int(number)
                continue
            cursor += 1
        if session is None or depth:
            raise _fail("history_result_linkage_invalid")
        sessions.append(session)
    return sessions


_Invocation = tuple[str, int | None, Literal["structured", "stdout_only", "structured_tail"]]


def _expanded_invocations(script: str) -> list[_Invocation]:
    """Expand only a complete fixed literal polling loop, never evaluate JavaScript."""
    tokens = _tokens(script)
    names = [
        tokens[index + 2][1]
        for index in range(len(tokens) - 3)
        if tokens[index : index + 2] == [("code", "tools"), ("code", ".")]
        and tokens[index + 2] in {("code", "write_stdin"), ("code", "exec_command")}
        and tokens[index + 3] == ("code", "(")
    ]
    if "write_stdin" in names and ("code", "for") in tokens:
        cursor = 0

        def take(value: str) -> None:
            nonlocal cursor
            if cursor >= len(tokens) or tokens[cursor] != ("code", value):
                raise _fail("history_result_linkage_invalid")
            cursor += 1

        def number() -> int:
            nonlocal cursor
            if cursor >= len(tokens) or tokens[cursor][0] != "code":
                raise _fail("history_result_linkage_invalid")
            digits = tokens[cursor][1]
            if not re.fullmatch(r"[1-9][0-9]{0,9}", digits) or not int(digits) < 2**31:
                raise _fail("history_result_linkage_invalid")
            cursor += 1
            return int(digits)

        for value in ("for", "(", "const"):
            take(value)
        if (
            cursor >= len(tokens)
            or tokens[cursor][0] != "code"
            or not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", tokens[cursor][1])
        ):
            raise _fail("history_result_linkage_invalid")
        variable = tokens[cursor][1]
        if variable in {"tools", "text", "await", "for", "const", "of"}:
            raise _fail("history_result_linkage_invalid")
        cursor += 1
        take("of")
        take("[")
        sessions = [number()]
        while cursor < len(tokens) and tokens[cursor] == ("code", ","):
            take(",")
            sessions.append(number())
            if len(sessions) > 64:
                raise _fail("history_result_linkage_invalid")
        if len(set(sessions)) != len(sessions):
            raise _fail("history_result_linkage_invalid")
        for value in ("]", ")", "text", "(", "await", "tools", ".", "write_stdin", "(", "{"):
            take(value)
        keys: set[str] = set()
        while cursor < len(tokens) and tokens[cursor] != ("code", "}"):
            kind, key = tokens[cursor]
            if (
                kind not in {"code", "string"}
                or key not in {"session_id", "chars", "yield_time_ms", "max_output_tokens"}
                or key in keys
            ):
                raise _fail("history_result_linkage_invalid")
            keys.add(key)
            cursor += 1
            take(":")
            if key == "session_id":
                take(variable)
            elif key == "chars":
                if cursor >= len(tokens) or tokens[cursor] != ("string", ""):
                    raise _fail("history_result_linkage_invalid")
                cursor += 1
            else:
                number()
            if cursor < len(tokens) and tokens[cursor] == ("code", ","):
                take(",")
            elif cursor >= len(tokens) or tokens[cursor] != ("code", "}"):
                raise _fail("history_result_linkage_invalid")
        if not {"session_id", "chars"} <= keys:
            raise _fail("history_result_linkage_invalid")
        for value in ("}", ")", ")"):
            take(value)
        if cursor < len(tokens) and tokens[cursor] == ("code", ";"):
            take(";")
        invocations: list[_Invocation] = [
            ("write_stdin", session, "structured") for session in sessions
        ]
        if cursor < len(tokens):
            if len(sessions) not in {2, 3}:
                raise _fail("history_result_linkage_invalid")
            take("text")
            take("(")
            if len(sessions) == 3:
                take("(")
            for value in ("await", "tools", ".", "exec_command", "(", "{"):
                take(value)
            tail_keys: set[str] = set()
            while cursor < len(tokens) and tokens[cursor] != ("code", "}"):
                kind, key = tokens[cursor]
                if (
                    kind not in {"code", "string"}
                    or key not in {"cmd", "max_output_tokens"}
                    or key in tail_keys
                ):
                    raise _fail("history_result_linkage_invalid")
                tail_keys.add(key)
                cursor += 1
                take(":")
                if key == "cmd":
                    if cursor >= len(tokens) or tokens[cursor][0] != "string":
                        raise _fail("history_result_linkage_invalid")
                    cursor += 1
                else:
                    number()
                if cursor < len(tokens) and tokens[cursor] == ("code", ","):
                    take(",")
                elif cursor >= len(tokens) or tokens[cursor] != ("code", "}"):
                    raise _fail("history_result_linkage_invalid")
            if tail_keys != {"cmd", "max_output_tokens"}:
                raise _fail("history_result_linkage_invalid")
            suffix = ("}", ")", ")", ".", "output", ")") if len(sessions) == 3 else ("}", ")", ")")
            for value in suffix:
                take(value)
            if cursor < len(tokens) and tokens[cursor] == ("code", ";"):
                take(";")
            invocations.append(
                ("exec_command", None, "stdout_only" if len(sessions) == 3 else "structured_tail")
            )
        if cursor != len(tokens):
            raise _fail("history_result_linkage_invalid")
        return invocations
    literal_sessions = _literal_poll_sessions(tokens)
    if len(literal_sessions) != names.count("write_stdin"):
        raise _fail("history_result_linkage_invalid")
    session_iterator = iter(literal_sessions)
    return [
        (name, next(session_iterator) if name == "write_stdin" else None, "structured")
        for name in names
    ]


def _definitely_unrelated_settled_poll(script: str, sought: int) -> bool:
    """Closed literal source exclusion only; never decode settled output as proof."""
    try:
        tokens = _tokens(script)
        cursor = 0

        def take(value: str) -> None:
            nonlocal cursor
            if cursor >= len(tokens) or tokens[cursor] != ("code", value):
                raise _fail("history_result_linkage_invalid")
            cursor += 1

        def number() -> int:
            nonlocal cursor
            if cursor >= len(tokens) or tokens[cursor][0] != "code":
                raise _fail("history_result_linkage_invalid")
            value = tokens[cursor][1]
            if not re.fullmatch(r"[1-9][0-9]{0,9}", value) or not int(value) < 2**31:
                raise _fail("history_result_linkage_invalid")
            cursor += 1
            return int(value)

        take("const")
        if (
            cursor >= len(tokens)
            or tokens[cursor][0] != "code"
            or not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", tokens[cursor][1])
        ):
            return False
        binding = tokens[cursor][1]
        if binding in {"tools", "text", "Promise", "session_id", "const", "await", "for", "of"}:
            return False
        cursor += 1
        for value in ("=", "await", "Promise", ".", "allSettled", "(", "["):
            take(value)
        sessions = [number()]
        for _ in range(2):
            take(",")
            sessions.append(number())
        if len(set(sessions)) != 3:
            return False
        for value in (
            "]",
            ".",
            "map",
            "(",
            "session_id",
            "=",
            ">",
            "tools",
            ".",
            "write_stdin",
            "(",
            "{",
        ):
            take(value)
        keys: set[str] = set()
        while cursor < len(tokens) and tokens[cursor] != ("code", "}"):
            kind, key = tokens[cursor]
            if (
                kind not in {"code", "string"}
                or key not in {"session_id", "chars", "yield_time_ms", "max_output_tokens"}
                or key in keys
            ):
                return False
            keys.add(key)
            cursor += 1
            if key == "session_id":
                if kind != "code":
                    return False
            else:
                take(":")
                if key == "chars":
                    if cursor >= len(tokens) or tokens[cursor] != ("string", ""):
                        return False
                    cursor += 1
                else:
                    number()
            if cursor < len(tokens) and tokens[cursor] == ("code", ","):
                take(",")
            elif cursor >= len(tokens) or tokens[cursor] != ("code", "}"):
                return False
        if keys != {"session_id", "chars", "yield_time_ms", "max_output_tokens"}:
            return False
        for value in ("}", ")", ")", ")", ";", binding, ".", "forEach", "(", "text", ")"):
            take(value)
        if cursor < len(tokens) and tokens[cursor] == ("code", ";"):
            take(";")
        return (
            cursor == len(tokens)
            and type(sought) is int
            and 0 < sought < 2**31
            and sought not in sessions
        )
    except (ValueError, TypeError, SyntaxError, KeyError, AttributeError, IndexError):
        return False


def _definitely_unrelated_mixed_settled_poll(script: str, sought: int) -> bool:
    return _unrelated_fixed_settled_poll(script, sought, grammar="poll_exec_exec")


def _definitely_unrelated_patched_settled_poll(script: str, sought: int) -> bool:
    # The file edit remains unjudged; this never verifies its result or effects.
    return _unrelated_fixed_settled_poll(script, sought, grammar="patch_exec_poll")


def _definitely_unrelated_pair_settled_poll(script: str, sought: int) -> bool:
    return _unrelated_fixed_settled_poll(script, sought, grammar="poll_exec")


def _definitely_unrelated_two_polls_settled_poll(script: str, sought: int) -> bool:
    return _unrelated_fixed_settled_poll(script, sought, grammar="poll_poll")


def _unrelated_fixed_settled_poll(
    script: str,
    sought: int,
    *,
    grammar: Literal["poll_exec_exec", "patch_exec_poll", "poll_exec", "poll_poll"],
) -> bool:
    """Exclude one finite unrelated poll source; certify no settled output."""
    try:
        if (
            grammar not in {"poll_exec_exec", "patch_exec_poll", "poll_exec", "poll_poll"}
            or type(script) is not str
            or len(script) > 1024 * 1024
            or len(script.encode("utf-8")) > 1024 * 1024
            or type(sought) is not int
            or not 0 < sought < 2**31
        ):
            return False
        tokens = _tokens(script)
        cursor = 0

        def take(*values: str) -> None:
            nonlocal cursor
            for value in values:
                if cursor >= len(tokens) or tokens[cursor] != ("code", value):
                    raise _fail("history_result_linkage_invalid")
                cursor += 1

        def identifier() -> str:
            nonlocal cursor
            kind, value = tokens[cursor]
            reserved = {
                "await",
                "break",
                "case",
                "catch",
                "class",
                "const",
                "continue",
                "debugger",
                "default",
                "delete",
                "do",
                "else",
                "enum",
                "export",
                "extends",
                "false",
                "finally",
                "for",
                "function",
                "if",
                "import",
                "in",
                "instanceof",
                "let",
                "new",
                "null",
                "return",
                "super",
                "switch",
                "this",
                "throw",
                "true",
                "try",
                "typeof",
                "var",
                "void",
                "while",
                "with",
                "yield",
                "implements",
                "interface",
                "package",
                "private",
                "protected",
                "public",
                "static",
                "tools",
                "text",
                "Promise",
                "allSettled",
            }
            if (
                kind != "code"
                or not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", value)
                or value in reserved
            ):
                raise _fail("history_result_linkage_invalid")
            cursor += 1
            return value

        def key(value: str) -> None:
            nonlocal cursor
            if tokens[cursor] not in {("code", value), ("string", value)}:
                raise _fail("history_result_linkage_invalid")
            cursor += 1
            take(":")

        def literal() -> str:
            nonlocal cursor
            kind, value = tokens[cursor]
            if kind != "string":
                raise _fail("history_result_linkage_invalid")
            cursor += 1
            return value

        def number() -> int:
            nonlocal cursor
            kind, value = tokens[cursor]
            if kind != "code" or not re.fullmatch(r"[1-9][0-9]{0,9}", value) or int(value) >= 2**31:
                raise _fail("history_result_linkage_invalid")
            cursor += 1
            return int(value)

        if grammar == "patch_exec_poll":
            take("text", "(", "await", "tools", ".", "apply_patch", "(")
            literal()
            take(")", ")", ";")
        take("const")
        binding = identifier()
        take("=", "await", "Promise", ".", "allSettled", "(", "[")
        if grammar == "patch_exec_poll":
            take("tools", ".", "exec_command", "(", "{")
            key("cmd")
            literal()
            for option in ("yield_time_ms", "max_output_tokens"):
                take(",")
                key(option)
                number()
            take("}", ")", ",")
        take("tools", ".", "write_stdin", "(", "{")
        key("session_id")
        session = number()
        take(",")
        key("chars")
        if literal() != "":
            return False
        for option in ("yield_time_ms", "max_output_tokens"):
            take(",")
            key(option)
            number()
        take("}", ")")
        sessions = [session]
        if grammar == "poll_poll":
            take(",", "tools", ".", "write_stdin", "(", "{")
            key("session_id")
            sessions.append(number())
            if sessions[0] == sessions[1]:
                return False
            take(",")
            key("chars")
            if literal() != "":
                return False
            for option in ("yield_time_ms", "max_output_tokens"):
                take(",")
                key(option)
                number()
            take("}", ")")
        if grammar in {"poll_exec_exec", "poll_exec"}:
            option_sets = (
                (("yield_time_ms", "max_output_tokens"), ("max_output_tokens",))
                if grammar == "poll_exec_exec"
                else (("max_output_tokens",),)
            )
            for options in option_sets:
                take(",", "tools", ".", "exec_command", "(", "{")
                key("cmd")
                literal()
                for option in options:
                    take(",")
                    key(option)
                    number()
                take("}", ")")
        take("]", ")", ";", "for", "(", "let")
        index = identifier()
        if index == binding:
            return False
        take(
            "=",
            "0",
            ";",
            index,
            "<",
            binding,
            ".",
            "length",
            ";",
            index,
            "+",
            "+",
            ")",
            "text",
            "(",
            "{",
            index,
            ",",
        )
        field = identifier()
        if field == index:
            return False
        take(":", binding, "[", index, "]", "}", ")", ";")
        return cursor == len(tokens) and sought not in sessions
    except (ValueError, TypeError, SyntaxError, KeyError, AttributeError, IndexError):
        return False


# Each row is one approved whole script: prefix statements, settled array,
# emission, tail statements. These are not independently optional features.
_BATCH_SETTLED_FORMS: tuple[tuple[tuple[str, ...], tuple[str, ...], str, tuple[str, ...]], ...] = (
    ((), ("P", "P", "P", "E"), "nested", ()),
    (("E",), ("P", "P", "P"), "nested", ()),
    ((), ("P", "P", "P"), "nested", ()),
    ((), ("P", "P", "E"), "nested", ()),
    ((), ("P", "P", "C"), "nested", ()),
    ((), ("P", "P"), "spread", ()),
    ((), ("P", "E"), "spread", ()),
    ((), ("E", "E", "P"), "nested", ()),
    ((), ("E", "P"), "nested", ()),
    ((), ("C", "E", "P"), "nested", ()),
    ((), ("E", "Q"), "spread", ()),
    ((), ("Y", "E"), "nested", ("P",)),
    ((), (), "literal_for_of", ("Y",)),
    (("A", "F"), ("P", "P"), "spread", ()),
    ((), ("G", "P"), "spread", ()),
)


class _BatchSourceCursor:
    """Consume fixed syntax only; never evaluate source or inspect its outputs."""

    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.position = 0
        self.sessions: list[int] = []

    def take(self, *values: str) -> None:
        for value in values:
            if self.tokens[self.position] != ("code", value):
                raise _fail("history_result_linkage_invalid")
            self.position += 1

    def key(self, value: str) -> None:
        if self.tokens[self.position] not in {("code", value), ("string", value)}:
            raise _fail("history_result_linkage_invalid")
        self.position += 1
        self.take(":")

    def literal(self) -> str:
        kind, value = self.tokens[self.position]
        if kind != "string":
            raise _fail("history_result_linkage_invalid")
        self.position += 1
        return value

    def number(self) -> int:
        kind, value = self.tokens[self.position]
        if kind != "code" or not re.fullmatch(r"[1-9][0-9]{0,9}", value) or int(value) >= 2**31:
            raise _fail("history_result_linkage_invalid")
        self.position += 1
        return int(value)

    def identifier(self) -> str:
        kind, value = self.tokens[self.position]
        reserved = frozenset(
            [
                "await",
                "break",
                "case",
                "catch",
                "class",
                "const",
                "continue",
                "debugger",
                "default",
                "delete",
                "do",
                "else",
                "enum",
                "export",
                "extends",
                "false",
                "finally",
                "for",
                "function",
                "if",
                "import",
                "in",
                "instanceof",
                "let",
                "new",
                "null",
                "return",
                "super",
                "switch",
                "this",
                "throw",
                "true",
                "try",
                "typeof",
                "var",
                "void",
                "while",
                "with",
                "yield",
                "implements",
                "interface",
                "package",
                "private",
                "protected",
                "public",
                "static",
                "tools",
                "text",
                "Promise",
                "allSettled",
            ]
        )
        if (
            kind != "code"
            or not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", value)
            or value in reserved
        ):
            raise _fail("history_result_linkage_invalid")
        self.position += 1
        return value

    def atom(self, name: str, *, poll_binding: str | None = None) -> None:
        options: tuple[str, ...]
        self.take("tools", ".")
        if name == "A":
            self.take("apply_patch", "(")
            self.literal()
            self.take(")")
            return
        if name == "C":
            self.take("clock__curr_time", "(", "{", "}", ")")
            return
        if name in {"P", "Q"}:
            self.take("write_stdin", "(", "{")
            self.key("session_id")
            if poll_binding is None:
                self.sessions.append(self.number())
            else:
                self.take(poll_binding)
            self.take(",")
            self.key("chars")
            if self.literal() != "":
                raise _fail("history_result_linkage_invalid")
            options = (
                ("yield_time_ms", "max_output_tokens")
                if name == "P"
                else ("max_output_tokens", "yield_time_ms")
            )
        elif name in {"E", "Y", "F", "G"}:
            self.take("exec_command", "(", "{")
            self.key("cmd")
            self.literal()
            if name in {"F", "G"}:
                self.take(",")
                self.key("workdir")
                self.literal()
                self.take(",")
                self.key("sandbox_permissions")
                if self.literal() != "require_escalated":
                    raise _fail("history_result_linkage_invalid")
                self.take(",")
                self.key("login")
                self.take("false")
            options = {
                "E": ("max_output_tokens",),
                "Y": ("yield_time_ms", "max_output_tokens"),
                "F": ("max_output_tokens",),
                "G": ("max_output_tokens", "yield_time_ms"),
            }[name]
        else:
            raise _fail("history_result_linkage_invalid")
        for option in options:
            self.take(",")
            self.key(option)
            self.number()
        self.take("}", ")")

    def statement(self, name: str) -> None:
        self.take("text", "(", "await")
        self.atom(name)
        self.take(")", ";")

    def settled(self, atoms: tuple[str, ...], emission: str) -> None:
        self.take("const")
        binding = self.identifier()
        self.take("=", "await", "Promise", ".", "allSettled", "(", "[")
        for index, atom in enumerate(atoms):
            if index:
                self.take(",")
            self.atom(atom)
        self.take("]", ")", ";", "for", "(", "let")
        index_binding = self.identifier()
        if index_binding == binding:
            raise _fail("history_result_linkage_invalid")
        self.take(
            "=",
            "0",
            ";",
            index_binding,
            "<",
            binding,
            ".",
            "length",
            ";",
            index_binding,
            "+",
            "+",
            ")",
            "text",
            "(",
            "{",
            index_binding,
            ",",
        )
        if emission == "spread":
            self.take(".", ".", ".")
        elif emission == "nested":
            if self.identifier() == index_binding:
                raise _fail("history_result_linkage_invalid")
            self.take(":")
        else:
            raise _fail("history_result_linkage_invalid")
        self.take(binding, "[", index_binding, "]", "}", ")", ";")

    def literal_for_of(self) -> None:
        self.take("for", "(", "const")
        binding = self.identifier()
        self.take("of", "[")
        self.sessions.append(self.number())
        self.take(",")
        self.sessions.append(self.number())
        self.take("]", ")", "text", "(", "await")
        self.atom("P", poll_binding=binding)
        self.take(")", ";")


def _definitely_unrelated_batch_settled_poll(script: str, sought: int) -> bool:
    """Prove only poll nonmembership in one of fifteen immutable whole forms.

    Patch/exec statements remain unjudged. No result slots, selected-call
    terminals, omission coverage, admission or historical facts are supplied.
    """
    try:
        if (
            type(script) is not str
            or len(script) > 1024 * 1024
            or len(script.encode("utf-8")) > 1024 * 1024
            or type(sought) is not int
            or not 0 < sought < 2**31
        ):
            return False
        tokens = _tokens(script)
        for prefix, atoms, emission, tail in _BATCH_SETTLED_FORMS:
            cursor = _BatchSourceCursor(tokens)
            try:
                for atom in prefix:
                    cursor.statement(atom)
                if emission == "literal_for_of":
                    cursor.literal_for_of()
                else:
                    cursor.settled(atoms, emission)
                for atom in tail:
                    cursor.statement(atom)
                if (
                    cursor.position == len(tokens)
                    and cursor.sessions
                    and len(set(cursor.sessions)) == len(cursor.sessions)
                    and sought not in cursor.sessions
                ):
                    return True
            except (ValueError, TypeError, IndexError):
                continue
        return False
    except (ValueError, TypeError, SyntaxError, KeyError, AttributeError, IndexError):
        return False


def _stored_result_key(script: str, *, producer: bool) -> str:
    """Recognize one whole fixed store/load wrapper; never evaluate JS."""
    tokens = _tokens(script)
    cursor = 0

    def take(*values: str) -> None:
        nonlocal cursor
        for value in values:
            if cursor >= len(tokens) or tokens[cursor] != ("code", value):
                raise _fail("history_result_linkage_invalid")
            cursor += 1

    def literal() -> str:
        nonlocal cursor
        if cursor >= len(tokens) or tokens[cursor][0] != "string":
            raise _fail("history_result_linkage_invalid")
        value = tokens[cursor][1]
        cursor += 1
        return value

    def key(value: str) -> None:
        nonlocal cursor
        if cursor >= len(tokens) or tokens[cursor] not in {("code", value), ("string", value)}:
            raise _fail("history_result_linkage_invalid")
        cursor += 1
        take(":")

    def number() -> None:
        nonlocal cursor
        if cursor >= len(tokens) or tokens[cursor][0] != "code":
            raise _fail("history_result_linkage_invalid")
        value = tokens[cursor][1]
        if not re.fullmatch(r"[1-9][0-9]{0,9}", value) or not int(value) < 2**31:
            raise _fail("history_result_linkage_invalid")
        cursor += 1

    take("const")
    if cursor >= len(tokens) or tokens[cursor][0] != "code":
        raise _fail("history_result_linkage_invalid")
    binding = tokens[cursor][1]
    if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", binding) or binding in {
        "const",
        "let",
        "var",
        "await",
        "tools",
        "text",
        "store",
        "load",
        "for",
        "of",
        "return",
        "function",
        "if",
        "else",
        "while",
        "class",
        "new",
        "this",
        "throw",
    }:
        raise _fail("history_result_linkage_invalid")
    cursor += 1
    take("=")
    if producer:
        take("await", "tools", ".", "exec_command", "(", "{")
        key("cmd")
        literal()
    else:
        take("load", "(")
        stored_key = literal()
        take(")", ";", "text", "(", "await", "tools", ".", "write_stdin", "(", "{")
        key("session_id")
        take(binding, ".", "session_id", ",")
        key("chars")
        if literal() != "":
            raise _fail("history_result_linkage_invalid")
    take(",")
    key("yield_time_ms")
    number()
    take(",")
    key("max_output_tokens")
    number()
    take("}", ")")
    if producer:
        take(";", "store", "(")
        stored_key = literal()
        take(",", binding, ")", ";", "text", "(", binding, ")")
    else:
        take(")")
    if cursor < len(tokens) and tokens[cursor] == ("code", ";"):
        take(";")
    if cursor != len(tokens):
        raise _fail("history_result_linkage_invalid")
    return stored_key


def _outer_header(text: str) -> tuple[str, str | None]:
    if text == "Script completed":  # Existing explicit legacy Text header.
        return "completed", None
    match = re.fullmatch(
        r"Script (?:(completed|failed)|running with cell ID ([A-Za-z0-9_-]{1,128}))"
        r"(?P<nl>\r?\n)Wall time ((?:0|[1-9][0-9]*)(?:\.[0-9]+)?) seconds"
        r"(?P=nl)Output:(?P=nl)",
        text,
    )
    if match is None or len(match[4]) > 32 or not math.isfinite(float(match[4])):
        raise _fail("history_result_linkage_invalid")
    return match[1] or "running", match[2]


def _outer_envelope(value: Any) -> tuple[str, str | None]:
    """Closed wrapper state only: neither stdout nor a helper terminal receipt."""
    limit = 16 * 1024 * 1024
    if type(value) is str:
        if len(value) > 512:
            raise _fail("history_result_linkage_invalid")
        state, cell = _outer_header(value)
        if state != "running":
            raise _fail("history_result_linkage_invalid")
        return state, cell
    if type(value) is not list or not 1 <= len(value) <= 512:
        raise _fail("history_result_linkage_invalid")
    total = 0
    for item in value:
        if type(item) is not dict:
            raise _fail("history_result_linkage_invalid")
        if item.get("type") in {"text", "input_text", "output_text"}:
            if set(item) != {"type", "text"} or type(item["text"]) is not str:
                raise _fail("history_result_linkage_invalid")
            if len(item["text"]) > limit - total:
                raise _fail("history_result_linkage_invalid")
            total += len(item["text"].encode("utf-8"))
        elif item.get("type") == "input_image":
            if (
                set(item) != {"type", "image_url", "detail"}
                or type(item["image_url"]) is not str
                or type(item["detail"]) is not str
                or item["detail"] not in {"auto", "low", "high", "original"}
                or len(item["image_url"]) > limit
            ):
                raise _fail("history_result_linkage_invalid")
            encoded = re.fullmatch(
                r"data:image/(?:png|jpeg|webp|gif);base64,([A-Za-z0-9+/]+={0,2})", item["image_url"]
            )
            if encoded is None:
                raise _fail("history_result_linkage_invalid")
            base64.b64decode(encoded[1], validate=True)
            total += len(item["image_url"])
        else:
            raise _fail("history_result_linkage_invalid")
        if total > limit:
            raise _fail("history_result_linkage_invalid")
    first = value[0]
    if first.get("type") not in {"text", "input_text", "output_text"}:
        raise _fail("history_result_linkage_invalid")
    return _outer_header(first["text"])


def _literal_exec_text_nonwriter(script: str) -> bool:
    """Consume exactly one or three literal exec/text statements, no JS writer."""
    if len(script.encode("utf-8")) > 1024 * 1024:
        return False
    tokens, cursor, count = _tokens(script), 0, 0

    def take(*values: str) -> None:
        nonlocal cursor
        for value in values:
            if cursor >= len(tokens) or tokens[cursor] != ("code", value):
                raise _fail("history_result_linkage_invalid")
            cursor += 1

    while cursor < len(tokens):
        take("text", "(", "await", "tools", ".", "exec_command", "(", "{")
        keys: set[str] = set()
        while True:
            if cursor >= len(tokens):
                return False
            kind, key = tokens[cursor]
            if (
                kind not in {"code", "string"}
                or key
                not in {
                    "cmd",
                    "workdir",
                    "yield_time_ms",
                    "max_output_tokens",
                    "sandbox_permissions",
                    "justification",
                }
                or key in keys
            ):
                return False
            keys.add(key)
            cursor += 1
            take(":")
            if cursor >= len(tokens):
                return False
            kind, value = tokens[cursor]
            cursor += 1
            if key in {"yield_time_ms", "max_output_tokens"}:
                if (
                    kind != "code"
                    or re.fullmatch(r"[1-9][0-9]{0,9}", value) is None
                    or int(value) >= 2**31
                ):
                    return False
            elif (
                kind != "string"
                or key == "sandbox_permissions"
                and value not in {"use_default", "require_escalated"}
            ):
                return False
            if cursor < len(tokens) and tokens[cursor] == ("code", ","):
                take(",")
                continue
            break
        if not {"cmd", "max_output_tokens"} <= keys:
            return False
        take("}", ")", ")", ";")
        count += 1
        if count > 3:
            return False
    return count in {1, 3}


def _completed_outer_prefix(rows: list[dict[str, Any]], before: int, through: int) -> bool:
    """Every earlier isolate is closed or a whole-script proven store nonwriter."""
    if not 0 <= before <= through <= len(rows):
        return False
    calls: dict[str, tuple[int, dict[str, Any]]] = {}
    outputs: dict[str, list[tuple[int, Any]]] = {}
    for position, row in enumerate(rows[:through]):
        payload = row.get("payload", {})
        kind, call_id = payload.get("type"), payload.get("call_id")
        if kind in {"custom_tool_call", "function_call"} and payload.get("name") in {
            "exec",
            "functions.exec",
            "wait",
            "functions.wait",
        }:
            if type(call_id) is not str or not call_id or call_id in calls:
                return False
            if position < before:
                calls[call_id] = position, payload
        elif kind in {"custom_tool_call_output", "function_call_output"} and type(call_id) is str:
            outputs.setdefault(call_id, []).append((position, payload.get("output")))
    if len(calls) > 10000:
        return False
    # Events retain source order; wait bindings refer to the active generation,
    # never a reused label or a later response with the same numeric identifier.
    events: list[tuple[int, str, str, str | None, str | None]] = []
    scripts: dict[str, str] = {}
    for call_id, (position, payload) in calls.items():
        matched = outputs.get(call_id, [])
        if len(matched) != 1 or not position < matched[0][0] < before:
            return False
        state, cell = _outer_envelope(matched[0][1])
        if payload["name"] in {"exec", "functions.exec"}:
            script = payload.get("input", payload.get("arguments", ""))
            if type(script) is not str:
                return False
            scripts[call_id] = script
            events.append((position, "exec_begin", call_id, None, None))
            events.append((matched[0][0], "exec_result", call_id, state, cell))
        else:
            args = _json(payload.get("input", payload.get("arguments", "")))
            if (
                type(args) is not dict
                or not {"cell_id"}
                <= set(args)
                <= {"cell_id", "yield_time_ms", "max_tokens", "terminate"}
                or type(args["cell_id"]) is not str
                or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", args["cell_id"]) is None
                or any(
                    type(args[key]) is not int or not 0 < args[key] < 2**31
                    for key in ("yield_time_ms", "max_tokens")
                    if key in args
                )
                or "terminate" in args
                and args["terminate"] is not False
            ):
                return False
            events.append((position, "wait_begin", call_id, None, args["cell_id"]))
            events.append((matched[0][0], "wait_result", call_id, state, cell))
    pending: set[str] = set()
    active: dict[str, str] = {}
    waiting: dict[str, tuple[str, str]] = {}
    for _, kind, call_id, event_state, event_cell in sorted(events):
        if kind == "exec_begin":
            pending.add(call_id)
        elif kind == "exec_result":
            if call_id not in pending:
                return False
            if event_state == "running":
                if event_cell is None or event_cell in active:
                    return False
                active[event_cell] = call_id
            else:
                pending.remove(call_id)
        elif kind == "wait_begin":
            if (
                event_cell is None
                or event_cell not in active
                or any(v[0] == event_cell for v in waiting.values())
            ):
                return False
            waiting[call_id] = event_cell, active[event_cell]
        else:
            if call_id not in waiting:
                return False
            requested, generation = waiting.pop(call_id)
            if active.get(requested) != generation:
                return False
            if event_state == "running":
                if event_cell != requested:
                    return False
            else:
                del active[requested]
                pending.remove(generation)
    if waiting or set(active.values()) != pending:
        return False
    return all(_literal_exec_text_nonwriter(scripts[identifier]) for identifier in pending)


def _definitely_unrelated_stored_poll(
    rows: list[dict[str, Any]], position: int, sought: int
) -> bool:
    """Same-source preceding producer only; never issue a dynamic poll receipt."""
    try:
        if type(sought) is not int or not 0 < sought < 2**31 or not 0 <= position < len(rows):
            return False
        poll = rows[position].get("payload", {})
        if poll.get("type") not in {"custom_tool_call", "function_call"} or poll.get(
            "name"
        ) not in {"exec", "functions.exec"}:
            return False
        script = poll.get("input", poll.get("arguments", ""))
        if type(script) is not str:
            return False
        stored_key = _stored_result_key(script, producer=False)
        # Any intervening invocation is ambiguous, including a cell continuation.
        previous = next(
            (
                i
                for i in range(position - 1, -1, -1)
                if rows[i].get("payload", {}).get("type") in {"custom_tool_call", "function_call"}
            ),
            None,
        )
        if previous is None or not _completed_outer_prefix(rows, previous, position):
            return False
        producer = rows[previous].get("payload", {})
        if producer.get("name") not in {"exec", "functions.exec"}:
            return False
        producer_script = producer.get("input", producer.get("arguments", ""))
        if (
            type(producer_script) is not str
            or _stored_result_key(producer_script, producer=True) != stored_key
        ):
            return False
        call_id = producer.get("call_id")
        if type(call_id) is not str or not call_id or call_id == poll.get("call_id"):
            return False
        invocations = [
            i
            for i, row in enumerate(rows)
            if row.get("payload", {}).get("call_id") == call_id
            and row.get("payload", {}).get("type") in {"custom_tool_call", "function_call"}
        ]
        outputs = [
            (i, row.get("payload", {}).get("output"))
            for i, row in enumerate(rows)
            if row.get("payload", {}).get("call_id") == call_id
            and row.get("payload", {}).get("type")
            in {"custom_tool_call_output", "function_call_output"}
        ]
        if (
            invocations != [previous]
            or len(outputs) != 1
            or not previous < outputs[0][0] < position
        ):
            return False
        physical = outputs[0][1]
        if (
            type(physical) is not list
            or not physical
            or any(
                type(item) is not dict
                or item.get("type") not in {"text", "input_text", "output_text"}
                or type(item.get("text")) is not str
                for item in physical
            )
        ):
            return False
        texts = [item["text"] for item in physical]
        if len(texts) == 2:
            state, _ = _outer_header(texts[0])
            if state != "completed":
                return False
            texts = texts[1:]
        if len(texts) != 1:
            return False
        result = _json(texts[0])
        if (
            type(result) is not dict
            or type(result.get("output")) is not str
            or result.get("exit_code") is not None
        ):
            return False
        if (
            not {"session_id", "output"}
            <= set(result)
            <= {
                "session_id",
                "output",
                "exit_code",
                "chunk_id",
                "wall_time_seconds",
                "original_token_count",
            }
        ):
            return False
        if "chunk_id" in result and (
            type(result["chunk_id"]) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", result["chunk_id"]) is None
        ):
            return False
        if "wall_time_seconds" in result and (
            type(result["wall_time_seconds"]) not in {int, float}
            or not math.isfinite(result["wall_time_seconds"])
            or result["wall_time_seconds"] < 0
        ):
            return False
        if "original_token_count" in result and (
            type(result["original_token_count"]) is not int
            or not 0 <= result["original_token_count"] < 2**31
        ):
            return False
        session = result.get("session_id")
        return type(session) is int and 0 < session < 2**31 and session != sought
    except (
        ValueError,
        TypeError,
        SyntaxError,
        KeyError,
        AttributeError,
        IndexError,
        OverflowError,
    ):
        return False


def _poll_sessions(script: str) -> list[int]:
    return [
        session
        for name, session, _ in _expanded_invocations(script)
        if name == "write_stdin" and session is not None
    ]


def _result_slots(script: str) -> list[str]:
    return [name for name, _, _ in _expanded_invocations(script)]


def _poll_results(script: str, value: Any) -> list[dict[str, Any] | None]:
    """Bind physical emissions first; stdout never supplies terminal authority."""
    invocations = _expanded_invocations(script)
    if not any(kind in {"stdout_only", "structured_tail"} for _, _, kind in invocations):
        return [part for part in _parts(value)]
    if type(value) is not list or any(
        type(element) is not dict
        or element.get("type") not in {"text", "input_text", "output_text"}
        or type(element.get("text")) is not str
        for element in value
    ):
        raise _fail("history_result_linkage_invalid")
    texts = [element["text"] for element in value]
    if len(texts) == len(invocations) + 1 and texts[0].startswith("Script completed"):
        texts = texts[1:]
    if len(texts) != len(invocations):
        raise _fail("history_result_linkage_invalid")
    results: list[dict[str, Any] | None] = []
    poll_ids = {session for name, session, _ in invocations if name == "write_stdin"}
    for (name, session, kind), text in zip(invocations, texts, strict=True):
        if kind == "stdout_only":
            results.append(None)
            continue
        try:
            obj = _json(text)
        except (ValueError, TypeError):
            raise _fail("history_result_linkage_invalid") from None
        if type(obj) is not dict:
            raise _fail("history_result_linkage_invalid")
        code = obj.get("exit_code")
        if code is not None and type(code) is not int:
            raise _fail("history_result_linkage_invalid")
        if "session_id" in obj:
            if (
                type(obj["session_id"]) is not int
                or not 0 < obj["session_id"] < 2**31
                or name == "write_stdin"
                and obj["session_id"] != session
                or name == "exec_command"
                and obj["session_id"] in poll_ids
            ):
                raise _fail("history_result_linkage_invalid")
        elif code is None:
            raise _fail("history_result_linkage_invalid")
        results.append(obj)
    return results


def _potential_original_control(command: str, project: str) -> bool:
    """Only actual original-control binding can widen the selected inventory."""
    inline = re.search(r"@(['\"])\r?\n(.*?)\r?\n\1@", command, re.S)
    if inline is not None:
        try:
            tree = ast.parse(inline.group(2))
        except SyntaxError:
            return any(
                marker in command for marker in (project, "alias_recovery", "cutover_control")
            )
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = (
                    [item.name for item in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                if any("control_process" in name or "cutover_control" in name for name in modules):
                    return True
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module
                    and "alias_recovery" in node.module
                    and any(item.name != "load_original_settings" for item in node.names)
                ):
                    return True
            if isinstance(node, ast.Call):
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                if name in {"recover", "recover_local", "run_control", "execute_native"}:
                    return True
                if name in {"run", "Popen", "check_output", "system"}:
                    values = [
                        n.value
                        for arg in node.args
                        for n in ast.walk(arg)
                        if isinstance(n, ast.Constant) and type(n.value) is str
                    ]
                    if any(
                        project in value or "docker" in value.lower() or "alias_recovery" in value
                        for value in values
                    ):
                        return True
        return False
    stripped = re.sub(r"'[^']*'|\"[^\"]*\"", "", command)
    return bool(
        re.search(
            r"\b(?:docker|stopapi|startapi|stopbeat|startworker|stopworker|start-process|stop-process)\b",
            stripped,
            re.I,
        )
    ) or any(
        value in command
        for value in (
            "alias_recovery_cli",
            "recover-local",
            "recover-access-epoch",
            "cutover_control",
            "control_process_windows",
        )
    )


def _literal_helper_dispatch(source: str, argv: list[str]) -> ast.Module:
    """Project only a closed, literal argparse branch; never execute the helper."""
    tree = ast.parse(source)
    parsers: set[str] = set()
    bindings: dict[tuple[str, str], str] = {}
    positional: dict[str, str] = {}
    for item in tree.body:
        if isinstance(item, ast.Assign) and len(item.targets) == 1:
            target = item.targets[0]
            call = item.value
            if not isinstance(target, ast.Name) or not isinstance(call, ast.Call):
                continue
            if (
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "argparse"
                and call.func.attr == "ArgumentParser"
            ):
                parsers.add(target.id)
            elif (
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id in positional
                and call.func.attr == "parse_args"
                and not call.args
                and not call.keywords
            ):
                if not argv or argv[0] not in {"inspect", "migrate", "tests"}:
                    raise _fail("history_helper_dispatch_unknown")
                bindings[(target.id, positional[call.func.value.id])] = argv[0]
        if not isinstance(item, ast.Expr) or not isinstance(item.value, ast.Call):
            continue
        call = item.value
        if (
            isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in parsers
            and call.func.attr == "add_argument"
            and len(call.args) == 1
            and isinstance(call.args[0], ast.Constant)
            and type(call.args[0].value) is str
            and not call.args[0].value.startswith("-")
        ):
            choices = next((k.value for k in call.keywords if k.arg == "choices"), None)
            if (
                not isinstance(choices, (ast.List, ast.Tuple))
                or {v.value for v in choices.elts if isinstance(v, ast.Constant)}
                != {"inspect", "migrate", "tests"}
                or len(choices.elts) != 3
            ):
                raise _fail("history_helper_dispatch_unknown")
            positional[call.func.value.id] = call.args[0].value
    if not bindings:
        return tree
    namespace = {key[0] for key in bindings}
    if any(
        sum(
            isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == name
            for node in ast.walk(tree)
        )
        != 1
        for name in namespace | parsers
    ):
        raise _fail("history_helper_dispatch_unknown")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id in namespace
                for target in targets
            ):
                raise _fail("history_helper_dispatch_unknown")
    result: list[ast.stmt] = []
    for item in tree.body:
        if (
            isinstance(item, ast.If)
            and isinstance(item.test, ast.Compare)
            and isinstance(item.test.left, ast.Attribute)
            and isinstance(item.test.left.value, ast.Name)
            and len(item.test.ops) == len(item.test.comparators) == 1
            and isinstance(item.test.ops[0], ast.Eq)
            and isinstance(item.test.comparators[0], ast.Constant)
            and (item.test.left.value.id, item.test.left.attr) in bindings
        ):
            selected = bindings[(item.test.left.value.id, item.test.left.attr)]
            chosen = item.body if item.test.comparators[0].value == selected else item.orelse
            result.extend(chosen)
            if chosen and isinstance(chosen[-1], ast.Raise):
                exit_call = chosen[-1].exc
                if (
                    isinstance(exit_call, ast.Call)
                    and isinstance(exit_call.func, ast.Name)
                    and exit_call.func.id == "SystemExit"
                    and len(exit_call.args) == 1
                    and isinstance(exit_call.args[0], ast.Constant)
                    and type(exit_call.args[0].value) is int
                ):
                    break
        else:
            result.append(item)
    return ast.Module(body=result, type_ignores=[])


def _readonly_sql_attributes(tree: ast.Module) -> set[int]:
    literal_loop_values: dict[str, list[str]] = {}
    constants = {
        node.targets[0].id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, (ast.Dict, ast.List, ast.Tuple, ast.Constant))
    }
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.For)
            or not isinstance(node.iter, ast.Call)
            or not isinstance(node.iter.func, ast.Attribute)
            or node.iter.func.attr != "items"
            or not isinstance(node.iter.func.value, ast.Name)
            or node.iter.func.value.id not in constants
            or node.iter.args
            or node.iter.keywords
            or not isinstance(node.target, ast.Tuple)
            or len(node.target.elts) != 2
            or not isinstance(node.target.elts[1], ast.Tuple)
        ):
            continue
        try:
            values = ast.literal_eval(constants[node.iter.func.value.id])
        except (ValueError, TypeError):
            continue
        targets = node.target.elts[1].elts
        if (
            type(values) is not dict
            or not 1 <= len(values) <= 100
            or not all(isinstance(target, ast.Name) for target in targets)
            or not all(
                type(value) in {tuple, list}
                and len(value) == len(targets)
                and all(type(part) is str for part in value)
                for value in values.values()
            )
        ):
            continue
        for index, target in enumerate(targets):
            assert isinstance(target, ast.Name)
            literal_loop_values[target.id] = [value[index] for value in values.values()]

    def sql_values(node: ast.AST) -> list[str]:
        if isinstance(node, ast.Constant) and type(node.value) is str:
            return [node.value]
        if isinstance(node, ast.JoinedStr):
            values = [""]
            for part in node.values:
                if isinstance(part, ast.Constant) and type(part.value) is str:
                    parts = [part.value]
                elif (
                    isinstance(part, ast.FormattedValue)
                    and isinstance(part.value, ast.Name)
                    and part.value.id in literal_loop_values
                    and part.conversion == -1
                    and part.format_spec is None
                ):
                    parts = literal_loop_values[part.value.id]
                else:
                    raise _fail("history_sql_grammar_unknown")
                if len(values) * len(parts) > 10000:
                    raise _fail("history_sql_grammar_unknown")
                values = [value + suffix for value in values for suffix in parts]
            return values
        raise _fail("history_sql_grammar_unknown")

    builders = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module in {"sqlalchemy", "ai_workshop.shared.db"}
        for alias in node.names
        if alias.name == "create_engine"
    }
    text_builders = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "sqlalchemy"
        for alias in node.names
        if alias.name == "text"
    }
    engines = {
        node.targets[0].id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id in builders
    }
    connections = {
        item.optional_vars.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.With, ast.AsyncWith))
        for item in node.items
        if isinstance(item.optional_vars, ast.Name)
        and isinstance(item.context_expr, ast.Call)
        and isinstance(item.context_expr.func, ast.Attribute)
        and isinstance(item.context_expr.func.value, ast.Name)
        and item.context_expr.func.value.id in engines
        and item.context_expr.func.attr == "connect"
    }
    session_builders = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "ai_workshop.shared.db"
        for alias in node.names
        if alias.name == "create_session_factory"
    }
    factories = {
        node.targets[0].id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id in session_builders
        and len(node.value.args) == 1
        and isinstance(node.value.args[0], ast.Name)
        and node.value.args[0].id in engines
    }
    connections |= {
        item.optional_vars.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.With, ast.AsyncWith))
        for item in node.items
        if isinstance(item.optional_vars, ast.Name)
        and isinstance(item.context_expr, ast.Call)
        and isinstance(item.context_expr.func, ast.Name)
        and item.context_expr.func.id in factories
        and not item.context_expr.args
        and not item.context_expr.keywords
    }
    connections |= {
        item.optional_vars.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.With, ast.AsyncWith))
        for item in node.items
        if isinstance(item.optional_vars, ast.Name)
        and isinstance(item.context_expr, ast.Call)
        and not item.context_expr.args
        and not item.context_expr.keywords
        and isinstance(item.context_expr.func, ast.Call)
        and isinstance(item.context_expr.func.func, ast.Name)
        and item.context_expr.func.func.id in session_builders
        and len(item.context_expr.func.args) == 1
        and isinstance(item.context_expr.func.args[0], ast.Name)
        and item.context_expr.func.args[0].id in engines
        and not item.context_expr.func.keywords
    }
    allowed: set[int] = set()
    result_getters: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"execute", "scalar", "scalars", "exec_driver_sql"}:
            continue
        if node.func.attr in {"scalar", "scalars"} and not node.args and not node.keywords:
            result_getters.append(node)
            continue
        if (
            not isinstance(node.func.value, ast.Name)
            or node.func.value.id not in connections
            or not node.args
        ):
            raise _fail("history_sql_grammar_unknown")
        sql = node.args[0]
        if (
            isinstance(sql, ast.Call)
            and isinstance(sql.func, ast.Name)
            and sql.func.id in text_builders
            and len(sql.args) == 1
            and not sql.keywords
        ):
            sql = sql.args[0]
        for rendered in sql_values(sql):
            value = rendered.strip()
            if value.endswith(";") and value.count(";") == 1:
                value = value[:-1].rstrip()
            if value.upper() in {"SHOW TRANSACTION_READ_ONLY", "SHOW TRANSACTION_ISOLATION"}:
                continue
            if re.fullmatch(
                r"SET\s+TRANSACTION\s+(?:ISOLATION\s+LEVEL\s+(?:REPEATABLE\s+READ|READ\s+COMMITTED)\s*,?\s*)?READ\s+ONLY",
                value.upper(),
            ):
                continue
            stripped = re.sub(r"'[^']*'|\"[^\"]*\"", "", value).upper()
            if (
                not re.match(r"SELECT\b", stripped)
                or ";" in stripped
                or re.search(r'"[^"\n]+"\s*\(', value)
                or any(
                    qualifier.lower() != "pg_catalog"
                    for qualifier in re.findall(
                        r"\b([A-Za-z_][A-Za-z_0-9]*)\s*\.\s*[A-Za-z_][A-Za-z_0-9]*\s*\(",
                        value,
                    )
                )
                or re.search(r'"[^"\n]+"\s*\.\s*[A-Za-z_][A-Za-z_0-9]*\s*\(', value)
                or re.search(
                    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|COPY|CALL|DO|INTO|FOR\s+UPDATE)\b",
                    stripped,
                )
                or any(
                    name.lower()
                    not in {
                        "count",
                        "coalesce",
                        "max",
                        "min",
                        "sum",
                        "md5",
                        "in",
                        "and",
                        "or",
                        "not",
                        "exists",
                        "filter",
                        "where",
                        "any",
                        "all",
                        "pg_backend_pid",
                        "current_database",
                        "current_setting",
                        "to_regclass",
                        "to_jsonb",
                        "bool_and",
                        "bool_or",
                        "jsonb_agg",
                        "jsonb_build_object",
                        "json_build_object",
                        "array_agg",
                        "string_agg",
                        "row_to_json",
                        "lower",
                        "upper",
                        "from",
                        "as",
                        "cast",
                        "concat",
                        "concat_ws",
                        "length",
                        "octet_length",
                        "left",
                        "right",
                        "substring",
                        "substr",
                        "by",
                        "chr",
                        "jsonb_object_agg",
                        "json_object_agg",
                        "to_char",
                    }
                    for name in re.findall(r"\b([A-Z_][A-Z_0-9]*)\s*\(", stripped)
                )
            ):
                raise _fail("history_sql_grammar_unknown")
        allowed.add(id(node.func))
    results: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        result_value = node.value.value if isinstance(node.value, ast.Await) else node.value
        if (
            isinstance(node.targets[0], ast.Name)
            and isinstance(result_value, ast.Call)
            and isinstance(result_value.func, ast.Attribute)
            and id(result_value.func) in allowed
        ):
            results.add(node.targets[0].id)
    for node in result_getters:
        assert isinstance(node.func, ast.Attribute)
        result_value = node.func.value
        result_value = result_value.value if isinstance(result_value, ast.Await) else result_value
        if not (
            isinstance(result_value, ast.Name)
            and result_value.id in results
            or isinstance(result_value, ast.Call)
            and isinstance(result_value.func, ast.Attribute)
            and id(result_value.func) in allowed
        ):
            raise _fail("history_sql_grammar_unknown")
        allowed.add(id(node.func))
    return allowed


def _literal_python_code(command: str) -> str | None:
    inline = re.search(r"@(['\"])\r?\n(.*?)\r?\n\1@\s*\|[^\n]*python(?:\.exe)?\b", command, re.S)
    if inline is not None:
        return inline.group(2)
    match = re.search(r"python(?:\.exe)?[\"']?\s+(?:-(?:I|B)\s+)*-c\s+(['\"])", command, re.I)
    if match is None:
        return None
    quote = match.group(1)
    result = []
    index = match.end()
    while index < len(command):
        char = command[index]
        if char == quote:
            if index + 1 < len(command) and command[index + 1] == quote:
                result.append(char)
                index += 2
                continue
            return "".join(result)
        if quote == '"' and char == "$":
            raise _fail("history_command_grammar_unknown")
        if quote == '"' and char == "`":
            index += 1
            if index >= len(command) or command[index] not in {'"', "`", "$"}:
                raise _fail("history_command_grammar_unknown")
            char = command[index]
        result.append(char)
        index += 1
    raise _fail("history_command_grammar_unknown")


def _category(command: str) -> str:
    lowered = command.lower()
    # A metadata command earlier in a compound shell must not conceal an
    # actual process action. Quoted source fixtures are assessed by the AST.
    shell_code = re.sub(r"@(['\"])\r?\n.*?\r?\n\1@", "", command, flags=re.S)
    shell_code = re.sub(r"'[^']*'|\"[^\"]*\"", "", shell_code)
    inline = _literal_python_code(command)
    if inline is not None:
        lowered = shell_code.lower()
    if re.search(r"\b(?:stop-process|start-process)\b", shell_code, re.I):
        return "application"
    if re.match(r"\s*(get-content|rg\b|select-string|git\s+(diff|show|status))", lowered):
        if re.search(r";\s*(docker|stop-process|start-process)", lowered):
            raise _fail("history_control_unsettled")
        return "static_metadata"
    modules = re.findall(
        r"python(?:\.exe)?[\"']?\s+(?:-(?:I|B)\s+)*-m\s+([A-Za-z_][A-Za-z_0-9.]*)",
        command,
        re.I,
    )
    if modules and all(module in {"ruff", "mypy"} for module in modules):
        if len(re.findall(r"python(?:\.exe)?\b", shell_code, re.I)) != len(modules):
            raise _fail("history_control_grammar_unknown")
        return "static_metadata"
    if re.search(
        r"\bdocker\s+(?:(?:--context|-h|--host)\s+\S+\s+)?(?:start|stop|rm|compose)\b", lowered
    ):
        return "original_docker"
    if re.search(
        r"\b(?:stopbeat|stopapi|stopworker|startapi|startworker(?:beat)?|startbeat)\b", lowered
    ):
        return "application"
    if (
        "recover-local" in lowered
        or "recover-access-epoch" in lowered
        or re.search(
            r"python(?:\.exe)?[\"']?\s+-m\s+"
            r"ai_workshop\.labs\.rag\.indexing\.alias_recovery_cli\s+recover\b",
            lowered,
        )
    ):
        return "collector"
    if re.search(
        r"\b(?:docker|invoke-webrequest|get-ciminstance|get-nettcpconnection|preflight)\b", lowered
    ):
        return "readonly"
    if inline is not None:
        try:
            tree = ast.parse(inline)
        except SyntaxError:
            raise _fail("history_command_grammar_unknown") from None
        sql_attributes = _readonly_sql_attributes(tree)
        # String contents that write a source/test fixture do not themselves
        # submit commands. Actual invocation nodes are assessed separately.
        dangerous = {
            "execute",
            "Popen",
            "system",
            "startfile",
            "kill",
            "terminate",
            "recover",
            "recover_local",
            "run_control",
            "create_subprocess_exec",
            "create_subprocess_shell",
            "check_call",
            "check_output",
            "exec",
            "eval",
            "__import__",
            "getattr",
            "start",
            "launch",
            "worker_main",
            "apply",
            "apply_async",
            "send_task",
            "delay",
            "send_signal",
            "suspend",
            "resume",
            "revoke",
            "shutdown",
            "pool_restart",
            "pool_grow",
            "pool_shrink",
            "purge",
            "cancel_consumer",
            "broadcast",
            "enable_events",
            "disable_events",
            "rate_limit",
            "time_limit",
            "commit",
            "upgrade",
        }
        pure_prefixes = {
            "ast",
            "asyncio",
            "collections",
            "datetime",
            "hashlib",
            "json",
            "os",
            "pathlib",
            "re",
            "sys",
            "tempfile",
            "typing",
            "uuid",
            "sqlalchemy",
            "argparse",
            "subprocess",
        }
        subprocess_names = {
            alias.asname or alias.name
            for statement in ast.walk(tree)
            if isinstance(statement, ast.Import)
            for alias in statement.names
            if alias.name == "subprocess"
        }
        os_names = {
            alias.asname or alias.name
            for statement in ast.walk(tree)
            if isinstance(statement, ast.Import)
            for alias in statement.names
            if alias.name == "os"
        }
        inspected_members: dict[str, set[str]] = {}
        aliases = {
            node.targets[0].id: node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, (ast.Name, ast.Attribute))
        }

        def receiver(value: ast.AST) -> str:
            if isinstance(value, ast.Name) and value.id in aliases:
                value = aliases[value.id]
            return ast.dump(value, include_attributes=False).replace("ctx=Store()", "ctx=Load()")

        dataclass_members: dict[str, str] = {}
        stored_binding_owners = set()
        binding_receivers = set()
        for statement in ast.walk(tree):
            if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
                continue
            target = statement.targets[0]
            value = (
                statement.value.value if isinstance(statement.value, ast.Await) else statement.value
            )
            if (
                not isinstance(target, ast.Name)
                or not isinstance(value, ast.Call)
                or not isinstance(value.func, ast.Attribute)
            ):
                continue
            if value.func.attr == "latest_attempt":
                stored_binding_owners.add(target.id)
            if value.func.attr == "_binding":
                binding_receivers.add(receiver(target))
        for loop in ast.walk(tree):
            if (
                isinstance(loop, (ast.For, ast.comprehension))
                and isinstance(loop.target, ast.Name)
                and isinstance(loop.iter, ast.Attribute)
                and loop.iter.attr == "__dataclass_fields__"
                and isinstance(loop.iter.value, ast.Name)
            ):
                dataclass_members[loop.target.id] = receiver(loop.iter.value)
        celery_builders = {
            alias.asname or alias.name
            for item in ast.walk(tree)
            if isinstance(item, ast.ImportFrom) and item.module == "ai_workshop.worker"
            for alias in item.names
            if alias.name == "create_celery"
        }
        celery_apps = {
            item.targets[0].id
            for item in ast.walk(tree)
            if isinstance(item, ast.Assign)
            and len(item.targets) == 1
            and isinstance(item.targets[0], ast.Name)
            and isinstance(item.value, ast.Call)
            and isinstance(item.value.func, ast.Name)
            and item.value.func.id in celery_builders
        }
        celery_apps |= {
            alias.asname or alias.name
            for item in ast.walk(tree)
            if isinstance(item, ast.ImportFrom) and item.module == "ai_workshop.worker"
            for alias in item.names
            if alias.name == "celery_app"
        }
        inspectors = {
            item.targets[0].id
            for item in ast.walk(tree)
            if isinstance(item, ast.Assign)
            and len(item.targets) == 1
            and isinstance(item.targets[0], ast.Name)
            and isinstance(item.value, ast.Call)
            and isinstance(item.value.func, ast.Attribute)
            and item.value.func.attr == "inspect"
            and isinstance(item.value.func.value, ast.Attribute)
            and item.value.func.value.attr == "control"
            and isinstance(item.value.func.value.value, ast.Name)
            and item.value.func.value.value.id in celery_apps
        }
        for loop in ast.walk(tree):
            if (
                isinstance(loop, ast.For)
                and isinstance(loop.target, ast.Name)
                and isinstance(loop.iter, (ast.List, ast.Tuple))
                and all(
                    isinstance(value, ast.Constant) and type(value.value) is str
                    for value in loop.iter.elts
                )
                and not any(
                    isinstance(value, ast.Name)
                    and isinstance(value.ctx, ast.Store)
                    and value.id == loop.target.id
                    for statement in loop.body
                    for value in ast.walk(statement)
                )
            ):
                members = {
                    str(value.value) for value in loop.iter.elts if isinstance(value, ast.Constant)
                }
                if members <= {"active", "reserved", "scheduled"}:
                    inspected_members[loop.target.id] = members
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                if (
                    node.module == "subprocess"
                    and any(
                        item.name
                        not in {"CompletedProcess", "TimeoutExpired", "CalledProcessError"}
                        for item in node.names
                    )
                    or node.module == "os"
                    and any(
                        item.name.startswith(("spawn", "exec"))
                        or item.name in {"system", "popen", "startfile", "kill"}
                        for item in node.names
                    )
                ):
                    raise _fail("history_control_grammar_unknown")
                if any(item.name in dangerous or item.name in {"run", "*"} for item in node.names):
                    raise _fail("history_control_grammar_unknown")
                allowed = node.module.split(".")[0] in pure_prefixes
                allowed |= node.module in {
                    "ai_workshop.config",
                    "ai_workshop.shared.db",
                    "ai_workshop.shared.asyncio_policy",
                    "ai_workshop.labs.rag.indexing.alias_models",
                }
                allowed |= node.module == "ai_workshop.labs.rag.domains.repository" and all(
                    item.name
                    in {"SqlAlchemyDomainRepository", "SqlAlchemyDomainConfigurationProvider"}
                    for item in node.names
                )
                allowed |= node.module == "ai_workshop.labs.rag.domains.service" and all(
                    item.name == "DomainService" for item in node.names
                )
                allowed |= (
                    node.module == "ai_workshop.labs.rag.generation.codex_composition"
                    and all(
                        item.name in {"codex_services", "codex_registry"} for item in node.names
                    )
                )
                allowed |= (
                    node.module == "ai_workshop.labs.rag.generation.codex_runner_registry"
                    and all(item.name == "CodexRunnerReferenceError" for item in node.names)
                )
                allowed |= (
                    node.module == "ai_workshop.labs.rag.indexing.alias_recovery_cli"
                    and all(item.name == "load_original_settings" for item in node.names)
                )
                allowed |= node.module == "dotenv" and all(
                    item.name in {"dotenv_values", "load_dotenv"} for item in node.names
                )
                allowed |= node.module == "ai_workshop.worker" and all(
                    item.name in {"create_celery", "celery_app"} for item in node.names
                )
                allowed |= node.module == "urllib.parse" and all(
                    item.name == "urlsplit" for item in node.names
                )
                if not allowed:
                    raise _fail("history_control_grammar_unknown")
            if isinstance(node, ast.Import) and any(
                item.name.split(".")[0] not in pure_prefixes for item in node.names
            ):
                raise _fail("history_control_grammar_unknown")
            if (
                isinstance(node, ast.Attribute)
                and node.attr in dangerous
                and id(node) not in sql_attributes
            ):
                raise _fail("history_control_grammar_unknown")
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute):
                if id(node.func) in sql_attributes:
                    continue
                if isinstance(node.func.value, ast.Name) and (
                    node.func.value.id in subprocess_names
                    and node.func.attr
                    not in {"CompletedProcess", "TimeoutExpired", "CalledProcessError"}
                    or node.func.value.id in os_names
                    and (
                        node.func.attr.startswith(("spawn", "exec"))
                        or node.func.attr in {"system", "popen", "startfile", "kill"}
                    )
                ):
                    raise _fail("history_control_grammar_unknown")
                if node.func.attr in dangerous or (
                    node.func.attr == "run"
                    and not (
                        isinstance(node.func.value, ast.Name) and node.func.value.id == "asyncio"
                    )
                ):
                    raise _fail("history_control_grammar_unknown")
            elif isinstance(node.func, ast.Name) and node.func.id in dangerous:
                if (
                    node.func.id == "getattr"
                    and len(node.args) in {2, 3}
                    and isinstance(node.args[0], (ast.Name, ast.Attribute))
                    and isinstance(node.args[1], ast.Name)
                    and (
                        dataclass_members.get(node.args[1].id) == receiver(node.args[0])
                        or dataclass_members.get(node.args[1].id) in binding_receivers
                        and isinstance(node.args[0], ast.Attribute)
                        and node.args[0].attr == "binding"
                        and isinstance(node.args[0].value, ast.Name)
                        and node.args[0].value.id in stored_binding_owners
                    )
                    and not any(
                        isinstance(call, ast.Call) and call.func is node for call in ast.walk(tree)
                    )
                    and not any(
                        isinstance(statement, ast.Assign)
                        and statement.value is node
                        and any(
                            isinstance(target, ast.Name)
                            and any(
                                isinstance(call, ast.Call)
                                and isinstance(call.func, ast.Name)
                                and call.func.id == target.id
                                for call in ast.walk(tree)
                            )
                            for target in statement.targets
                        )
                        for statement in ast.walk(tree)
                    )
                ):
                    continue
                if (
                    node.func.id == "getattr"
                    and len(node.args) in {2, 3}
                    and isinstance(node.args[1], ast.Name)
                    and node.args[1].id in inspected_members
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id in inspectors
                ):
                    continue
                if (
                    node.func.id == "getattr"
                    and len(node.args) in {2, 3}
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value
                    in {
                        "worker_pool",
                        "task_always_eager",
                        "broker_url",
                        "result_backend",
                        "value",
                        "safe_error_code",
                        "code",
                        "name",
                        "readiness",
                    }
                ):
                    continue
                raise _fail("history_control_grammar_unknown")
        return "static_metadata"
    if re.search(
        r"stop-process|start-process|\.execute\(|nativecommandexecutor|subprocess\.(?:run|popen)"
        r"|\bpython(?:\.exe)?\b",
        lowered,
    ):
        raise _fail("history_control_grammar_unknown")
    return "static_metadata"


def _parts(value: Any) -> list[dict[str, Any]]:
    """Recognize wrapper results only, never scan stdout for a success marker."""
    results: list[dict[str, Any]] = []
    for text in _texts(value):
        try:
            obj = _json(text)
        except (ValueError, TypeError):
            obj = None
        if type(obj) is dict and ("exit_code" in obj or "session_id" in obj):
            results.append(obj)
        elif type(obj) is dict and set(obj) >= {"status", "value"} and obj["status"] == "fulfilled":
            nested = obj["value"]
            if type(nested) is dict and ("exit_code" in nested or "session_id" in nested):
                results.append(nested)
        elif type(obj) is list:
            for nested in obj:
                if type(nested) is dict and ("exit_code" in nested or "session_id" in nested):
                    results.append(nested)
        else:
            match = re.match(
                r"(?s)\s*(?:Chunk ID: [A-Za-z0-9_-]+\r?\n)?"
                r"(?:Wall time: [0-9.]+(?: seconds)?\r?\n)?"
                r"(?:Process exited with code|Exit code:)\s*(-?\d+)\s*\r?\n"
                r"(?:Final output:|Output:)\s*\r?\n(.*)\Z",
                text,
            )
            if match:
                results.append({"exit_code": int(match.group(1)), "output": match.group(2)})
    return results


def _required_shell_indices(value: object, shell_count: int | None = None) -> tuple[int, ...]:
    if (
        type(value) is not tuple
        or not value
        or any(type(index) is not int or index < 0 for index in value)
        or len(set(value)) != len(value)
        or shell_count is not None
        and any(index >= shell_count for index in value)
    ):
        raise _fail("history_batch_ambiguous")
    return cast(tuple[int, ...], value)


def _sequential_shell_emissions(script: str) -> int:
    """Whole literal exec/text source order, not tool-call discovery or execution."""
    if len(script.encode("utf-8")) > 1024 * 1024:
        raise _fail("history_result_linkage_invalid")
    cursor = _BatchSourceCursor(_tokens(script))
    count = 0
    try:
        while cursor.position < len(cursor.tokens):
            cursor.take("text", "(", "await", "tools", ".", "exec_command", "(", "{")
            keys: set[str] = set()
            while True:
                kind, key = cursor.tokens[cursor.position]
                if kind not in {"code", "string"} or key in keys:
                    raise _fail("history_result_linkage_invalid")
                keys.add(key)
                cursor.key(key)
                if key in {"cmd", "workdir", "justification"}:
                    cursor.literal()
                elif key == "sandbox_permissions":
                    if cursor.literal() not in {"use_default", "require_escalated"}:
                        raise _fail("history_result_linkage_invalid")
                elif key in {"yield_time_ms", "max_output_tokens"}:
                    cursor.number()
                elif key in {"login", "tty"}:
                    if cursor.tokens[cursor.position] not in {("code", "true"), ("code", "false")}:
                        raise _fail("history_result_linkage_invalid")
                    cursor.position += 1
                else:
                    raise _fail("history_result_linkage_invalid")
                if cursor.tokens[cursor.position] == ("code", "}"):
                    break
                cursor.take(",")
            if "cmd" not in keys:
                raise _fail("history_result_linkage_invalid")
            cursor.take("}", ")", ")", ";")
            count += 1
            if count > 64:
                raise _fail("history_batch_ambiguous")
    except (IndexError, TypeError, SyntaxError):
        raise _fail("history_result_linkage_invalid") from None
    if not count:
        raise _fail("history_batch_ambiguous")
    return count


def _scoped_physical_parts(physical_outputs: list[Any]) -> list[dict[str, Any]]:
    """Retain every sequential emission; never compact an unknown physical slot."""
    result: list[dict[str, Any]] = []
    size = 0
    for physical in physical_outputs:
        if type(physical) is str:
            texts = [physical]
        elif type(physical) is list and len(physical) <= 512:
            if any(
                type(item) is not dict
                or set(item) != {"type", "text"}
                or item.get("type") not in {"text", "input_text", "output_text"}
                or type(item.get("text")) is not str
                for item in physical
            ):
                raise _fail("history_result_linkage_invalid")
            texts = [item["text"] for item in physical]
        else:
            raise _fail("history_result_linkage_invalid")
        for ordinal, text in enumerate(texts):
            size += len(text.encode("utf-8"))
            if size > 16 * 1024 * 1024:
                raise _fail("history_result_linkage_invalid")
            if text.startswith("Script "):
                if ordinal != 0:
                    raise _fail("history_result_linkage_invalid")
                state, _ = (
                    ("running", None)
                    if re.fullmatch(r"Script running with cell ID [A-Za-z0-9_-]{1,128}", text)
                    else _outer_header(text)
                )
                if state not in {"running", "completed"}:
                    raise _fail("history_result_linkage_invalid")
                continue
            try:
                obj = _json(text)
            except (ValueError, TypeError):
                raise _fail("history_result_linkage_invalid") from None
            if (
                type(obj) is not dict
                or type(obj.get("output")) is not str
                or not {"output"}
                <= set(obj)
                <= {
                    "output",
                    "exit_code",
                    "session_id",
                    "chunk_id",
                    "wall_time_seconds",
                    "original_token_count",
                }
            ):
                raise _fail("history_result_linkage_invalid")
            code = obj.get("exit_code")
            if code is not None and type(code) is not int:
                raise _fail("history_result_linkage_invalid")
            if "session_id" in obj and (
                type(obj["session_id"]) is not int or not 0 < obj["session_id"] < 2**31
            ):
                raise _fail("history_result_linkage_invalid")
            if code is None and "session_id" not in obj:
                raise _fail("history_terminal_missing")
            if "chunk_id" in obj and (
                type(obj["chunk_id"]) is not str
                or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", obj["chunk_id"]) is None
            ):
                raise _fail("history_result_linkage_invalid")
            if "wall_time_seconds" in obj and (
                type(obj["wall_time_seconds"]) not in {int, float}
                or not math.isfinite(obj["wall_time_seconds"])
                or obj["wall_time_seconds"] < 0
            ):
                raise _fail("history_result_linkage_invalid")
            if "original_token_count" in obj and (
                type(obj["original_token_count"]) is not int
                or not 0 <= obj["original_token_count"] < 2**31
            ):
                raise _fail("history_result_linkage_invalid")
            result.append(obj)
    return result


def _inspect_submission(command: str, project: str) -> tuple[str, str] | None:
    """Only an actually invoked, literal Docker inspect argv is admitted."""
    arguments: list[list[str]] = []
    powershell = re.sub(r"@(['\"])\r?\n.*?\r?\n\1@", "", command, flags=re.S)
    projection = re.search(
        r"(?m)^\s*\$(\w+)\s*=\s*&\s*(['\"])([^\n'\"]*docker\.exe)\2"
        r"\s+inspect\s+([0-9a-f]{64})\s+2>\$null\s*\|\s*ConvertFrom-Json\s*$",
        powershell,
        re.I,
    )
    if projection is not None:
        variable, identifier = projection.group(1), projection.group(4)
        ref = re.escape("$" + variable)
        guard = (
            r"if\s*\(\s*\$LASTEXITCODE\s+-ne\s+0\s+-or\s+@\(\s*"
            + ref
            + r"\s*\)\.Count\s+-ne\s+1\s*\)\s*\{\s*throw\s+['\"][^\n'\"]+['\"]\s*\}"
        )
        fields = (
            r"\[PSCustomObject\]@\{\s*container_id\s*=\s*" + ref + r"\.Id\s*;\s*"
            r"running\s*=\s*" + ref + r"\.State\.Running\s*;\s*"
            r"started_at\s*=\s*" + ref + r"\.State\.StartedAt\s*;\s*"
            r"finished_at\s*=\s*" + ref + r"\.State\.FinishedAt\s*\}\s*"
            r"\|\s*ConvertTo-Json\s+-Compress"
        )
        if re.search(guard, powershell, re.I) and re.search(fields, powershell, re.I):
            return identifier, ""
    for match in re.finditer(
        r"(?m)^\s*(?:\$[A-Za-z_]\w*\s*=\s*)?&\s*"
        r"(['\"])([^\n'\"]*docker\.exe)\1([^\n]*)$",
        powershell,
        re.I,
    ):
        tail = match.group(3)
        if any(symbol in tail for symbol in (";", "$", "`", "|", "&")):
            continue
        if tail.strip().startswith("@(") and tail.strip().endswith(")"):
            try:
                values = ast.literal_eval("[" + tail.strip()[2:-1] + "]")
            except (ValueError, SyntaxError):
                continue
            if type(values) is list and all(type(value) is str for value in values):
                arguments.append([match.group(2), *values])
            continue
        tokens = re.findall(r"'([^']*)'|\"([^\"]*)\"|([^\s'\"]+)", tail)
        arguments.append([match.group(2), *[next(v for v in token if v) for token in tokens]])
    for match in re.finditer(
        r"@(['\"])\r?\n(.*?)\r?\n\1@\s*\|[^\n]*python(?:\.exe)?\b", command, re.S
    ):
        try:
            tree = ast.parse(match.group(2))
        except SyntaxError:
            raise _fail("history_command_grammar_unknown") from None
        literals: dict[str, str] = {}
        for statement in tree.body:
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                and isinstance(statement.value, ast.Constant)
                and type(statement.value.value) is str
            ):
                literals[statement.targets[0].id] = statement.value.value
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Call)
                or not isinstance(node.func, ast.Attribute)
                or not isinstance(node.func.value, ast.Name)
                or node.func.value.id != "subprocess"
                or node.func.attr not in {"run", "check_output"}
                or not node.args
                or not isinstance(node.args[0], (ast.List, ast.Tuple))
            ):
                continue
            argv = []
            for value in node.args[0].elts:
                if isinstance(value, ast.Constant) and type(value.value) is str:
                    argv.append(value.value)
                elif isinstance(value, ast.Name) and value.id in literals:
                    argv.append(literals[value.id])
                else:
                    argv = []
                    break
            if argv:
                arguments.append(argv)
    accepted = []
    for argv in arguments:
        if not argv or Path(argv[0]).name.lower() not in {"docker", "docker.exe"}:
            continue
        rest = argv[1:]
        if len(rest) >= 2 and rest[0] == "--context":
            rest = rest[2:]
        if rest and rest[0] == "container":
            rest = rest[1:]
        if len(rest) == 4 and rest[0] == "inspect" and rest[2] in {"--format", "-f"}:
            rest = ["inspect", rest[2], rest[3], rest[1]]
        if (
            len(rest) == 4
            and rest[0] == "inspect"
            and rest[1] in {"--format", "-f"}
            and (
                rest[3] == project + "-elasticsearch-1"
                or re.fullmatch(r"[0-9a-f]{64}", rest[3]) is not None
            )
            and all(
                marker in rest[2]
                for marker in (".Id", ".State.Running", ".State.StartedAt", ".State.FinishedAt")
            )
        ):
            accepted.append((rest[3], rest[2]))
    return accepted[0] if len(accepted) == 1 else None


class OriginalHistoricalReceiptReader:
    def __init__(
        self, root: str | Path, protection: ProtectionPort, files: PrivateFilePort
    ) -> None:
        self.root = Path(root)
        self.protection, self.files = protection, files
        self._issued: dict[int, tuple[DerivedHistoricalFacts, dict[str, Any], bytes]] = {}

    def _recorded_python_category(
        self, command: str, rows: list[dict[str, Any]], call_id: str, *, source_only: bool = False
    ) -> str:
        match = re.search(
            r"python(?:\.exe)?[\"']?\s+(?:-(?:B|I)\s+)*(?:\"([^\"\n]+\.py)\"|'([^'\n]+\.py)'|([^\s\"']+\.py))",
            command,
            re.I,
        )
        if match is None:
            raise _fail("history_control_grammar_unknown")
        target = Path(next(value for value in match.groups() if value))
        if not target.is_absolute():
            target = self.root / target
        target = target.resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise _fail("history_helper_not_original")
        position = next(
            (
                i
                for i, r in enumerate(rows)
                if r.get("payload", {}).get("call_id") == call_id
                and r.get("payload", {}).get("type") == "custom_tool_call"
            ),
            None,
        )
        if position is None:
            raise _fail("history_call_linkage_invalid")
        body: list[str] | None = None
        written: dict[str, str] = {}
        for row in rows[:position]:
            payload = row.get("payload", {})
            if payload.get("type") != "custom_tool_call" or payload.get("name") not in {
                "exec",
                "functions.exec",
            }:
                continue
            patches = _patches(payload.get("input", ""))
            matching = []
            for patch in patches:
                for chunk in re.split(
                    r"(?m)^(?=\*\*\* (?:Update File:|Add File:|Delete File:|End Patch))", patch
                ):
                    header = re.match(r"\*\*\* (Add|Update|Delete) File: ([^\n]+)\r?\n", chunk)
                    if header is None:
                        continue
                    path = Path(header.group(2).rstrip("\r"))
                    if not path.is_absolute():
                        path = self.root / path
                    if path.resolve() == target:
                        matching.append((header.group(1), chunk.splitlines()[1:]))
            if not matching:
                continue
            write_id = payload.get("call_id")
            if type(write_id) is not str:
                raise _fail("history_helper_write_unverified")
            serialized = json.dumps(payload, sort_keys=True)
            if write_id in written:
                if written[write_id] != serialized:
                    raise _fail("history_helper_source_ambiguous")
                continue
            written[write_id] = serialized
            outputs = {
                json.dumps(r.get("payload", {}), sort_keys=True): r.get("payload", {})
                for r in rows[:position]
                if r.get("payload", {}).get("call_id") == payload.get("call_id")
                and r.get("payload", {}).get("type") == "custom_tool_call_output"
            }
            if len(outputs) != 1:
                raise _fail("history_helper_write_unverified")
            texts = _texts(next(iter(outputs.values())).get("output"))
            tokens = _tokens(payload.get("input", ""))
            return_slots = [
                tokens[i + 2][1]
                for i in range(len(tokens) - 3)
                if tokens[i : i + 2] == [("code", "tools"), ("code", ".")]
                and tokens[i + 2]
                in {("code", "apply_patch"), ("code", "exec_command"), ("code", "write_stdin")}
                and tokens[i + 3] == ("code", "(")
            ]
            if (
                len(texts) != len(return_slots) + 1
                or not texts[0].startswith("Script completed")
                or return_slots.count("apply_patch") != len(patches)
                or any(
                    texts[i + 1].strip() != "{}"
                    for i, slot in enumerate(return_slots)
                    if slot == "apply_patch"
                )
            ):
                raise _fail("history_helper_write_unverified")
            for action, lines in matching:
                if action == "Add":
                    if body is not None or any(line and not line.startswith("+") for line in lines):
                        raise _fail("history_helper_source_ambiguous")
                    body = [line[1:] for line in lines if line.startswith("+")]
                elif action == "Delete":
                    body = None
                elif body is None:
                    raise _fail("history_helper_source_incomplete")
                else:
                    hunks: list[tuple[str | None, list[str]]] = []
                    anchor: str | None = None
                    parts: list[str] = []
                    for line in lines:
                        if line == "@@" or line.startswith("@@ "):
                            if parts:
                                hunks.append((anchor, parts))
                            anchor, parts = line[3:] if line.startswith("@@ ") else None, []
                        else:
                            parts.append(line)
                    if parts:
                        hunks.append((anchor, parts))
                    cursor = 0
                    for anchor, parts in hunks:
                        if anchor is not None:
                            positions = [i for i in range(cursor, len(body)) if body[i] == anchor]
                            if len(positions) != 1:
                                raise _fail("history_helper_source_ambiguous")
                            cursor = positions[0] + 1
                        at_end = bool(parts and parts[-1] == "*** End of File")
                        if at_end:
                            parts = parts[:-1]
                        if any(not line or line[0] not in " +-" for line in parts):
                            raise _fail("history_helper_source_ambiguous")
                        old = [line[1:] for line in parts if line[0] in " -"]
                        new = [line[1:] for line in parts if line[0] in " +"]
                        offsets = [
                            i
                            for i in range(cursor, len(body) - len(old) + 1)
                            if body[i : i + len(old)] == old
                            and (not at_end or i + len(old) == len(body))
                        ]
                        if len(offsets) != 1:
                            raise _fail("history_helper_source_ambiguous")
                        # Without a pinned historical tool seek contract,
                        # multiple exact spans remain unverified, not guessed.
                        offset = offsets[0]
                        body[offset : offset + len(old)] = new
                        cursor = offset + len(new)
        if body is None:
            raise _fail("history_helper_source_missing")
        if source_only:
            return "\n".join(body)
        tail = command[match.end() :].strip()
        argv = [
            next(v for v in token if v)
            for token in re.findall(r"'([^']*)'|\"([^\"]*)\"|([^\s'\"]+)", tail)
        ]
        tree = _literal_helper_dispatch("\n".join(body), argv)
        return _category("@'\n" + ast.unparse(tree) + "\n'@ | python.exe -")

    def _recipe(self) -> dict[str, Any]:
        path = self.root / ".local-data/access-epoch/private/history-recipe.dpapi"
        sealed = self.files.read(str(path))
        if type(sealed) is not bytes or len(sealed) > 16 * 1024 * 1024:
            raise _fail("history_recipe_missing")
        raw = self.protection.unprotect(sealed)
        if type(raw) is not bytes or len(raw) > 16 * 1024 * 1024:
            raise _fail()
        obj = _json(raw)
        if (
            type(obj) is not dict
            or set(obj) != {"schema_version", "scanner_version", "sources", "calls"}
            or type(obj["schema_version"]) is not int
            or obj["schema_version"] != 1
            or type(obj["scanner_version"]) is not int
            or obj["scanner_version"] != 1
        ):
            raise _fail()
        if (
            type(obj["sources"]) is not list
            or not 1 <= len(obj["sources"]) <= 64
            or type(obj["calls"]) is not list
            or not 1 <= len(obj["calls"]) <= 10000
        ):
            raise _fail()
        return cast(dict[str, Any], obj)

    def _sources(self, recipe: dict[str, Any]) -> list[list[dict[str, Any]]]:
        base = (Path.home() / ".codex/sessions").resolve()
        result: list[list[dict[str, Any]]] = []
        seen: set[Path] = set()
        total = 0
        for item in recipe["sources"]:
            if (
                type(item) is not dict
                or set(item)
                not in (
                    {"locator", "prefix_bytes", "prefix_sha256"},
                    {"locator", "prefix_bytes", "prefix_sha256", "parent_spawn", "purpose"},
                )
                or ("parent_spawn" in item and item.get("purpose") != "historical_source_writes")
                or type(item["locator"]) is not str
                or type(item["prefix_bytes"]) is not int
                or not 1 <= item["prefix_bytes"] <= 512 * 1024 * 1024
                or type(item["prefix_sha256"]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", item["prefix_sha256"]) is None
            ):
                raise _fail()
            path = Path(item["locator"]).resolve()
            if (
                not path.is_relative_to(base)
                or path in seen
                or path.suffix != ".jsonl"
                or not path.name.startswith("rollout-")
            ):
                raise _fail("history_source_not_original")
            seen.add(path)
            total += item["prefix_bytes"]
            if total > 1024 * 1024 * 1024:
                raise _fail()
            digest = hashlib.sha256()
            remaining = item["prefix_bytes"]
            rows: list[dict[str, Any]] = []
            write_ids: set[str] = set()
            cutoff = self._source_cutoff(recipe, result) if "parent_spawn" in item else None
            with path.open("rb") as stream:
                while remaining:
                    raw = stream.readline(remaining)
                    if not raw:
                        raise _fail("history_source_changed")
                    remaining -= len(raw)
                    digest.update(raw)
                    if not raw.endswith(b"\n"):
                        raise _fail("history_prefix_incomplete")
                    try:
                        row = _json(raw)
                    except ValueError:
                        raise _fail("history_source_changed") from None
                    if type(row) is not dict:
                        raise _fail()
                    if not rows and "parent_spawn" in item:
                        # Admission is verified before reading any child body.
                        self._child_link(item["parent_spawn"], row, raw, result)
                    if cutoff is not None and row.get("type") != "session_meta":
                        try:
                            stamp = _timestamp(row.get("timestamp"))
                            if stamp.tzinfo is None or stamp > cutoff:
                                raise _fail("history_child_cutoff_invalid")
                        except (ValueError, TypeError):
                            raise _fail("history_child_cutoff_invalid") from None
                    payload = row.get("payload", {})
                    if cutoff is not None and row.get("type") != "session_meta":
                        keep = False
                        if type(payload) is dict:
                            if payload.get("type") in {"custom_tool_call", "function_call"}:
                                script = payload.get("input", payload.get("arguments", ""))
                                if (
                                    payload.get("name") in {"exec", "functions.exec"}
                                    and type(script) is str
                                    and _patches(script)
                                ):
                                    keep = True
                                    if type(payload.get("call_id")) is not str:
                                        raise _fail("history_child_linkage_invalid")
                                    write_ids.add(payload["call_id"])
                            elif payload.get("type") in {
                                "custom_tool_call_output",
                                "function_call_output",
                            }:
                                keep = payload.get("call_id") in write_ids
                        rows.append(row if keep else {})
                        continue
                    # Preserve exact line indices for private selectors without
                    # retaining unrelated conversation/source bodies in RAM.
                    rows.append(
                        row
                        if row.get("type") == "session_meta"
                        or (
                            type(payload) is dict
                            and payload.get("type")
                            in {
                                "custom_tool_call",
                                "custom_tool_call_output",
                                "function_call",
                                "function_call_output",
                            }
                        )
                        else {}
                    )
            if digest.hexdigest() != item["prefix_sha256"]:
                raise _fail("history_source_changed")
            # The provisioned LF prefix is the reviewed finite inventory.
            # Appended future records are outside this receipt's coverage;
            # never turn them into a promise about every later daemon action.
            result.append(rows)
        return result

    def _source_cutoff(
        self, recipe: dict[str, Any], previous: list[list[dict[str, Any]]]
    ) -> datetime:
        times = []
        for entry in recipe["calls"]:
            if type(entry) is not dict or type(entry.get("source")) is not int:
                raise _fail()
            if not 0 <= entry["source"] < len(previous):
                raise _fail("history_child_scope_invalid")
            if "parent_spawn" in recipe["sources"][entry["source"]]:
                raise _fail("history_child_scope_invalid")
            for row in previous[entry["source"]]:
                payload = row.get("payload", {})
                if (
                    payload.get("call_id") != entry.get("call_id")
                    or payload.get("type") != "custom_tool_call"
                ):
                    continue
                if any(
                    re.search(r"\s-m\s+pytest(?:\s|$)", shell)
                    for shell in _shells(payload.get("input", ""))
                ):
                    try:
                        stamp = _timestamp(row.get("timestamp"))
                        if stamp.tzinfo is None:
                            raise _fail()
                        times.append(stamp)
                    except (ValueError, TypeError):
                        raise _fail("history_child_cutoff_invalid") from None
        if not times:
            raise _fail("history_child_cutoff_invalid")
        return min(times)

    def _child_link(
        self,
        link: Any,
        header: dict[str, Any],
        raw: bytes,
        previous: list[list[dict[str, Any]]],
    ) -> None:
        invalid = "history_child_linkage_invalid"
        if (
            type(link) is not dict
            or set(link) != {"source", "call_id", "first_line_sha256"}
            or type(link["source"]) is not int
            or not 0 <= link["source"] < len(previous)
            or type(link["call_id"]) is not str
            or not link["call_id"]
            or link["first_line_sha256"] != _sha(raw)
            or header.get("type") != "session_meta"
        ):
            raise _fail(invalid)
        rows = previous[link["source"]]
        if not rows or rows[0].get("type") != "session_meta":
            raise _fail(invalid)
        parent = rows[0].get("payload", {})
        child = header.get("payload", {})
        if type(parent) is not dict or type(child) is not dict:
            raise _fail(invalid)
        nested = child.get("source", {})
        if type(nested) is not dict or type(nested.get("subagent")) is not dict:
            raise _fail(invalid)
        spawn = nested["subagent"].get("thread_spawn", {})
        if type(spawn) is not dict or spawn.get("parent_thread_id") != parent.get("id"):
            raise _fail(invalid)
        calls = {
            json.dumps(row, sort_keys=True): row
            for row in rows
            if row.get("payload", {}).get("call_id") == link["call_id"]
            and row.get("payload", {}).get("type") in {"function_call", "custom_tool_call"}
        }
        returns = {
            json.dumps(row, sort_keys=True): row
            for row in rows
            if row.get("payload", {}).get("call_id") == link["call_id"]
            and row.get("payload", {}).get("type")
            in {"function_call_output", "custom_tool_call_output"}
        }
        if len(calls) != 1 or len(returns) != 1:
            raise _fail(invalid)
        call, returned = next(iter(calls.values())), next(iter(returns.values()))
        payload = call["payload"]
        if payload.get("name") not in {"collaboration.spawn_agent", "spawn_agent"}:
            raise _fail(invalid)
        try:
            args = _json(payload.get("arguments", payload.get("input", "")))
            texts = _texts(returned["payload"].get("output"))
            if len(texts) != 1:
                raise _fail(invalid)
            result = _json(texts[0])
            timestamps = [
                _timestamp(value)
                for value in (
                    call.get("timestamp"),
                    child.get("timestamp"),
                    returned.get("timestamp"),
                )
            ]
            if any(value.tzinfo is None for value in timestamps):
                raise _fail(invalid)
            cwd = child.get("cwd")
            if type(cwd) is not str or Path(cwd).resolve() != self.root.resolve():
                raise _fail(invalid)
        except (ValueError, TypeError, OSError):
            raise _fail(invalid) from None
        canonical = spawn.get("agent_path")
        if (
            type(args) is not dict
            or type(result) is not dict
            or type(canonical) is not str
            or result.get("task_name") != canonical
            or canonical.rsplit("/", 1)[-1] != args.get("task_name")
            or not timestamps[0] <= timestamps[1] <= timestamps[2]
        ):
            raise _fail(invalid)

    def _chain(
        self,
        call_id: str,
        rows: list[dict[str, Any]],
        visited: frozenset[str] = frozenset(),
        *,
        required_shell_indices: tuple[int, ...] | None = None,
    ) -> list[dict[str, Any]]:
        required = (
            _required_shell_indices(required_shell_indices)
            if required_shell_indices is not None
            else None
        )
        scoped_script: str | None = None
        scoped_shell_count = 0
        if required is not None:
            producers = {
                json.dumps(row["payload"], sort_keys=True): row["payload"]
                for row in rows
                if row.get("payload", {}).get("call_id") == call_id
                and row.get("payload", {}).get("type") in {"custom_tool_call", "function_call"}
            }
            if len(producers) != 1:
                raise _fail("history_call_linkage_invalid")
            producer = next(iter(producers.values()))
            scoped_script = producer.get("input", producer.get("arguments"))
            if (
                producer.get("name") not in {"exec", "functions.exec"}
                or type(scoped_script) is not str
            ):
                raise _fail("history_command_grammar_unknown")
            scoped_shell_count = len(_shells(scoped_script))
            _required_shell_indices(required, scoped_shell_count)
        if call_id in visited or len(visited) >= 64:
            raise _fail("history_result_linkage_invalid")
        visited = visited | {call_id}
        structured_tail_script = None
        for row in rows:
            payload = row.get("payload", {})
            if (
                payload.get("call_id") != call_id
                or payload.get("type") not in {"custom_tool_call", "function_call"}
                or payload.get("name") not in {"exec", "functions.exec"}
            ):
                continue
            script = payload.get("input", payload.get("arguments", ""))
            if type(script) is str:
                invocations = _expanded_invocations(script)
                if any(kind == "stdout_only" for _, _, kind in invocations):
                    # A completed exec wrapper or forged stdout cannot settle it.
                    raise _fail("history_terminal_missing")
                if any(kind == "structured_tail" for _, _, kind in invocations):
                    structured_tail_script = script
        output_positions = [
            index
            for index, row in enumerate(rows)
            if row.get("payload", {}).get("call_id") == call_id
            and row.get("payload", {}).get("type")
            in {"custom_tool_call_output", "function_call_output"}
        ]
        if not output_positions:
            raise _fail("history_terminal_missing")
        earliest_output = min(output_positions)
        outputs = [
            r.get("payload", {})
            for r in rows
            if r.get("payload", {}).get("call_id") == call_id
            and r.get("payload", {}).get("type")
            in {"custom_tool_call_output", "function_call_output"}
        ]
        if not outputs:
            raise _fail("history_terminal_missing")
        unique: dict[str, dict[str, Any]] = {}
        for payload in outputs:
            unique[json.dumps(payload, sort_keys=True)] = payload
        if required is not None and len(unique) != 1:
            raise _fail("history_result_linkage_invalid")
        physical_outputs = [payload.get("output") for payload in unique.values()]
        parts = [part for payload in unique.values() for part in _parts(payload.get("output"))]
        cells = {
            match.group(1)
            for payload in unique.values()
            for text in _texts(payload.get("output"))
            if (match := re.match(r"Script running with cell ID ([A-Za-z0-9_-]+)\b", text))
        }
        if len(cells) > 1:
            raise _fail("history_result_linkage_invalid")
        if cells:
            cell = next(iter(cells))
            cell_completed = False
            continuation_count = 0
            for row in rows[earliest_output + 1 :]:
                payload = row.get("payload", {})
                if payload.get("name") not in {"wait", "functions.wait"}:
                    continue
                try:
                    args = _json(payload.get("input", payload.get("arguments", "")))
                except (ValueError, TypeError):
                    raise _fail("history_result_linkage_invalid") from None
                if type(args) is not dict or args.get("cell_id") != cell:
                    continue
                continuation_count += 1
                if continuation_count > 64 or cell_completed or args.get("terminate") is True:
                    raise _fail("history_result_linkage_invalid")
                waited = [
                    output.get("payload", {})
                    for output in rows
                    if output.get("payload", {}).get("call_id") == payload.get("call_id")
                    and output.get("payload", {}).get("type")
                    in {"custom_tool_call_output", "function_call_output"}
                ]
                deduplicated = {json.dumps(value, sort_keys=True): value for value in waited}
                if len(deduplicated) != 1:
                    raise _fail("history_terminal_missing")
                texts = _texts(next(iter(deduplicated.values())).get("output"))
                cell_completed = any(text.startswith("Script completed") for text in texts)
                if not cell_completed and not any(
                    re.match(r"Script running with cell ID " + re.escape(cell) + r"\b", text)
                    for text in texts
                ):
                    raise _fail("history_terminal_missing")
                waited_output = next(iter(deduplicated.values())).get("output")
                physical_outputs.append(waited_output)
                parts.extend(_parts(waited_output))
                if cell_completed:
                    break
            if not cell_completed:
                raise _fail("history_terminal_missing")
        if structured_tail_script is not None:
            physical: list[Any] = []
            for value in physical_outputs:
                if type(value) is not list:
                    raise _fail("history_result_linkage_invalid")
                physical.extend(value)
            bound = _poll_results(structured_tail_script, physical)
            # Only the exec tail is a selected shell. Poll emissions retain their
            # slot/session binding but do not acquire a new termination duty.
            tail = bound[-1]
            if tail is None:
                raise _fail("history_terminal_missing")
            parts = [tail]
        if required is not None:
            if len(parts) != scoped_shell_count:
                raise _fail("history_batch_ambiguous")
            if len(required) < scoped_shell_count:
                assert scoped_script is not None
                if _sequential_shell_emissions(scoped_script) != scoped_shell_count:
                    raise _fail("history_batch_ambiguous")
                complete_parts = _scoped_physical_parts(physical_outputs)
                if len(complete_parts) != scoped_shell_count or complete_parts != parts:
                    raise _fail("history_batch_ambiguous")
                parts = complete_parts
        # A yielded shell's terminal is tied to its exact numeric session.
        for index, part in enumerate(parts):
            if required is not None and index not in required:
                continue  # Unjudged original part remains unchanged, never settled.
            if part.get("exit_code") is not None:
                if required is not None and type(part["exit_code"]) is not int:
                    raise _fail("history_result_linkage_invalid")
                continue
            session = part.get("session_id")
            if type(session) is not int or required is not None and not 0 < session < 2**31:
                raise _fail("history_terminal_missing")
            continuations = []
            poll_ids: set[str] = set()
            for position in range(earliest_output + 1, len(rows)):
                row = rows[position]
                payload = row.get("payload", {})
                if payload.get("type") not in {"custom_tool_call", "function_call"} or payload.get(
                    "name"
                ) not in {"exec", "functions.exec"}:
                    continue
                text = payload.get("input", payload.get("arguments", ""))
                if type(text) is str and (
                    _definitely_unrelated_settled_poll(text, session)
                    or _definitely_unrelated_mixed_settled_poll(text, session)
                    or _definitely_unrelated_patched_settled_poll(text, session)
                    or _definitely_unrelated_pair_settled_poll(text, session)
                    or _definitely_unrelated_two_polls_settled_poll(text, session)
                    or _definitely_unrelated_batch_settled_poll(text, session)
                    or _definitely_unrelated_stored_poll(rows, position, session)
                ):
                    continue  # Source-only nonmembership; no output is certified.
                requested_sessions = _poll_sessions(text) if type(text) is str else []
                if (
                    payload.get("type") in {"custom_tool_call", "function_call"}
                    and type(text) is str
                    and session in requested_sessions
                ):
                    poll_id = payload.get("call_id")
                    if type(poll_id) is not str or poll_id in visited or poll_id in poll_ids:
                        continue
                    poll_ids.add(poll_id)
                    poll_outputs = {
                        json.dumps(output.get("payload", {}), sort_keys=True): output.get(
                            "payload", {}
                        )
                        for output in rows
                        if output.get("payload", {}).get("call_id") == poll_id
                        and output.get("payload", {}).get("type")
                        in {"custom_tool_call_output", "function_call_output"}
                    }
                    if len(poll_outputs) != 1:
                        raise _fail("history_terminal_missing")
                    values = _poll_results(text, next(iter(poll_outputs.values())).get("output"))
                    slots = _result_slots(text)
                    poll_positions = [i for i, name in enumerate(slots) if name == "write_stdin"]
                    if (
                        len(values) != len(slots)
                        or len(poll_positions) != len(requested_sessions)
                        or requested_sessions.count(session) != 1
                    ):
                        raise _fail("history_result_linkage_invalid")
                    value = values[poll_positions[requested_sessions.index(session)]]
                    if value is None:
                        raise _fail("history_terminal_missing")
                    if value.get("exit_code") is not None:
                        if required is not None and type(value["exit_code"]) is not int:
                            raise _fail("history_result_linkage_invalid")
                        continuations.append(value)
                        break
                    if value.get("session_id") != session:
                        raise _fail("history_result_linkage_invalid")
            terminal = [value for value in continuations if value.get("exit_code") is not None]
            if len(terminal) != 1:
                raise _fail("history_terminal_missing")
            parts[index] = terminal[0]
        if not parts:
            raise _fail("history_result_linkage_invalid")
        return parts

    def _support(
        self, supports: Any, category: str, sources: list[list[dict[str, Any]]]
    ) -> tuple[str, str]:
        required = (
            "target_observation" if category == "original_docker" else "contemporaneous_stage"
        )
        if type(supports) is not list or not supports:
            raise _fail(
                "history_target_evidence_missing"
                if category == "original_docker"
                else "history_stage_evidence_missing"
            )
        stage_verified = False
        observed_identities: set[tuple[str, str]] = set()
        # Proof must be in recorded contemporaneous source, not today's code.
        for support in supports:
            if (
                type(support) is not dict
                or set(support) != {"source", "line", "payload_sha256", "kind"}
                or support["kind"] not in {required, "target_observation"}
                or type(support["source"]) is not int
                or type(support["line"]) is not int
                or not 0 <= support["source"] < len(sources)
                or not 1 <= support["line"] <= len(sources[support["source"]])
            ):
                raise _fail("history_support_invalid")
            try:
                row = sources[support["source"]][support["line"] - 1]
            except (IndexError, TypeError):
                raise _fail("history_support_invalid") from None
            raw = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
            if _sha(raw) != support["payload_sha256"]:
                raise _fail("history_support_invalid")
            if support["kind"] == "contemporaneous_stage":
                stage_verified |= self._recorded_stage(row, sources[support["source"]])
            else:
                observed_identities.add(self._recorded_inspect(row, sources[support["source"]]))
        if not observed_identities or len(observed_identities) != 1:
            raise _fail("history_target_evidence_missing")
        if category == "collector" and not stage_verified:
            raise _fail("history_stage_evidence_missing")
        return next(iter(observed_identities))

    def _recorded_stage(self, row: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
        payload = row.get("payload", {})
        script = payload.get("input", "")
        if payload.get("name") not in {"exec", "functions.exec"} or type(script) is not str:
            raise _fail("history_support_invalid")
        patches = _patches(script)
        # The awaited patch result has no shell exit code. Require exact exec
        # completion and one empty returned tool result per awaited patch.
        outputs = {
            json.dumps(value.get("payload", {}), sort_keys=True): value.get("payload", {})
            for value in rows
            if value.get("payload", {}).get("call_id") == payload.get("call_id")
            and value.get("payload", {}).get("type") == "custom_tool_call_output"
        }
        if len(outputs) != 1 or not patches:
            raise _fail("history_support_invalid")
        texts = _texts(next(iter(outputs.values())).get("output"))
        if (
            len(texts) != len(patches) + 1
            or re.fullmatch(
                r"Script completed\s*(?:Wall time:? [0-9.]+ seconds\s*)?(?:Output:\s*)?",
                texts[0],
            )
            is None
            or any(_json(text) != {} for text in texts[1:])
        ):
            raise _fail("history_support_invalid")
        target = self.root / "docs/worklogs/2026-09-30-rag-alias-recovery.md"
        supported = False
        for patch in patches:
            chunks = re.split(
                r"(?m)^(?=\*\*\* (?:Update File:|Add File:|Delete File:|End Patch))", patch
            )
            additions: list[str] = []
            for chunk in chunks:
                header = re.match(r"\*\*\* Update File: ([^\n]+)\r?\n", chunk)
                if header is None:
                    continue
                path = Path(header.group(1).rstrip("\r"))
                if not path.is_absolute():
                    path = self.root / path
                if path.resolve() == target.resolve():
                    additions.extend(
                        line[1:] for line in chunk.splitlines() if line.startswith("+")
                    )
            added = "\n".join(additions)
            # Closed historical refusal grammar: the recorded addition must
            # explicitly say native actions were not run, not just contain a
            # diagnostic code somewhere in unrelated source or deleted lines.
            cluster_refusal = (
                "cluster_node_changed" in added
                and "ephemeral" in added
                and "동일" in added
                and "거부" in added
                and "미실행" in added
                and "stop" in added.lower()
                and "revision" in added
            )
            pre_stop_refusal = (
                "Authenticode" in added
                and "matching_frozen_claim" in added
                and "not_run" in added
                and "stop" in added.lower()
                and "실행하지 않았다" in added
                and "단계" in added
                and "receipt" in added
                and "revision" in added
            )
            supported |= cluster_refusal or pre_stop_refusal
        if not supported:
            raise _fail("history_support_semantics_unverified")
        return True

    def _recorded_inspect(self, row: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[str, str]:
        payload = row.get("payload", {})
        call_id = payload.get("call_id")
        calls = [
            value.get("payload", {})
            for value in rows
            if value.get("payload", {}).get("call_id") == call_id
            and value.get("payload", {}).get("type") == "custom_tool_call"
        ]
        distinct = {json.dumps(value, sort_keys=True): value for value in calls}
        if len(distinct) != 1:
            raise _fail("history_support_invalid")
        shells = _shells(next(iter(distinct.values())).get("input", ""))
        results = self._chain(call_id, rows)
        if len(shells) != len(results):
            raise _fail("history_batch_ambiguous")
        observed = []
        for shell, result in zip(shells, results, strict=True):
            if result.get("exit_code") != 0 or "inspect" not in shell:
                continue
            # Do not accept a marker in stdout as proof an inspect was submitted.
            submission = _inspect_submission(shell, self.root.name)
            if submission is None:
                continue
            requested_target, template = submission
            output = result.get("output", "")
            if type(output) is not str:
                raise _fail("history_support_invalid")
            try:
                value = _json(output.strip().splitlines()[-1])
            except (ValueError, TypeError):
                value = None
            if (
                type(value) is dict
                and set(value) == {"container_id", "running", "started_at", "finished_at"}
                and value["running"] is True
            ):
                identifier, started = value["container_id"], value["started_at"]
            else:
                pattern = re.escape(template)
                captures = {
                    "{{.Id}}": r"(?P<identifier>[0-9a-f]{64})",
                    "{{.State.Running}}": "true",
                    "{{.State.StartedAt}}": r"(?P<started>[0-9T:.Z-]+)",
                    "{{.State.FinishedAt}}": r"[0-9T:.Z-]+",
                }
                for marker, capture in captures.items():
                    pattern = pattern.replace(re.escape(marker), capture)
                match = re.fullmatch(pattern, output.strip())
                if match is None:
                    continue
                identifier, started = match.group("identifier"), match.group("started")
            if (
                type(identifier) is not str
                or re.fullmatch(r"[0-9a-f]{64}", identifier) is None
                or type(started) is not str
                or re.fullmatch(r"\d{4}-\d\d-\d\dT[0-9:.]+Z", started) is None
            ):
                raise _fail("history_support_invalid")
            if re.fullmatch(r"[0-9a-f]{64}", requested_target) and requested_target != identifier:
                raise _fail("history_support_invalid")
            observed.append((identifier, started))
        if len(observed) != 1:
            raise _fail("history_target_evidence_missing")
        return observed[0]

    def read_original(self) -> DerivedHistoricalFacts:
        try:
            recipe = self._recipe()
            sources = self._sources(recipe)
            _require_cross_source_call_equivalence(sources)
            categories: Counter[str] = Counter()
            dispositions: Counter[str] = Counter()
            derived = []
            observed_containers: set[str] = set()
            submitted_starts = []
            unjudged_helpers = 0
            seen: set[tuple[str, int]] = set()
            for entry in recipe["calls"]:
                if (
                    type(entry) is not dict
                    or set(entry) != {"source", "call_id", "shell_indices", "supports"}
                    or type(entry["source"]) is not int
                    or type(entry["call_id"]) is not str
                    or type(entry["shell_indices"]) is not list
                    or not entry["shell_indices"]
                ):
                    raise _fail()
                if not 0 <= entry["source"] < len(sources):
                    raise _fail()
                rows = sources[entry["source"]]
                calls = [
                    r["payload"]
                    for r in rows
                    if r.get("payload", {}).get("call_id") == entry["call_id"]
                    and r["payload"].get("type") in {"custom_tool_call", "function_call"}
                ]
                distinct = {json.dumps(v, sort_keys=True): v for v in calls}
                if len(distinct) != 1:
                    raise _fail("history_call_linkage_invalid")
                call = next(iter(distinct.values()))
                if call.get("name") not in {"exec", "functions.exec", "exec_command"}:
                    raise _fail("history_command_grammar_unknown")
                script = call.get("input", call.get("arguments"))
                if type(script) is not str:
                    raise _fail()
                shells = _shells(script)
                required = _required_shell_indices(tuple(entry["shell_indices"]), len(shells))
                results = self._chain(entry["call_id"], rows, required_shell_indices=required)
                if len(results) != len(shells):
                    raise _fail("history_batch_ambiguous")
                for index in entry["shell_indices"]:
                    if type(index) is not int or not 0 <= index < len(shells):
                        raise _fail()
                    key = entry["call_id"], index
                    if key in seen:
                        continue
                    seen.add(key)
                    try:
                        category = _category(shells[index])
                    except HistoricalReceiptError:
                        category = self._recorded_python_category(
                            shells[index], rows, entry["call_id"]
                        )
                    code = results[index].get("exit_code")
                    if type(code) is not int:
                        raise _fail("history_terminal_missing")
                    if category in {"original_docker", "collector"}:
                        if (category == "original_docker" and code != 0) or (
                            category == "collector" and code != 1
                        ):
                            raise _fail("history_control_unsettled")
                        start_match = re.fullmatch(
                            r"\s*docker\s+start\s+([A-Za-z0-9_ -]+)\s*", shells[index]
                        )
                        known_targets = set(start_match.group(1).split()) if start_match else set()
                        if (
                            category == "original_docker"
                            and start_match is not None
                            and len(known_targets) == 3
                            and len(start_match.group(1).split()) == 3
                            and all(
                                target.startswith(self.root.name + "-") for target in known_targets
                            )
                        ):
                            returned = results[index].get("output", "").split()
                            if set(returned) != known_targets or len(returned) != 3:
                                raise _fail("history_target_evidence_missing")
                            submitted_times = {
                                row.get("timestamp")
                                for row in rows
                                if row.get("payload", {}).get("call_id") == entry["call_id"]
                                and row.get("payload", {}).get("type") == "custom_tool_call"
                            }
                            if len(submitted_times) != 1:
                                raise _fail("history_call_linkage_invalid")
                            submitted_at = next(iter(submitted_times))
                            if type(submitted_at) is not str:
                                raise _fail("history_call_linkage_invalid")
                            parsed = datetime.fromisoformat(submitted_at)
                            if parsed.utcoffset() != UTC.utcoffset(parsed):
                                raise _fail("history_call_linkage_invalid")
                            submitted_starts.append(
                                {
                                    "submitted_at": submitted_at,
                                    "target_names": sorted(known_targets),
                                    "client_terminal": True,
                                    "historical_daemon_receipt": "unrecorded",
                                }
                            )
                        else:
                            observed_containers.add(
                                self._support(entry["supports"], category, sources)[0]
                            )
                    if category == "application":
                        disposition = "application_terminal" if code == 0 else "application_failed"
                    elif category == "original_docker":
                        disposition = "original_terminal"
                    elif category == "collector":
                        disposition = "collector_refused"
                    else:
                        disposition = "non_control"
                    categories[category] += 1
                    dispositions[disposition] += 1
                    derived.append(
                        {
                            "call_id": entry["call_id"],
                            "shell_index": index,
                            "category": category,
                            "disposition": disposition,
                            "exit_code": code,
                        }
                    )
            self._sources(recipe)  # Reject reviewed prefix changes during derivation.
            # Recipe selectors cannot hide an identified accepted command.
            for source_index, rows in enumerate(sources):
                if recipe["sources"][source_index].get("purpose") == "historical_source_writes":
                    # Linked child prefixes supply contemporary file writes,
                    # never independent operational settlement/coverage facts.
                    continue
                for row in rows:
                    payload = row.get("payload", {})
                    if payload.get("type") not in {
                        "custom_tool_call",
                        "function_call",
                    } or payload.get("name") not in {"exec", "functions.exec"}:
                        continue
                    script = payload.get("input", payload.get("arguments", ""))
                    if type(script) is not str:
                        raise _fail()
                    for index, command in enumerate(_shells(script)):
                        try:
                            category = _category(command)
                        except HistoricalReceiptError:
                            if _potential_original_control(command, self.root.name):
                                raise _fail("history_inventory_control_grammar_unknown") from None
                            # Unselected ordinary helpers are outside judgment,
                            # not non-controls or settled records in the output.
                            unjudged_helpers += 1
                            continue
                        if (
                            category in {"original_docker", "application", "collector"}
                            and (payload.get("call_id"), index) not in seen
                        ):
                            raise _fail("history_inventory_coverage_incomplete")
            manifest = {
                "schema_version": 1,
                "scope": "bounded_original_recorded_controls",
                "categories": dict(categories),
                "dispositions": dict(dispositions),
                "unresolved_accepted_controls": 0,
                "coverage": "bounded_recorded_sources",
                "startup_initiator": "unrecorded_observed_start",
            }
            packet = json.dumps(
                {
                    "recipe": recipe,
                    "derived_receipts": derived,
                    "observed_container_ids": sorted(observed_containers),
                    "submitted_starts": submitted_starts,
                    "unselected_helpers_outside_judgment": unjudged_helpers,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            if len(packet) > 16 * 1024 * 1024:
                raise _fail()
            facts = object.__new__(DerivedHistoricalFacts)
            self._issued[id(facts)] = facts, manifest, packet
            return facts
        except HistoricalReceiptError:
            raise
        except Exception:
            raise _fail() from None

    def assert_issued(self, facts: object) -> None:
        row = self._issued.get(id(facts))
        if type(facts) is not DerivedHistoricalFacts or row is None or row[0] is not facts:
            raise _fail("history_facts_not_issued")

    def sanitized_manifest(self, facts: object) -> dict[str, object]:
        self.assert_issued(facts)
        return cast(dict[str, object], _json(json.dumps(self._issued[id(facts)][1])))

    def private_packet(self, facts: object) -> bytes:
        self.assert_issued(facts)
        return self._issued[id(facts)][2]

    def assert_original(
        self, facts: object, original: OriginalDeploymentIdentity, origin: OriginalTargetOrigin
    ) -> None:
        self.assert_issued(facts)
        if (
            type(original) is not OriginalDeploymentIdentity
            or type(origin) is not OriginalTargetOrigin
            or origin.container_id != original.container_id
            or origin.daemon_sha256 != original.daemon_sha256
            or origin.name != self.root.name + "-elasticsearch-1"
            or type(origin.created_at) is not datetime
            or origin.created_at.utcoffset() != UTC.utcoffset(origin.created_at)
        ):
            raise _fail("history_original_binding_invalid")
        packet = _json(self.private_packet(facts))
        if packet["observed_container_ids"] != [original.container_id]:
            raise _fail("history_original_binding_missing")
        for start in packet["submitted_starts"]:
            if origin.name not in start[
                "target_names"
            ] or origin.created_at > datetime.fromisoformat(start["submitted_at"]):
                raise _fail("history_original_binding_invalid")
