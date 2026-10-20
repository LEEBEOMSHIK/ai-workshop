"""Cancel only unstarted evaluations while retaining immutable input and audit evidence."""

# ruff: noqa: E501 -- Keep PostgreSQL transition predicates together.
from alembic import op

revision = "0066_generative_pending_cancel"
down_revision = "0065_local_transformers"
branch_labels = None
depends_on = None

# The pre-change definitions include 0056's dispatch timestamp allowance.
OLD_RUN_GUARD = """
CREATE OR REPLACE FUNCTION rag_generative_run_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'generative run removal requires an authorized retention operation';
  END IF;
  IF TG_OP='UPDATE' AND
    (to_jsonb(NEW)-ARRAY['status','claim_token','claimed_at','finished_at','runtime_environment','updated_at','dispatched_at'])
    IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['status','claim_token','claimed_at','finished_at','runtime_environment','updated_at','dispatched_at']) THEN
    RAISE EXCEPTION 'generative run input is immutable';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM rag_evaluation_datasets d JOIN rag_generative_policies p
    ON p.id=NEW.policy_id WHERE d.id=NEW.dataset_snapshot_id
    AND d.owner_id=NEW.owner_id AND p.owner_id=NEW.owner_id) THEN
    RAISE EXCEPTION 'generative input ownership mismatch';
  END IF;
  RETURN NEW;
END $$;
"""
OLD_ATTEMPT_GUARD = """
CREATE OR REPLACE FUNCTION rag_generative_attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent rag_generative_runs;
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'attempt evidence is immutable'; END IF;
  SELECT * INTO parent FROM rag_generative_runs WHERE id=NEW.run_id FOR UPDATE;
  IF NOT EXISTS(SELECT 1 FROM rag_evaluation_dataset_cases
      WHERE dataset_snapshot_id=parent.dataset_snapshot_id AND id=NEW.case_id)
    OR NEW.repetition>=parent.repetition_count
    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(parent.snapshot->'candidates') c
      WHERE c->>'configuration_version_id'=NEW.configuration_version_id::text) THEN
    RAISE EXCEPTION 'attempt is outside frozen inputs';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF OLD.status IN ('completed','failed','interrupted') OR
      (to_jsonb(NEW)-ARRAY['status','claim_token','result','result_bytes','result_digest','error_code','finished_at','updated_at'])
      IS DISTINCT FROM
      (to_jsonb(OLD)-ARRAY['status','claim_token','result','result_bytes','result_digest','error_code','finished_at','updated_at']) THEN
      RAISE EXCEPTION 'attempt identity or terminal result is immutable';
    END IF;
    IF parent.status<>'running' OR NEW.claim_token IS DISTINCT FROM parent.claim_token THEN
      RAISE EXCEPTION 'stale generative attempt claim';
    END IF;
  END IF;
  RETURN NEW;
END $$;
"""

