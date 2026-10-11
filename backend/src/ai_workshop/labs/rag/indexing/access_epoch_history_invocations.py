"""Pure, deliberately incomplete Python invocation analysis; never proof authority.

No source is executed and no filesystem, environment, history or terminal is read.
Consumers must establish context and retained-source provenance independently.
"""

import ast
import re
from dataclasses import dataclass, field
from pathlib import PureWindowsPath
from typing import Literal, cast


class PythonInvocationError(ValueError):
    """Fixed body-free refusal; unknown source never becomes a safe verdict."""


def _deny(reason: str = "unsupported_source") -> PythonInvocationError:
    return PythonInvocationError("history_python_" + reason)


@dataclass(frozen=True, slots=True)
class PythonInvocationContext:
    project_root: str = field(repr=False)
    python_executable: str = field(repr=False)
    docker_executable: str = field(repr=False)
    docker_host: str = field(repr=False)
    original_container_targets: tuple[str, ...] = field(repr=False)
    application_argv: tuple[tuple[str, ...], ...] = field(repr=False)
    collector_argv: tuple[tuple[str, ...], ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class PythonControlInvocation:
    kind: Literal["application", "collector", "docker"]
    callee: str
    line: int
    argv: tuple[str, ...] = field(repr=False)
    cwd: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class PythonInvocationAnalysis:
    """An ordinary analysis DTO, not a receipt or source-issued capability."""

    disposition: Literal["bound_original_control", "recorded_unadjudicated"]
    invocations: tuple[PythonControlInvocation, ...] = field(repr=False)
    import_count: int
    uncalled_definition_count: int
    unbound_invocation_count: int


@dataclass(frozen=True, slots=True)
class _Symbol:
    name: str


@dataclass(frozen=True, slots=True)
class _ProcessValue:
    pass


type _Value = (
    str | int | bool | None | PureWindowsPath | _Symbol | _ProcessValue | tuple[_Value, ...]
)


def _string(value: object) -> str:
    if type(value) is not str or not value or len(value) > 32768 or "\x00" in value:
        raise _deny("literal_invalid")
    return value


def _path(value: object) -> PureWindowsPath:
    text = _string(value)
    path = PureWindowsPath(text)
    if (
        not path.is_absolute()
        or not re.fullmatch(r"[A-Za-z]:", path.drive)
        or ".." in path.parts
        or any(":" in part or part.endswith((".", " ")) for part in path.parts[1:])
        or any(char in text for char in ("\r", "\n", "*", "?"))
    ):
        raise _deny("context_unverified")
    return path


def _context(value: PythonInvocationContext) -> None:
    if type(value) is not PythonInvocationContext:
        raise _deny("context_unverified")
    paths = [
        _path(v) for v in (value.project_root, value.python_executable, value.docker_executable)
    ]
    if len(set(paths)) != 3:
        raise _deny("context_unverified")
    if re.fullmatch(r"npipe:////\./pipe/[A-Za-z0-9_.-]{1,128}", _string(value.docker_host)) is None:
        raise _deny("context_unverified")
    targets = value.original_container_targets
    if (
        type(targets) is not tuple
        or not 1 <= len(targets) <= 16
        or any(
            type(v) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", v) is None
            for v in targets
        )
        or len(set(targets)) != len(targets)
    ):
        raise _deny("context_unverified")
    entries: list[tuple[str, ...]] = []
    for group in (value.application_argv, value.collector_argv):
        if type(group) is not tuple or not 1 <= len(group) <= 16:
            raise _deny("context_unverified")
        for argv in group:
            if type(argv) is not tuple or not 2 <= len(argv) <= 64:
                raise _deny("context_unverified")
            for arg in argv:
                _string(arg)
            if argv[0] != "-m" or re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", argv[1]) is None:
                raise _deny("context_unverified")
            entries.append(argv)
    if len(set(entries)) != len(entries):
        raise _deny("context_unverified")


class _Analyzer:
    def __init__(self, context: PythonInvocationContext) -> None:
        self.context = context
        self.bindings: dict[str, _Value] = {}
        self.controls: list[PythonControlInvocation] = []
        self.imports = 0
        self.definitions = 0
        self.unbound = 0

    def bind(self, name: str, value: _Value) -> None:
        if name in self.bindings or name in {"str", "print"}:
            raise _deny("binding_ambiguous")
        self.bindings[name] = value

    def join(self, base: PureWindowsPath, values: list[_Value]) -> PureWindowsPath:
        if not values or len(values) > 16:
            raise _deny()
        for value in values:
            component = _string(value)
            part = PureWindowsPath(component)
            if (
                part.anchor
                or ".." in part.parts
                or any(c in component for c in ("\r", "\n", "*", "?", ":"))
            ):
                raise _deny("path_unverified")
            base /= part
        return base

    def value(self, node: ast.expr, depth: int = 0) -> _Value:
        if depth > 64:
            raise _deny("source_bound")
        if isinstance(node, ast.Constant) and type(node.value) in {str, bool, int, type(None)}:
            return cast(str | int | bool | None, node.value)
        if isinstance(node, (ast.List, ast.Tuple)):
            if len(node.elts) > 64:
                raise _deny("source_bound")
            values = tuple(self.value(item, depth + 1) for item in node.elts)
            if any(
                not self.literal_only(value) and not isinstance(value, PureWindowsPath)
                for value in values
            ):
                raise _deny()
            return values
        if isinstance(node, ast.Name):
            if node.id not in self.bindings:
                raise _deny("binding_unresolved")
            return self.bindings[node.id]
        if isinstance(node, ast.Attribute):
            owner = self.value(node.value, depth + 1)
            if isinstance(owner, _Symbol):
                allowed = {
                    "subprocess": {
                        "run",
                        "Popen",
                        "check_call",
                        "check_output",
                        "PIPE",
                        "DEVNULL",
                        "STDOUT",
                    },
                    "asyncio": {"run", "create_subprocess_exec"},
                    "pathlib": {"Path"},
                }
                if node.attr in allowed.get(owner.name, set()):
                    return _Symbol(owner.name + "." + node.attr)
            raise _deny("receiver_unresolved")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = self.value(node.left, depth + 1)
            if isinstance(left, PureWindowsPath):
                return self.join(left, [self.value(node.right, depth + 1)])
            raise _deny("path_unverified")
        if isinstance(node, ast.Call):
            return self.call(node, depth + 1)
        raise _deny()

    def call(self, node: ast.Call, depth: int) -> _Value:
        if isinstance(node.func, ast.Name) and node.func.id in {"str", "print"}:
            if node.func.id in self.bindings or node.keywords:
                raise _deny("binding_ambiguous")
            values = [self.value(arg, depth + 1) for arg in node.args]
            if node.func.id == "str":
                if len(values) != 1 or not isinstance(values[0], PureWindowsPath):
                    raise _deny()
                return values[0].as_posix()
            if any(not self.literal_only(v) for v in values):
                raise _deny()
            return None
        if isinstance(node.func, ast.Attribute) and node.func.attr == "joinpath":
            owner = self.value(node.func.value, depth + 1)
            if not isinstance(owner, PureWindowsPath) or node.keywords:
                raise _deny("path_unverified")
            return self.join(owner, [self.value(arg, depth + 1) for arg in node.args])
        receiver = self.value(node.func, depth + 1)
        if not isinstance(receiver, _Symbol):
            raise _deny("receiver_unresolved")
        name = receiver.name
        if name == "pathlib.Path":
            if len(node.args) != 1 or node.keywords:
                raise _deny("path_unverified")
            value = self.value(node.args[0], depth + 1)
            if isinstance(value, PureWindowsPath):
                return value
            path = _path(value)
            if path not in {
                _path(self.context.project_root),
                _path(self.context.python_executable),
                _path(self.context.docker_executable),
            }:
                raise _deny("path_unverified")
            return path
        if name == "asyncio.run":
            if len(node.args) != 1 or node.keywords or not isinstance(node.args[0], ast.Call):
                raise _deny("async_schedule_unverified")
            inner = node.args[0]
            inner_receiver = self.value(inner.func, depth + 1)
            if (
                not isinstance(inner_receiver, _Symbol)
                or inner_receiver.name != "asyncio.create_subprocess_exec"
            ):
                raise _deny("async_schedule_unverified")
            return self.process(inner, inner_receiver.name, depth + 1)
        if name in {
            "subprocess.run",
            "subprocess.Popen",
            "subprocess.check_call",
            "subprocess.check_output",
        }:
            return self.process(node, name, depth + 1)
        if name == "asyncio.create_subprocess_exec":
            raise _deny("async_schedule_unverified")
        raise _deny("helper_invocation_unsupported")

    def literal_only(self, value: _Value) -> bool:
        return type(value) in {str, int, bool, type(None)} or (
            type(value) is tuple and all(self.literal_only(item) for item in value)
        )

    def process(self, node: ast.Call, name: str, depth: int) -> _ProcessValue:
        if name == "asyncio.create_subprocess_exec":
            if len(node.args) == 1 and isinstance(node.args[0], ast.Starred):
                raw = self.value(node.args[0].value, depth + 1)
            else:
                raw = tuple(self.value(arg, depth + 1) for arg in node.args)
        else:
            if len(node.args) != 1:
                raise _deny("argv_unresolved")
            raw = self.value(node.args[0], depth + 1)
        if type(raw) is not tuple or not 1 <= len(raw) <= 64:
            raise _deny("argv_unresolved")
        argv = tuple(_string(v.as_posix() if isinstance(v, PureWindowsPath) else v) for v in raw)
        cwd = self.context.project_root
        seen: set[str] = set()
        capture_output = False
        for keyword in node.keywords:
            key = keyword.arg
            if key is None or key in seen:
                raise _deny("argv_unresolved")
            seen.add(key)
            if (
                key in {"check", "capture_output"}
                and name != "subprocess.run"
                or key == "timeout"
                and name == "subprocess.Popen"
                or key == "stdout"
                and name == "subprocess.check_output"
            ):
                raise _deny("option_unsupported")
            value = self.value(keyword.value, depth + 1)
            if key == "cwd":
                cwd = _path(
                    value.as_posix() if isinstance(value, PureWindowsPath) else value
                ).as_posix()
            elif key in {"stdin", "stdout", "stderr"}:
                if not isinstance(value, _Symbol) or value.name not in {
                    "subprocess.PIPE",
                    "subprocess.DEVNULL",
                    "subprocess.STDOUT",
                }:
                    raise _deny("option_unsupported")
                if key != "stderr" and value.name == "subprocess.STDOUT":
                    raise _deny("option_unsupported")
            elif name == "asyncio.create_subprocess_exec":
                raise _deny("option_unsupported")
            elif key == "shell":
                if value is not False:
                    raise _deny("shell_unsupported")
            elif key in {"check", "capture_output", "text"}:
                if type(value) is not bool:
                    raise _deny("option_unsupported")
                if key == "capture_output":
                    capture_output = value
            elif key == "timeout":
                if type(value) is not int or not 0 < value < 2**31:
                    raise _deny("option_unsupported")
            elif key == "encoding":
                if value != "utf-8":
                    raise _deny("option_unsupported")
            else:
                raise _deny("option_unsupported")
        if capture_output and {"stdout", "stderr"}.intersection(seen):
            raise _deny("option_unsupported")
        kind = self.target(argv, cwd)
        if kind is None:
            self.unbound += 1
        else:
            self.controls.append(PythonControlInvocation(kind, name, node.lineno, argv, cwd))
        return _ProcessValue()

    def target(
        self, argv: tuple[str, ...], cwd: str
    ) -> Literal["application", "collector", "docker"] | None:
        try:
            executable = _path(argv[0])
        except PythonInvocationError:
            raise _deny("executable_unresolved") from None
        suffix = argv[1:]
        known_suffixes = self.context.application_argv + self.context.collector_argv
        if executable == _path(self.context.python_executable) or any(
            suffix[:2] == known[:2] for known in known_suffixes
        ):
            if executable != _path(self.context.python_executable) or _path(cwd) != _path(
                self.context.project_root
            ):
                raise _deny("target_unresolved")
            if suffix in self.context.application_argv:
                return "application"
            if suffix in self.context.collector_argv:
                return "collector"
            raise _deny("helper_source_unresolved")
        targets = set(self.context.original_container_targets)
        if (
            executable.name.casefold() in {"docker", "docker.exe"}
            and targets.intersection(argv)
            and executable != _path(self.context.docker_executable)
        ):
            raise _deny("executable_unresolved")
        if executable == _path(self.context.docker_executable):
            if not targets.intersection(argv):
                return None
            if len(argv) < 5 or argv[1:3] != ("--host", self.context.docker_host):
                raise _deny("target_unresolved")
            if argv[3] not in {"start", "stop", "restart", "kill", "rm", "pause", "unpause"}:
                raise _deny("target_unresolved")
            if not set(argv[4:]) <= targets or len(set(argv[4:])) != len(argv[4:]):
                raise _deny("target_unresolved")
            return "docker"
        return None

    def statement(self, node: ast.stmt) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                self.bind(
                    name,
                    _Symbol(
                        alias.name
                        if alias.name in {"subprocess", "asyncio", "pathlib"}
                        else "unknown_import"
                    ),
                )
                self.imports += 1
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module is None:
                raise _deny("import_unsupported")
            for alias in node.names:
                if alias.name == "*":
                    raise _deny("import_unsupported")
                self.bind(alias.asname or alias.name, _Symbol(node.module + "." + alias.name))
                self.imports += 1
        elif isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                raise _deny("binding_ambiguous")
            self.bind(node.targets[0].id, self.value(node.value))
        elif isinstance(node, ast.Expr):
            self.value(node.value)
        elif isinstance(node, ast.Pass):
            return
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            if (
                node.decorator_list
                or node.returns is not None
                or node.type_params
                or args.defaults
                or any(value is not None for value in args.kw_defaults)
                or any(
                    arg.annotation is not None
                    for arg in [
                        *args.posonlyargs,
                        *args.args,
                        *args.kwonlyargs,
                        *([args.vararg] if args.vararg else []),
                        *([args.kwarg] if args.kwarg else []),
                    ]
                )
            ):
                raise _deny("definition_effect_unresolved")
            self.bind(node.name, _Symbol("uncalled_helper"))
            self.definitions += 1
        else:
            raise _deny()


def classify_python_invocations(
    source: str,
    *,
    context: PythonInvocationContext,
    submitted_executable: str,
    submitted_cwd: str,
) -> PythonInvocationAnalysis:
    """Analyze literal invocation relations; never issue operational proof."""
    try:
        _context(context)
        if _path(submitted_executable) != _path(context.python_executable) or _path(
            submitted_cwd
        ) != _path(context.project_root):
            raise _deny("context_unverified")
        if (
            type(source) is not str
            or len(source) > 1024 * 1024
            or len(source.encode("utf-8")) > 1024 * 1024
        ):
            raise _deny("source_bound")
        tree = ast.parse(source)
        if sum(1 for _ in ast.walk(tree)) > 10000:
            raise _deny("source_bound")
        # Validate scope/syntax constraints ast.parse alone omits. Never execute
        # the resulting code object or import anything named by the source.
        compile(tree, "<historical_python>", "exec")
        analyzer = _Analyzer(context)
        for statement in tree.body:
            analyzer.statement(statement)
        return PythonInvocationAnalysis(
            "bound_original_control" if analyzer.controls else "recorded_unadjudicated",
            tuple(analyzer.controls),
            analyzer.imports,
            analyzer.definitions,
            analyzer.unbound,
        )
    except PythonInvocationError:
        raise
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, OverflowError):
        raise _deny("source_invalid") from None
