"""Explicit local administration import; defaults to a filesystem-only dry-run."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ai_workshop.config import Settings
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.issue_history.importer import apply_import, prepare_import, verify_import
from ai_workshop.shared.asyncio_policy import configure_windows_selector_policy
from ai_workshop.shared.db import create_engine, create_session_factory
from ai_workshop.shared.errors import AppError


async def run(
    root: Path, apply: bool, actor_id: UUID | None, verify: bool = False
) -> dict[str, int | str]:
    manifest = prepare_import(root)
    if not apply and not verify:
        return {**manifest.summary(), "result": "dry-run"}
    settings = Settings(_env_file=root / ".env")  # type: ignore[call-arg]
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine).begin() as session:
            if actor_id is None:
                owners = (
                    await session.scalars(
                        select(UserRecord.id).where(
                            UserRecord.role == "owner",
                            UserRecord.is_active.is_(True),
                        )
                    )
                ).all()
                if len(owners) != 1:
                    raise ValueError("Specify an existing active owner with --actor-id.")
                actor_id = owners[0]
            result = (
                await verify_import(session, manifest)
                if verify
                else await apply_import(session, manifest, actor_id)
            )
        return result
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true", help="Read-only initial cutover audit.")
    parser.add_argument("--actor-id", type=UUID)
    args = parser.parse_args()
    configure_windows_selector_policy()
    try:
        if args.apply and args.verify:
            parser.error("Use --apply or --verify, not both.")
        result = asyncio.run(run(args.root.resolve(), args.apply, args.actor_id, args.verify))
    except (ValueError, AppError, SQLAlchemyError) as exc:
        # Validation errors may embed private inputs: expose only safe error codes.
        parser.exit(
            1, f"Import failed: {exc.code if isinstance(exc, AppError) else 'invalid_input'}\n"
        )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
