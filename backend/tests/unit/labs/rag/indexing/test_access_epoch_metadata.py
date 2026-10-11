"""The ORM schema agrees with0062 while v1 reads omit deferred new columns."""

import importlib.util
import re
from pathlib import Path

from sqlalchemy import CheckConstraint, select

from ai_workshop.labs.rag.indexing.alias_models import AliasRecoveryReceiptRecord


def test_receipt_metadata_has_v2_linkage_and_same_proof_check_as_migration(monkeypatch):
    path = Path(__file__).parents[5] / "alembic/versions/0062_rag_access_epoch.py"
    spec = importlib.util.spec_from_file_location("epoch_revision", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statements = []

    class Operations:
        def execute(self, statement):
            statements.append(statement)

    monkeypatch.setattr(module, "op", Operations())
    module.upgrade()
    sql = "\n".join(statements)
    check = re.search(
        r"ADD CONSTRAINT ck_rag_alias_receipt_proof CHECK \((.*?)\n\);", sql, re.S
    ).group(1)
    table = AliasRecoveryReceiptRecord.__table__
    assert {"access_epoch_id", "execution_id"} <= set(table.columns.keys())
    constraint = next(
        c
        for c in table.constraints
        if isinstance(c, CheckConstraint) and c.name == "ck_rag_alias_receipt_proof"
    )
    def normalize(value):
        return re.sub(r"\s+", "", str(value)).lower()
    assert normalize(constraint.sqltext) == normalize(check)
    selected = str(select(AliasRecoveryReceiptRecord))
    assert ".access_epoch_id" not in selected and ".execution_id" not in selected
