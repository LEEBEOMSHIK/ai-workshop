"""New original ownership tests must never fall back to a developer's .env DB."""

import os


def require_explicit_original_test_database() -> None:
    if (
        os.environ.get("AI_WORKSHOP_ENVIRONMENT") != "test"
        or not os.environ.get("AI_WORKSHOP_DATABASE_URL")
    ):
        raise RuntimeError("explicit_original_test_database_required")
