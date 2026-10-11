"""Pure synthetic Python source; no process, filesystem, DB or model calls."""

import importlib

import pytest


def module():
    return importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_history_invocations")


def context():
    return module().PythonInvocationContext(
        project_root="C:/synthetic/project",
        python_executable="C:/synthetic/project/venv/python.exe",
        docker_executable="C:/synthetic/docker.exe",
        docker_host="npipe:////./pipe/synthetic",
        original_container_targets=("synthetic-elasticsearch-1",),
        application_argv=(("-m", "uvicorn", "ai_workshop.main:app"),),
        collector_argv=(("-m", "ai_workshop.labs.rag.indexing.alias_recovery_cli", "recover"),),
    )


def classify(source, **kwargs):
    return module().classify_python_invocations(
        source,
        context=kwargs.pop("context", context()),
        submitted_executable=kwargs.pop(
            "submitted_executable", "C:/synthetic/project/venv/python.exe"
        ),
        submitted_cwd=kwargs.pop("submitted_cwd", "C:/synthetic/project"),
        **kwargs,
    )


APP = "['C:/synthetic/project/venv/python.exe','-m','uvicorn','ai_workshop.main:app']"
COLLECTOR = (
    "['C:/synthetic/project/venv/python.exe','-m',"
    "'ai_workshop.labs.rag.indexing.alias_recovery_cli','recover']"
)
DOCKER = "['C:/synthetic/docker.exe','--host','npipe:////./pipe/synthetic','start','synthetic-elasticsearch-1']"
DOCKER_WITHOUT_HOST = DOCKER.replace("'--host','npipe:////./pipe/synthetic',", "")


@pytest.mark.parametrize("callee", ["run", "Popen", "check_call", "check_output"])
def test_exact_imported_subprocess_receivers_bind_application(callee):
    result = classify(
        f"import subprocess as sp\nargv={APP}\n"
        f"sp.{callee}(argv,cwd='C:/synthetic/project',shell=False)"
    )
    assert result.disposition == "bound_original_control"
    assert len(result.invocations) == 1
    assert result.invocations[0].kind == "application"
    assert result.invocations[0].callee == f"subprocess.{callee}"
    assert result.invocations[0].line == 3
    assert "synthetic" not in repr(result)
    assert "synthetic" not in repr(result.invocations[0])


@pytest.mark.parametrize("argv,kind", [(COLLECTOR, "collector"), (DOCKER, "docker")])
def test_exact_literal_targets_bind_distinct_kinds(argv, kind):
    result = classify(f"from subprocess import run as launch\nlaunch({argv})")
    assert [call.kind for call in result.invocations] == [kind]


def test_literal_path_construction_and_prior_aliases():
    result = classify("""from pathlib import Path as P
from subprocess import run as launch
root=P('C:/synthetic/project')
python=root/'venv'/'python.exe'
argv=[str(python),'-m','uvicorn','ai_workshop.main:app']
copied=argv
launch(copied,cwd=str(root),capture_output=True,text=True,timeout=10,encoding='utf-8')
""")
    assert result.invocations[0].kind == "application"


def test_literal_joinpath_and_subprocess_pipe_constants():
    result = classify("""import pathlib as paths
import subprocess as sp
root=paths.Path('C:/synthetic/project')
python=root.joinpath('venv','python.exe')
sp.run([str(python),'-m','uvicorn','ai_workshop.main:app'],stdout=sp.PIPE,stderr=sp.DEVNULL)
""")
    assert len(result.invocations) == 1


@pytest.mark.parametrize(
    "source",
    [
        f"import asyncio as a\na.run(a.create_subprocess_exec(*{APP}))",
        "from asyncio import run as drive, create_subprocess_exec as launch\n"
        "drive(launch('C:/synthetic/project/venv/python.exe','-m','uvicorn','ai_workshop.main:app'))",
    ],
)
def test_async_invocation_requires_actual_closed_scheduling(source):
    result = classify(source)
    assert result.invocations[0].callee == "asyncio.create_subprocess_exec"


@pytest.mark.parametrize(
    "source",
    [
        "import ai_workshop.worker",
        "'subprocess.run(original_control)'",
        "print('StopApi docker start original')",
        "import subprocess\ndef unused():\n subprocess.run(unknown_target)\n",
        "import asyncio\nasync def unused():\n"
        " await asyncio.create_subprocess_exec(unknown_target)\n",
        "import subprocess\nsubprocess.run(['C:/unrelated/tool.exe','metadata'])",
    ],
)
def test_import_definition_or_quoted_text_is_never_an_accepted_control(source):
    result = classify(source)
    assert result.disposition == "recorded_unadjudicated"
    assert result.invocations == ()
    assert not hasattr(result, "settled") and not hasattr(result, "safe")


