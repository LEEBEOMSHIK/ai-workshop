from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import threading
from pathlib import Path


def validated_store(raw: str) -> Path:
    candidate = Path(raw)
    if ".local-data/public" in candidate.as_posix():
        raise ValueError("publishing_acceptance_store_not_isolated")
    store = candidate.resolve(strict=True)
    repository = Path(__file__).resolve().parents[3]
    task_root = (
        repository
        / ".local-data"
        / "project-agent-work"
        / "publishing-service"
    ).resolve(strict=True)
    if (
        store.name != "studies.sqlite3"
        or store.parent.parent != task_root
        or re.fullmatch(r"acceptance-runtime-[a-z0-9]+", store.parent.name) is None
        or ".local-data/public" in store.as_posix()
    ):
        raise ValueError("publishing_acceptance_store_not_isolated")
    return store


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    arguments = parser.parse_args()
    if arguments.timeout <= 0 or arguments.timeout > 30:
        raise ValueError("publishing_acceptance_lock_timeout_invalid")

    connection = sqlite3.connect(validated_store(arguments.store), timeout=1)
    try:
        connection.execute("BEGIN EXCLUSIVE")
        print("READY", flush=True)
        released = threading.Event()

        def wait_for_release() -> None:
            sys.stdin.readline()
            released.set()

        threading.Thread(target=wait_for_release, daemon=True).start()
        released.wait(arguments.timeout)
    finally:
        connection.rollback()
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