RUN_CANCEL_GUARD = """
  IF TG_OP='UPDATE' AND OLD.status='cancelled' THEN
    RAISE EXCEPTION 'cancelled generative run is immutable';
  END IF;
  IF NEW.status='cancelled' THEN
    IF TG_OP<>'UPDATE' OR OLD.status<>'pending' OR OLD.claim_token IS NOT NULL
      OR OLD.claimed_at IS NOT NULL OR OLD.finished_at IS NOT NULL
      OR OLD.runtime_environment IS NOT NULL THEN
      RAISE EXCEPTION 'only an unstarted generative run can be cancelled';
    END IF;
    IF NEW.cancelled_by IS DISTINCT FROM NEW.owner_id OR NOT EXISTS(
      SELECT 1 FROM users WHERE id=NEW.cancelled_by AND role='owner') THEN
      RAISE EXCEPTION 'generative cancellation requires the owning owner';
    END IF;
    -- The UPDATE already owns the parent row; acquire children in a stable order.
    PERFORM id FROM rag_generative_attempts WHERE run_id=NEW.id ORDER BY id FOR UPDATE;
    IF EXISTS(SELECT 1 FROM rag_generative_attempts a WHERE a.run_id=NEW.id AND (
      a.status<>'pending' OR a.claim_token IS NOT NULL OR a.finished_at IS NOT NULL
      OR a.result IS NOT NULL OR a.result_bytes IS NOT NULL OR a.result_digest IS NOT NULL
      OR a.error_code IS NOT NULL)) OR EXISTS(
      SELECT 1 FROM rag_generative_attempts a JOIN rag_executions x
        ON x.id=a.execution_id OR x.evaluation_attempt_id=a.id WHERE a.run_id=NEW.id
    ) OR EXISTS(
      SELECT 1 FROM rag_generative_attempts a JOIN rag_generation_execution_audits x
        ON x.execution_id=a.execution_id WHERE a.run_id=NEW.id
    ) THEN
      RAISE EXCEPTION 'generative cancellation requires all attempts to be unstarted';
    END IF;
  END IF;
"""

ATTEMPT_CANCEL_GUARD = """
  IF TG_OP='INSERT' AND (NEW.status='cancelled' OR parent.status='cancelled') THEN
    RAISE EXCEPTION 'cannot add an attempt to a cancelled generative run';
  END IF;
  IF TG_OP='UPDATE' AND OLD.status='cancelled' THEN
    RAISE EXCEPTION 'cancelled generative attempt is immutable';
  END IF;
  IF TG_OP='UPDATE' AND NEW.status='cancelled' THEN
    IF parent.status<>'cancelled' OR OLD.status<>'pending'
      OR OLD.claim_token IS NOT NULL OR OLD.finished_at IS NOT NULL
      OR OLD.result IS NOT NULL OR OLD.result_bytes IS NOT NULL
      OR OLD.result_digest IS NOT NULL OR OLD.error_code IS NOT NULL
      OR NEW.finished_at IS DISTINCT FROM parent.cancelled_at
      OR (to_jsonb(NEW)-ARRAY['status','finished_at','updated_at']) IS DISTINCT FROM
         (to_jsonb(OLD)-ARRAY['status','finished_at','updated_at']) THEN
      RAISE EXCEPTION 'invalid generative attempt cancellation';
    END IF;
    RETURN NEW;
  END IF;
"""


def _status_constraints(*, cancel: bool) -> None:
    op.execute("""
    ALTER TABLE rag_generative_runs DROP CONSTRAINT rag_generative_runs_status_check,
      DROP CONSTRAINT rag_generative_runs_check2;
    ALTER TABLE rag_generative_attempts DROP CONSTRAINT rag_generative_attempts_status_check,
      DROP CONSTRAINT rag_generative_attempts_check;
    """)
    extra = ",'cancelled'" if cancel else ""
    run_cancel = (
        " OR (status='cancelled' AND claim_token IS NULL AND claimed_at IS NULL "
        "AND finished_at IS NOT NULL AND runtime_environment IS NULL)" if cancel else ""
    )
    attempt_cancel = (
        " OR (status='cancelled' AND claim_token IS NULL AND finished_at IS NOT NULL "
        "AND result IS NULL AND result_bytes IS NULL AND result_digest IS NULL "
        "AND error_code IS NULL)" if cancel else ""
    )
    op.execute(f"""
    ALTER TABLE rag_generative_runs
      ADD CONSTRAINT rag_generative_runs_status_check CHECK(status IN ('pending','running','completed','failed'{extra})),
      ADD CONSTRAINT rag_generative_runs_check2 CHECK(
        (status='pending' AND claim_token IS NULL AND finished_at IS NULL)
        OR (status='running' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL AND finished_at IS NULL)
        OR (status IN ('completed','failed') AND claim_token IS NULL AND finished_at IS NOT NULL){run_cancel});
    ALTER TABLE rag_generative_attempts
      ADD CONSTRAINT rag_generative_attempts_status_check CHECK(status IN ('pending','running','completed','failed','interrupted'{extra})),
      ADD CONSTRAINT rag_generative_attempts_check CHECK(
        (status='pending' AND claim_token IS NULL AND finished_at IS NULL)
        OR (status='running' AND claim_token IS NOT NULL AND finished_at IS NULL)
        OR (status IN ('completed','failed','interrupted') AND finished_at IS NOT NULL){attempt_cancel});
    """)