@pytest.mark.parametrize(
    "source",
    [
        f"import subprocess\nargv={APP}\nargv={APP}\nsubprocess.run(argv)",
        f"import subprocess as sp\nsp=unknown\nsp.run({APP})",
        f"import subprocess\nif condition:\n subprocess.run({APP})",
        f"import subprocess\nsubprocess.run({APP},shell=True)",
        f"import subprocess\nsubprocess.run({APP},env={{'KEY':'value'}})",
        f"import subprocess\nsubprocess.run({APP},cwd=unknown)",
        f"import subprocess\nsubprocess.run({APP},cwd='C:/elsewhere')",
        f"import subprocess\nsubprocess.run({APP.replace('project/venv', 'other/venv')})",
        f"import subprocess\nsubprocess.run({APP[:-1]},'--unknown'])",
        "import subprocess\nsubprocess.run(['C:/synthetic/project/venv/python.exe','helper.py'])",
        f"import asyncio\nasyncio.create_subprocess_exec(*{APP})",
        "import asyncio\nasyncio.run(helper())",
        f"import subprocess\ndef helper():\n subprocess.run({APP})\nhelper()",
        "@unknown\ndef unused():\n pass",
        "def unused(arg=unknown()):\n pass",
        "def unused(arg:unknown()):\n pass",
        "class Unknown:\n launch()",
        "from subprocess import *",
        f"import subprocess\ngetattr(subprocess,'run')({APP})",
        "import os\nos.system('original')",
        f"import subprocess\nsubprocess.run({DOCKER.replace('npipe:////./pipe/synthetic', 'npipe:////./pipe/other')})",
        f"import subprocess\nsubprocess.run({DOCKER_WITHOUT_HOST})",
        f"import subprocess\nsubprocess.run({DOCKER[:-1]},'unknown-container'])",
        "from pathlib import Path\np=Path('C:/synthetic/project')/'..'/'secret'",
        "from pathlib import Path\np=Path('C:/elsewhere')",
        "from pathlib import Path\np=Path('C:/synthetic/project').resolve()",
        "print=unknown\nprint('metadata')",
        "x=[v for v in unknown]",
        "try:\n pass\nexcept:\n pass",
        "pass\nunknown()",
    ],
)
def test_unsupported_or_bound_unresolved_source_refuses(source):
    with pytest.raises(module().PythonInvocationError, match=r"^history_python_[a-z_]+$"):
        classify(source)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"submitted_executable": "C:/other/python.exe"},
        {"submitted_cwd": "C:/elsewhere"},
        {"context": object()},
    ],
)
def test_submitted_context_is_checked_before_analysis(kwargs):
    with pytest.raises(module().PythonInvocationError):
        classify("pass", **kwargs)


def test_context_mutation_and_private_repr():
    value = context()
    assert "synthetic" not in repr(value)
    object.__setattr__(value, "application_argv", [["-m", "uvicorn"]])
    with pytest.raises(module().PythonInvocationError):
        classify("pass", context=value)


@pytest.mark.parametrize(
    "callee,options",
    [
        ("Popen", "check=False"),
        ("Popen", "capture_output=True"),
        ("Popen", "timeout=1"),
        ("check_call", "check=True"),
        ("check_output", "check=True"),
        ("check_output", "stdout=sp.PIPE"),
        ("run", "capture_output=True,stdout=sp.PIPE"),
        ("run", "stdin=sp.STDOUT"),
    ],
)
def test_options_are_valid_for_the_exact_process_callee(callee, options):
    with pytest.raises(module().PythonInvocationError):
        classify(f"import subprocess as sp\nsp.{callee}({APP},{options})")


@pytest.mark.parametrize(
    "source",
    [
        f"import subprocess as sp\nvalues=[sp.run({APP})]",
        "import subprocess as sp\n"
        f"sp.run({APP.replace('project/venv', 'other/venv')[:-1]},'--unknown'])",
        "import subprocess as sp\n"
        f"sp.run({DOCKER.replace('synthetic/docker.exe', 'other/docker.exe')})",
    ],
)
def test_hidden_effects_and_incomplete_original_related_binding_refuse(source):
    with pytest.raises(module().PythonInvocationError):
        classify(source)


def test_uncompilable_whole_module_cannot_supply_a_positive_invocation():
    source = f"import subprocess\nsubprocess.run({APP})\ndef unused():\n nonlocal missing\n"
    with pytest.raises(module().PythonInvocationError):
        classify(source)


def test_actual_source_is_never_executed(monkeypatch):
    import subprocess

    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("source must remain data")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = classify(f"import subprocess\nsubprocess.run({APP})")
    assert len(result.invocations) == 1 and calls == []


@pytest.mark.parametrize(
    "source",
    ["if", "x='unterminated", "x=1\n" * 10001, "#" * (1024 * 1024 + 1)],
    ids=["syntax", "unterminated", "node_bound", "byte_bound"],
)
def test_invalid_or_unbounded_source_has_body_free_error(source):
    with pytest.raises(module().PythonInvocationError, match=r"^history_python_[a-z_]+$"):
        classify(source)
