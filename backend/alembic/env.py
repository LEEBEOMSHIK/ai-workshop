from asyncio import run
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.configurations import models as rag_configuration_models  # noqa: F401
from ai_workshop.labs.rag.documents import models as rag_document_models  # noqa: F401
from ai_workshop.labs.rag.evaluation import models as rag_evaluation_models  # noqa: F401
from ai_workshop.labs.rag.ingestion import models as rag_ingestion_models  # noqa: F401
from ai_workshop.labs.rag.models import models as rag_model_models  # noqa: F401
from ai_workshop.platform.assets import models as asset_models  # noqa: F401
from ai_workshop.platform.identity import models as identity_models  # noqa: F401
from ai_workshop.platform.jobs import models as job_models  # noqa: F401
from ai_workshop.platform.workspaces import models as workspace_models  # noqa: F401
from ai_workshop.shared.models import Base
from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: object) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
