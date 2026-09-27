"""Reject missing judgment inputs and verify stored per-claim citation structure."""

from alembic import op

revision = "0059_generative_raw_proof"
down_revision = "0058_generative_case_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE FUNCTION rag_require_generative_raw_proof(result jsonb, rule jsonb)
    RETURNS void LANGUAGE plpgsql AS $$
    DECLARE item jsonb; ordinal integer:=0; ids jsonb:='[]'; cited jsonb;
    BEGIN
      IF jsonb_typeof(rule->'required_propositions') IS DISTINCT FROM 'array'
        OR jsonb_typeof(rule->'forbidden_propositions') IS DISTINCT FROM 'array'
        OR jsonb_typeof(rule->'required_evidence_groups') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'missing raw judgment rule fields';
      END IF;
      FOR item IN SELECT * FROM jsonb_array_elements(
        (rule->'required_propositions')||(rule->'forbidden_propositions')) LOOP
        IF jsonb_typeof(item) IS DISTINCT FROM 'string'
          OR length(rag_normalize_proposition(item#>>'{}'))=0 THEN
          RAISE EXCEPTION 'invalid proposition rule';
        END IF;
      END LOOP;
      IF result->'observation'->>'generation_status'='answered' THEN
        IF jsonb_typeof(result->'answer') IS DISTINCT FROM 'string'
          OR length(btrim(result->>'answer'))=0
          OR jsonb_typeof(result->'citations') IS DISTINCT FROM 'array'
          OR coalesce(jsonb_array_length(result->'citations'),0)=0 THEN
          RAISE EXCEPTION 'answered result requires raw citations';
        END IF;
        FOR item IN SELECT * FROM jsonb_array_elements(result->'citations') LOOP
          IF jsonb_typeof(item->'claim_index') IS DISTINCT FROM 'number'
            OR item->>'claim_index' IS DISTINCT FROM ordinal::text
            OR jsonb_typeof(item->'evidence_ids') IS DISTINCT FROM 'array'
            OR coalesce(jsonb_array_length(item->'evidence_ids'),0)=0 THEN
            RAISE EXCEPTION 'invalid raw claim citation';
          END IF;
          ids:=ids||(item->'evidence_ids'); ordinal:=ordinal+1;
        END LOOP;
        cited:=result->'observation'->'cited_evidence_ids';
        IF (ids @> cited AND cited @> ids) IS DISTINCT FROM true
          OR ((result->'observation'->'selected_evidence_ids') @> ids)
            IS DISTINCT FROM true THEN
          RAISE EXCEPTION 'raw citations disagree with observation';
        END IF;
      END IF;
    END $$;
    DO $$ DECLARE definition text; BEGIN
      SELECT pg_get_functiondef('rag_verify_generative_candidate(uuid,uuid)'::regprocedure)
        INTO definition;
      definition:=replace(definition, 'observation:=a.result->''observation'';',
        'PERFORM rag_require_generative_raw_proof(a.result,rule); '
        'observation:=a.result->''observation'';');
      EXECUTE definition;
    END $$;
    """)


def downgrade() -> None:
    raise RuntimeError("Proof validation rollback requires explicit review.")
