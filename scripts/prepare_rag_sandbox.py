"""Provision an isolated, persistent Windows RAG sandbox without downloads or resets.

The ignored environment.json and credentials.json contain synthetic credentials.
Never print their contents or point this script at a development database.
"""

import argparse
import json
import os
import secrets
import socket
import stat
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

REPOSITORY = Path(__file__).resolve().parents[1]
ROOT = REPOSITORY / ".local-data" / "rag-sandbox"
PROJECT = "ai-workshop-rag-sandbox"
PORTS = {"postgres": 55474, "redis": 16379, "elasticsearch": 19200, "api": 18000}
IMAGES = {
    "postgres": "postgres:17-alpine",
    "redis": "redis:8-alpine",
    "elasticsearch": "docker.elastic.co/elasticsearch/elasticsearch:9.5.2",
}


def is_reparse(path: Path) -> bool:
    return path.is_symlink() or bool(
        getattr(path.lstat(), "st_file_attributes", 0)
        & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def require_new_root(root: Path) -> None:
    if root.exists():
        raise ValueError("Sandbox root already exists; use an explicit later phase.")
    for ancestor in root.parents:
        if ancestor.exists() and is_reparse(ancestor):
            raise ValueError("Sandbox root has a reparse ancestor.")


def require_free_port(port: int) -> None:
    with socket.socket() as connection:
        connection.settimeout(0.2)
        if connection.connect_ex(("127.0.0.1", port)) == 0:
            raise ValueError(f"Sandbox port {port} is already in use.")


def docker_names(kind: str) -> list[str]:
    command = [
        "docker",
        kind,
        "ls",
        "--format",
        "{{.Names}}" if kind == "container" else "{{.Name}}",
    ]
    if kind == "container":
        command.append("--all")
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    labeled = subprocess.run(
        [*command, "--filter", "label=com.docker.compose.project=" + PROJECT],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines() + ([PROJECT] if labeled.stdout.strip() else [])


def require_fresh_docker_project() -> None:
    for kind in ("container", "volume", "network"):
        if any(
            name == PROJECT or name.startswith((PROJECT + "-", PROJECT + "_"))
            for name in docker_names(kind)
        ):
            raise ValueError(
                "Refusing existing Docker sandbox resources; no adoption is allowed."
            )


def isolated_services(root: Path) -> dict[str, str]:
    return {
        "AI_WORKSHOP_PUBLISHING_PUBLIC_STORE_PATH": str(
            root / "public" / "studies.sqlite3"
        ),
        "AI_WORKSHOP_PUBLISHING_DELIVERY_MODE": "manual",
        "AI_WORKSHOP_PROVIDER_ENDPOINT_REFS": "{}",
        "AI_WORKSHOP_PROVIDER_SECRET_REFS": "{}",
        "AI_WORKSHOP_CODEX_RUNNER_REFS": "{}",
        "AI_WORKSHOP_PUBLIC_API_TARGET": "http://127.0.0.1:18000",
    }


def make_environment(root: Path, password: str, secret: str) -> dict[str, str]:
    return {
        **isolated_services(root),
        "AI_WORKSHOP_ENVIRONMENT": "local",
        "AI_WORKSHOP_SECRET_KEY": secret,
        "AI_WORKSHOP_DATABASE_URL": (
            "postgresql+psycopg://rag_sandbox:"
            + password
            + "@127.0.0.1:55474/ai_workshop_rag_sandbox"
        ),
        "AI_WORKSHOP_REDIS_URL": "redis://127.0.0.1:16379/0",
        "AI_WORKSHOP_ELASTICSEARCH_URL": "http://127.0.0.1:19200",
        "AI_WORKSHOP_ELASTICSEARCH_INDEX_PREFIX": PROJECT,
        "AI_WORKSHOP_OBJECT_STORE_ROOT": str(root / "objects"),
        "AI_WORKSHOP_TEMPORARY_STORE_ROOT": str(root / "temporary"),
        "AI_WORKSHOP_MODEL_CACHE_ROOT": str(REPOSITORY / ".local-data" / "models"),
        "AI_WORKSHOP_ORIGINAL_STORE_ID": "rag_sandbox_originals",
        "AI_WORKSHOP_ORIGINAL_STORE_BINDING_ID": str(uuid4()),
        "AI_WORKSHOP_TEMPORARY_STORE_ID": "rag_sandbox_temporary",
        "AI_WORKSHOP_TEMPORARY_STORE_BINDING_ID": str(uuid4()),
        "AI_WORKSHOP_RAG_ARTIFACT_STORE_ID": "rag_sandbox_artifacts",
        "AI_WORKSHOP_RAG_ARTIFACT_STORE_BINDING_ID": str(uuid4()),
        "AI_WORKSHOP_RAG_INDEX_STORE_ID": "rag_sandbox_indexes",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "API_PORT": "18000",
        "AI_WORKSHOP_FRONTEND_RUNTIME": "combined",
    }


def validate_environment(environment: dict[str, str], root: Path) -> None:
    database = urlsplit(environment.get("AI_WORKSHOP_DATABASE_URL", ""))
    expected = {
        **isolated_services(root),
        "AI_WORKSHOP_ENVIRONMENT": "local",
        "AI_WORKSHOP_REDIS_URL": "redis://127.0.0.1:16379/0",
        "AI_WORKSHOP_ELASTICSEARCH_URL": "http://127.0.0.1:19200",
        "AI_WORKSHOP_ELASTICSEARCH_INDEX_PREFIX": PROJECT,
        "AI_WORKSHOP_OBJECT_STORE_ROOT": str(root / "objects"),
        "AI_WORKSHOP_TEMPORARY_STORE_ROOT": str(root / "temporary"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
    if (
        any(environment.get(key) != value for key, value in expected.items())
        or not set(environment)
        <= set(make_environment(root, "", "")) | {"AI_WORKSHOP_RAG_INDEX_CLUSTER_UUID"}
        or database.scheme != "postgresql+psycopg"
        or database.hostname != "127.0.0.1"
        or database.port != PORTS["postgres"]
        or database.path != "/ai_workshop_rag_sandbox"
        or database.username != "rag_sandbox"
        or database.query
        or database.fragment
    ):
        raise ValueError("Refusing configuration outside the exact sandbox.")
    for path in (root, *root.parents, root / "objects", root / "temporary"):
        if path.exists() and is_reparse(path):
            raise ValueError("Refusing sandbox reparse path.")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def compose(*arguments: str) -> None:
    subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            PROJECT,
            "--env-file",
            str(ROOT / "compose.env"),
            "--file",
            str(ROOT / "compose.json"),
            *arguments,
        ],
        check=True,
        cwd=REPOSITORY,
    )


def prepare() -> None:
    require_new_root(ROOT)
    require_fresh_docker_project()
    for port in PORTS.values():
        require_free_port(port)
    for image in IMAGES.values():
        subprocess.run(
            ["docker", "image", "inspect", image], check=True, stdout=subprocess.DEVNULL
        )
    password = secrets.token_hex(24)
    environment = make_environment(ROOT, password, secrets.token_hex(32))
    ROOT.mkdir()
    for directory in ("objects", "temporary", "logs", "public"):
        (ROOT / directory).mkdir()
    write_json(ROOT / "environment.json", environment)
    write_json(
        ROOT / "credentials.json",
        {
            "display_name": "Synthetic RAG Owner",
            "email": "rag-sandbox@example.com",
            "password": secrets.token_urlsafe(24),
        },
    )
    (ROOT / "compose.env").write_text(
        "SANDBOX_POSTGRES_PASSWORD=" + password + "\n", encoding="utf-8"
    )
    for directory, marker, prefix in (
        ("objects", ".ai-workshop-original-store.json", "ORIGINAL"),
        ("objects", ".ai-workshop-store.json", "RAG_ARTIFACT"),
        ("temporary", ".ai-workshop-temporary-store.json", "TEMPORARY"),
    ):
        write_json(
            ROOT / directory / marker,
            {
                "schema_version": 1,
                "store_id": environment[f"AI_WORKSHOP_{prefix}_STORE_ID"],
                "binding_id": environment[f"AI_WORKSHOP_{prefix}_STORE_BINDING_ID"],
            },
        )
    services = {
        "postgres": {
            "image": IMAGES["postgres"],
            "pull_policy": "never",
            "environment": {
                "POSTGRES_USER": "rag_sandbox",
                "POSTGRES_DB": "ai_workshop_rag_sandbox",
                "POSTGRES_PASSWORD": "${SANDBOX_POSTGRES_PASSWORD:?required}",
            },
            "ports": ["127.0.0.1:55474:5432"],
            "volumes": ["postgres-data:/var/lib/postgresql/data"],
            "healthcheck": {
                "test": [
                    "CMD-SHELL",
                    "pg_isready -U rag_sandbox -d ai_workshop_rag_sandbox",
                ],
                "interval": "3s",
                "timeout": "3s",
                "retries": 30,
            },
        },
        "redis": {
            "image": IMAGES["redis"],
            "pull_policy": "never",
            "ports": ["127.0.0.1:16379:6379"],
            "volumes": ["redis-data:/data"],
            "command": ["redis-server", "--appendonly", "yes"],
            "healthcheck": {
                "test": ["CMD", "redis-cli", "ping"],
                "interval": "3s",
                "timeout": "3s",
                "retries": 30,
            },
        },
        "elasticsearch": {
            "image": IMAGES["elasticsearch"],
            "pull_policy": "never",
            "environment": {
                "discovery.type": "single-node",
                "xpack.security.enabled": "false",
                "ES_JAVA_OPTS": "-Xms1g -Xmx1g",
            },
            "ports": ["127.0.0.1:19200:9200"],
            "volumes": ["elasticsearch-data:/usr/share/elasticsearch/data"],
            "healthcheck": {
                "test": [
                    "CMD-SHELL",
                    "curl -fsS 'http://localhost:9200/_cluster/health?wait_for_status=yellow&timeout=2s' >/dev/null",
                ],
                "interval": "5s",
                "timeout": "4s",
                "retries": 40,
            },
        },
    }
    write_json(
        ROOT / "compose.json",
        {
            "name": PROJECT,
            "services": services,
            "volumes": {
                "postgres-data": {},
                "redis-data": {},
                "elasticsearch-data": {},
            },
        },
    )
    write_json(
        ROOT / "manifest.json", {"project": PROJECT, "root": str(ROOT), "ports": PORTS}
    )
    print("sandbox_configuration_prepared")


def load_environment() -> dict[str, str]:
    raw = json.loads((ROOT / "environment.json").read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in raw.items()
    ):
        raise ValueError("Sandbox environment must contain string settings only.")
    environment = {str(key): str(value) for key, value in raw.items()}
    validate_environment(environment, ROOT)
    return environment


def infrastructure() -> None:
    environment = load_environment()
    compose("up", "--detach", "--wait", "--wait-timeout", "180", "--pull", "never")
    with urllib.request.urlopen("http://127.0.0.1:19200/", timeout=5) as response:
        cluster = json.load(response)["cluster_uuid"]
    if not isinstance(cluster, str) or not cluster or cluster == "_na_":
        raise ValueError("Sandbox Elasticsearch cluster binding is unavailable.")
    previous = environment.get("AI_WORKSHOP_RAG_INDEX_CLUSTER_UUID")
    if previous is not None and previous != cluster:
        raise ValueError("Sandbox Elasticsearch identity changed; refusing adoption.")
    environment["AI_WORKSHOP_RAG_INDEX_CLUSTER_UUID"] = cluster
    write_json(ROOT / "environment.json", environment)
    print("sandbox_infrastructure_ready")


def install_environment(environment: dict[str, str], root: Path) -> None:
    validate_environment(environment, root)
    for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"):
        if key in os.environ:
            raise ValueError("Refusing inherited database override in sandbox runtime.")
    for key in list(os.environ):
        if key.upper().startswith("AI_WORKSHOP_") or key in {
            "API_PORT",
            "PUBLIC_API_PORT",
        }:
            del os.environ[key]
    os.environ.update(environment)
    from ai_workshop.config import Settings, get_settings

    Settings.model_config["env_file"] = None
    get_settings.cache_clear()


def runtime(phase: str) -> None:
    environment = load_environment()
    install_environment(environment, ROOT)
    os.chdir(ROOT)
    from ai_workshop.shared.asyncio_policy import configure_windows_selector_policy

    configure_windows_selector_policy()
    if phase == "migrate":
        from alembic.config import main as alembic_main

        alembic_main(
            argv=["-c", str(REPOSITORY / "backend" / "alembic.ini"), "upgrade", "head"]
        )
        from ai_workshop.cli import main as cli_main

        cli_main(["register-rag-models"])
        print("sandbox_schema_and_catalog_ready")
    elif phase == "api":
        require_free_port(PORTS["api"])
        import uvicorn

        uvicorn.run(
            "ai_workshop.main:app",
            host="127.0.0.1",
            port=PORTS["api"],
            loop="ai_workshop.shared.asyncio_policy:create_selector_event_loop",
        )
    elif phase in {"worker", "beat"}:
        from ai_workshop.worker import celery_app

        arguments = (
            ["worker", "--pool=solo", "--loglevel=INFO", "--hostname=rag-sandbox@%h"]
            if phase == "worker"
            else [
                "beat",
                "--loglevel=INFO",
                "--schedule",
                str(ROOT / "celerybeat-schedule"),
            ]
        )
        celery_app.start(arguments)
    elif phase == "frontend":
        require_free_port(5173)
        os.chdir(REPOSITORY / "frontend")
        raise SystemExit(
            subprocess.call(
                [
                    "node",
                    str(REPOSITORY / "frontend/node_modules/next/dist/bin/next"),
                    "dev",
                    "--hostname",
                    "127.0.0.1",
                    "--port",
                    "5173",
                ]
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=(
            "prepare",
            "infrastructure",
            "migrate",
            "api",
            "worker",
            "beat",
            "frontend",
        ),
    )
    phase = parser.parse_args().phase
    if phase == "prepare":
        prepare()
    elif phase == "infrastructure":
        infrastructure()
    else:
        runtime(phase)


if __name__ == "__main__":
    main()
