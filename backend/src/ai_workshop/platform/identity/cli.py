from __future__ import annotations

import argparse
import asyncio
from getpass import getpass

from ai_workshop.config import get_settings
from ai_workshop.platform.identity.repository import SqlAlchemyUserRepository
from ai_workshop.platform.identity.service import Argon2PasswordHasher, JwtTokenService
from ai_workshop.platform.setup.service import SystemSetupService
from ai_workshop.platform.workspaces.repository import SqlAlchemyWorkspaceRepository
from ai_workshop.platform.workspaces.service import WorkspaceService
from ai_workshop.shared.db import create_engine, create_session_factory
from ai_workshop.shared.errors import AppError


async def bootstrap_owner(name: str, email: str) -> None:
    password = getpass("Owner password: ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")
    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters.")

    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory.begin() as session:
            service = SystemSetupService(
                SqlAlchemyUserRepository(session),
                WorkspaceService(SqlAlchemyWorkspaceRepository(session)),
                Argon2PasswordHasher(),
                JwtTokenService(settings),
                settings,
            )
            try:
                await service.create_owner(
                    display_name=name,
                    email=email,
                    password=password,
                    password_confirmation=confirmation,
                )
            except AppError as exc:
                raise SystemExit(exc.message) from exc
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="ai-workshop")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_bootstrap_owner_parser(subparsers)
    args = parser.parse_args()

    if args.command == "bootstrap-owner":
        asyncio.run(bootstrap_owner(args.name, args.email))


def add_bootstrap_owner_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    bootstrap = subparsers.add_parser(
        "bootstrap-owner",
        help="Recovery-only owner bootstrap when the setup UI cannot be used.",
    )
    bootstrap.add_argument("--name", required=True)
    bootstrap.add_argument("--email", required=True)
