"""Bind expected status to the canonical dataset's nested expected contract."""

from alembic import op

revision = "0058_generative_case_contract"
down_revision = "0057_generative_proof_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    DO $$ DECLARE definition text; BEGIN
      SELECT pg_get_functiondef('rag_verify_generative_candidate(uuid,uuid)'::regprocedure)
        INTO definition;
      definition := replace(definition,
        '::jsonb->>''expected_answer_status''', '::jsonb->''expected''->>''answer_status''');
      EXECUTE definition;
    END $$;
    CREATE OR REPLACE FUNCTION rag_normalize_proposition(value text) RETURNS text
    LANGUAGE sql IMMUTABLE STRICT AS $$
      SELECT btrim(regexp_replace(translate(normalize(value,NFKC),
        'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),
        '[ '||chr(9)||chr(10)||chr(12)||chr(13)||chr(11)||']+', ' ', 'g'))
    $$;
    """)


def downgrade() -> None:
    raise RuntimeError("Proof validation rollback requires explicit review.")
