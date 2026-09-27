"""Immutable generative evaluation inputs and individually fenced attempts."""

# ruff: noqa: E501 -- Keep SQL state predicates readable as complete expressions.

from alembic import op

revision = "0055_generative_evaluation"
down_revision = "0054_rag_executions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE rag_generative_policies (
      id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES users(id),
      name varchar(180) NOT NULL, version integer NOT NULL CHECK(version > 0),
      definition jsonb NOT NULL, digest varchar(64) NOT NULL CHECK(length(digest)=64),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE(owner_id,name,version)
    );
    CREATE TABLE rag_generative_runs (
      id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES users(id),
      request_id uuid NOT NULL, UNIQUE(owner_id,request_id),
      dataset_snapshot_id uuid NOT NULL REFERENCES rag_evaluation_datasets(id),
      policy_id uuid NOT NULL REFERENCES rag_generative_policies(id),
      metric_version varchar(32) NOT NULL CHECK(metric_version='generative-v1'),
      snapshot jsonb NOT NULL, snapshot_bytes bytea NOT NULL,
      snapshot_digest varchar(64) NOT NULL,
      expected_rules jsonb NOT NULL, rules_digest varchar(64) NOT NULL,
      repetition_count integer NOT NULL CHECK(repetition_count BETWEEN 2 AND 5),
      input_approval jsonb,
      status varchar(32) NOT NULL CHECK(status IN ('pending','running','completed','failed')),
      claim_token uuid, claimed_at timestamptz, finished_at timestamptz,
      runtime_environment jsonb,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CHECK(encode(sha256(snapshot_bytes),'hex')=snapshot_digest),
      CHECK(convert_from(snapshot_bytes,'UTF8')::jsonb=snapshot),
      CHECK((status='pending' AND claim_token IS NULL AND finished_at IS NULL)
        OR (status='running' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL
            AND finished_at IS NULL)
        OR (status IN ('completed','failed') AND claim_token IS NULL AND finished_at IS NOT NULL))
    );
    CREATE INDEX ix_rag_generative_runs_owner ON rag_generative_runs(owner_id,created_at);
    CREATE TABLE rag_generative_attempts (
      id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES rag_generative_runs(id),
      configuration_version_id uuid NOT NULL REFERENCES rag_configuration_versions(id),
      case_id uuid NOT NULL, repetition integer NOT NULL CHECK(repetition>=0),
      attempt_number integer NOT NULL CHECK(attempt_number>0),
      execution_id uuid NOT NULL UNIQUE, claim_token uuid,
      status varchar(32) NOT NULL CHECK(status IN ('pending','running','completed','failed','interrupted')),
      result jsonb, result_bytes bytea, result_digest varchar(64),
      error_code varchar(100) CHECK(error_code ~ '^[a-z0-9_]+$'), finished_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(run_id,configuration_version_id,case_id,repetition,attempt_number),
      CHECK((status='pending' AND claim_token IS NULL AND finished_at IS NULL)
        OR (status='running' AND claim_token IS NOT NULL AND finished_at IS NULL)
        OR (status IN ('completed','failed','interrupted') AND finished_at IS NOT NULL)),
      CHECK(status<>'completed' OR (result IS NOT NULL AND result_bytes IS NOT NULL
          AND result_digest IS NOT NULL)),
      CHECK(result IS NULL OR (encode(sha256(result_bytes),'hex')=result_digest
          AND convert_from(result_bytes,'UTF8')::jsonb=result
          AND result->'observation'->>'execution_id'=execution_id::text))
    );
    ALTER TABLE rag_executions ADD CONSTRAINT fk_rag_execution_attempt
      FOREIGN KEY(evaluation_attempt_id) REFERENCES rag_generative_attempts(id);
    CREATE TABLE rag_generative_judgments (
      id uuid PRIMARY KEY, attempt_id uuid NOT NULL REFERENCES rag_generative_attempts(id),
      reviewer_id uuid NOT NULL REFERENCES users(id), result_digest varchar(64) NOT NULL,
      rule_digest varchar(64) NOT NULL, status varchar(24) NOT NULL
        CHECK(status IN ('passed','failed','unreviewed')), reason varchar(1000) NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
    );
    """)
    op.execute("""
    CREATE FUNCTION rag_generative_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'generative evaluation evidence is immutable';
    END $$;
    CREATE TRIGGER rag_generative_policy_immutable BEFORE UPDATE OR DELETE
      ON rag_generative_policies FOR EACH ROW EXECUTE FUNCTION rag_generative_immutable();
    CREATE TRIGGER rag_generative_judgment_immutable BEFORE UPDATE OR DELETE
      ON rag_generative_judgments FOR EACH ROW EXECUTE FUNCTION rag_generative_immutable();
    CREATE FUNCTION rag_generative_run_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN
        RAISE EXCEPTION 'generative run removal requires an authorized retention operation';
      END IF;
      IF TG_OP='UPDATE' AND
        (to_jsonb(NEW)-ARRAY['status','claim_token','claimed_at','finished_at','runtime_environment','updated_at'])
        IS DISTINCT FROM
        (to_jsonb(OLD)-ARRAY['status','claim_token','claimed_at','finished_at','runtime_environment','updated_at']) THEN
        RAISE EXCEPTION 'generative run input is immutable';
      END IF;
      IF NOT EXISTS(SELECT 1 FROM rag_evaluation_datasets d JOIN rag_generative_policies p
        ON p.id=NEW.policy_id WHERE d.id=NEW.dataset_snapshot_id
        AND d.owner_id=NEW.owner_id AND p.owner_id=NEW.owner_id) THEN
        RAISE EXCEPTION 'generative input ownership mismatch';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER rag_generative_run_guard BEFORE INSERT OR UPDATE OR DELETE
      ON rag_generative_runs FOR EACH ROW EXECUTE FUNCTION rag_generative_run_guard();
    CREATE FUNCTION rag_generative_attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
    CREATE TRIGGER rag_generative_attempt_guard BEFORE INSERT OR UPDATE OR DELETE
      ON rag_generative_attempts FOR EACH ROW EXECUTE FUNCTION rag_generative_attempt_guard();
    """)


def downgrade() -> None:
    raise RuntimeError("Generative evidence removal requires a reviewed retention migration.")