def upgrade() -> None:
    op.execute("""
    ALTER TABLE rag_generative_runs
      ADD COLUMN cancelled_by uuid REFERENCES users(id),
      ADD COLUMN cancelled_at timestamptz,
      ADD COLUMN cancellation_reason varchar(80),
      ADD CONSTRAINT ck_rag_generative_runs_cancellation CHECK(
        (status='cancelled' AND cancelled_by IS NOT NULL AND cancelled_by=owner_id
         AND cancelled_at IS NOT NULL AND cancelled_at=finished_at
         AND cancellation_reason IS NOT NULL AND cancellation_reason='user_requested')
        OR (status<>'cancelled' AND cancelled_by IS NULL AND cancelled_at IS NULL
            AND cancellation_reason IS NULL));
    """)
    _status_constraints(cancel=True)
    run_guard = OLD_RUN_GUARD.replace(
        "  IF TG_OP='UPDATE' AND\n", RUN_CANCEL_GUARD + "  IF TG_OP='UPDATE' AND\n", 1,
    ).replace(
        "'dispatched_at']", "'dispatched_at','cancelled_by','cancelled_at','cancellation_reason']",
    )
    op.execute(run_guard)
    op.execute(OLD_ATTEMPT_GUARD.replace(
        "  IF NOT EXISTS(SELECT 1 FROM rag_evaluation_dataset_cases",
        ATTEMPT_CANCEL_GUARD + "  IF NOT EXISTS(SELECT 1 FROM rag_evaluation_dataset_cases", 1,
    ))
    op.execute("""
    CREATE FUNCTION rag_generative_cancel_complete() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF EXISTS(SELECT 1 FROM rag_generative_attempts a WHERE a.run_id=NEW.id
        AND (a.status<>'cancelled' OR a.finished_at IS DISTINCT FROM NEW.cancelled_at)) THEN
        RAISE EXCEPTION 'generative cancellation must include every unstarted attempt';
      END IF;
      RETURN NULL;
    END $$;
    CREATE CONSTRAINT TRIGGER rag_generative_cancel_complete AFTER UPDATE OF status
      ON rag_generative_runs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      WHEN (NEW.status='cancelled') EXECUTE FUNCTION rag_generative_cancel_complete();
    """)


def downgrade() -> None:
    # Once cancellation evidence exists it must be retained; no forced status rewriting.
    op.execute("""
    DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM rag_generative_runs WHERE status='cancelled'
        OR cancelled_by IS NOT NULL OR cancelled_at IS NOT NULL OR cancellation_reason IS NOT NULL)
        OR EXISTS(SELECT 1 FROM rag_generative_attempts WHERE status='cancelled') THEN
        RAISE EXCEPTION 'Cannot downgrade while generative cancellation evidence exists';
      END IF;
    END $$;
    DROP TRIGGER rag_generative_cancel_complete ON rag_generative_runs;
    DROP FUNCTION rag_generative_cancel_complete();
    """)
    op.execute(OLD_RUN_GUARD)
    op.execute(OLD_ATTEMPT_GUARD)
    _status_constraints(cancel=False)
    op.execute("""
    ALTER TABLE rag_generative_runs DROP CONSTRAINT ck_rag_generative_runs_cancellation,
      DROP COLUMN cancelled_by, DROP COLUMN cancelled_at, DROP COLUMN cancellation_reason;
    """)
