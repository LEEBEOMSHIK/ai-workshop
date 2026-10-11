"""Add fail-closed transmission phase, cluster gate and immutable recovery receipt."""

from alembic import op

revision = "0061_alias_recovery"
down_revision = "0060_first_question"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE rag_alias_operations ADD COLUMN phase VARCHAR(24) NOT NULL DEFAULT 'legacy_unknown';
ALTER TABLE rag_alias_operations ADD CONSTRAINT ck_rag_alias_phase
    CHECK (phase IN ('legacy_unknown', 'reserved', 'dispatching'));
ALTER TABLE rag_alias_operations DROP CONSTRAINT ck_rag_alias_state;
ALTER TABLE rag_alias_operations ADD CONSTRAINT ck_rag_alias_state CHECK (
    (state = 'open' AND closed_at IS NULL AND result_code IS NULL) OR
    (state = 'closed' AND closed_at IS NOT NULL AND result_code IS NOT NULL AND result_code IN
        ('confirmed', 'not_dispatched', 'recovered_terminated'))
);
ALTER TABLE rag_alias_operations ADD CONSTRAINT ck_rag_alias_terminal_phase CHECK (
    result_code IS NULL OR
    (result_code = 'not_dispatched' AND phase = 'reserved') OR
    (result_code IN ('confirmed', 'recovered_terminated') AND
     phase IN ('legacy_unknown', 'dispatching'))
);
CREATE TABLE rag_alias_cluster_gates (
    cluster_uuid VARCHAR(128) PRIMARY KEY,
    state VARCHAR(16) NOT NULL DEFAULT 'admitted',
    revision INTEGER NOT NULL DEFAULT 0,
    request_id UUID UNIQUE,
    actor_id UUID REFERENCES users(id),
    operation_id UUID REFERENCES rag_alias_operations(id),
    snapshot_sha256 VARCHAR(64),
    CONSTRAINT ck_rag_alias_gate_cluster CHECK (cluster_uuid ~ '^[A-Za-z0-9_-]{1,128}$'),
    CONSTRAINT ck_rag_alias_gate_state CHECK (state IN ('admitted', 'frozen')),
    CONSTRAINT ck_rag_alias_gate_revision CHECK (revision >= 0),
    CONSTRAINT ck_rag_alias_gate_claim CHECK (
      (request_id IS NULL AND actor_id IS NULL AND operation_id IS NULL AND
       snapshot_sha256 IS NULL AND revision = 0 AND state = 'admitted') OR
      (request_id IS NOT NULL AND actor_id IS NOT NULL AND operation_id IS NOT NULL AND
       snapshot_sha256 IS NOT NULL AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND revision > 0)
    )
);
CREATE TABLE rag_alias_recovery_receipts (
    request_id UUID PRIMARY KEY,
    operation_id UUID NOT NULL UNIQUE REFERENCES rag_alias_operations(id),
    actor_id UUID NOT NULL REFERENCES users(id),
    cluster_uuid VARCHAR(128) NOT NULL,
    snapshot_sha256 VARCHAR(64) NOT NULL,
    gate_revision INTEGER NOT NULL,
    result_code VARCHAR(32) NOT NULL,
    proof_kind VARCHAR(48) NOT NULL,
    schema_version INTEGER NOT NULL,
    proof JSONB NOT NULL,
    proof_sha256 VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_rag_alias_receipt_result CHECK
        (result_code IN ('not_dispatched', 'recovered_terminated')),
    CONSTRAINT ck_rag_alias_receipt_digest CHECK
        (snapshot_sha256 ~ '^[0-9a-f]{64}$' AND proof_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_rag_alias_receipt_revision CHECK (gate_revision > 0),
    CONSTRAINT ck_rag_alias_receipt_proof CHECK (
      schema_version = 1 AND jsonb_typeof(proof) = 'object' AND
      ((result_code = 'not_dispatched' AND proof_kind = 'reserved_cas' AND proof = '{}'::jsonb) OR
       (result_code = 'recovered_terminated' AND
        proof_kind = 'local_single_node_controlled_restart' AND
        proof->>'proof_kind' = proof_kind AND (proof->>'schema_version')::integer = 1 AND
        proof->>'request_id' = request_id::text AND
        proof->>'operation_id' = operation_id::text AND
        proof->>'snapshot_sha256' = snapshot_sha256 AND
        proof->>'cluster_uuid' = cluster_uuid))
    )
);
CREATE OR REPLACE FUNCTION guard_rag_alias_operation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'immutable alias operation';
    END IF;
    IF (NEW.id, NEW.store_id, NEW.cluster_uuid, NEW.alias, NEW.indexing_profile_id,
        NEW.document_processing_profile_id, NEW.targets, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.store_id, OLD.cluster_uuid, OLD.alias, OLD.indexing_profile_id,
        OLD.document_processing_profile_id, OLD.targets, OLD.created_at)
       OR (OLD.state = 'closed' AND NEW IS DISTINCT FROM OLD)
       OR (NEW.phase IS DISTINCT FROM OLD.phase AND NOT
           (OLD.state = 'open' AND NEW.state = 'open' AND
            OLD.phase = 'reserved' AND NEW.phase = 'dispatching')) THEN
        RAISE EXCEPTION 'immutable alias operation or invalid dispatch transition';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER guard_rag_alias_operation_delete BEFORE DELETE ON rag_alias_operations
FOR EACH ROW EXECUTE FUNCTION guard_rag_alias_operation();

CREATE FUNCTION guard_rag_alias_gate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE terminal rag_alias_operations%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'immutable alias gate';
    ELSIF TG_OP = 'INSERT' THEN
        IF NEW.state <> 'admitted' OR NEW.revision <> 0 OR NEW.request_id IS NOT NULL THEN
            RAISE EXCEPTION 'gate must initialize admitted';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.cluster_uuid IS DISTINCT FROM OLD.cluster_uuid THEN
        RAISE EXCEPTION 'immutable gate cluster';
    END IF;
    IF NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
    IF OLD.state = 'frozen' THEN
        IF NEW.state <> 'admitted' OR
           (NEW.request_id, NEW.actor_id, NEW.operation_id, NEW.snapshot_sha256, NEW.revision)
           IS DISTINCT FROM
           (OLD.request_id, OLD.actor_id, OLD.operation_id, OLD.snapshot_sha256, OLD.revision) THEN
            RAISE EXCEPTION 'immutable frozen claim';
        END IF;
        SELECT * INTO terminal FROM rag_alias_operations WHERE id = OLD.operation_id;
        IF terminal.state <> 'closed' OR terminal.cluster_uuid <> OLD.cluster_uuid THEN
            RAISE EXCEPTION 'open operation cannot release';
        END IF;
        IF terminal.result_code <> 'confirmed' AND NOT EXISTS (
            SELECT 1 FROM rag_alias_recovery_receipts r WHERE r.operation_id = OLD.operation_id
              AND r.request_id = OLD.request_id AND r.actor_id = OLD.actor_id
              AND r.snapshot_sha256 = OLD.snapshot_sha256 AND r.gate_revision = OLD.revision
        ) THEN RAISE EXCEPTION 'release requires exact receipt'; END IF;
    ELSIF NEW.state <> 'frozen' OR NEW.revision <> OLD.revision + 1 OR
          NEW.request_id IS NULL OR NEW.request_id IS NOT DISTINCT FROM OLD.request_id THEN
        RAISE EXCEPTION 'invalid gate acquisition';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER guard_rag_alias_gate BEFORE INSERT OR UPDATE OR DELETE ON rag_alias_cluster_gates
FOR EACH ROW EXECUTE FUNCTION guard_rag_alias_gate();

CREATE FUNCTION guard_rag_alias_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE claim rag_alias_cluster_gates%ROWTYPE;
DECLARE expected_keys TEXT[] := ARRAY[
  'client_inventory_sha256','clients_terminated_at','cluster_uuid','config_sha256','container_id',
  'deployment_history_sha256','new_ephemeral_id','new_jvm_start_at','old_ephemeral_id',
  'old_jvm_start_at','operation_id','proof_kind','protected_mount_sha256','request_id',
  'schema_version','server_started_at','server_stopped_at','snapshot_sha256','stable_node_id',
  'verified_at'];
BEGIN
    IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'immutable alias recovery receipt'; END IF;
    SELECT * INTO claim FROM rag_alias_cluster_gates
      WHERE cluster_uuid = NEW.cluster_uuid FOR UPDATE;
    IF NOT FOUND OR claim.state <> 'frozen' OR
       (claim.request_id, claim.actor_id, claim.operation_id, claim.snapshot_sha256, claim.revision)
       IS DISTINCT FROM
       (NEW.request_id, NEW.actor_id, NEW.operation_id, NEW.snapshot_sha256, NEW.gate_revision) THEN
        RAISE EXCEPTION 'receipt requires exact frozen claim';
    END IF;
    IF NEW.result_code = 'recovered_terminated' AND
       (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(NEW.proof) k)
       IS DISTINCT FROM expected_keys THEN
        RAISE EXCEPTION 'unallowlisted proof facts';
    END IF;
    IF NEW.result_code = 'recovered_terminated' AND EXISTS (
      SELECT 1 FROM jsonb_each(NEW.proof) fact WHERE
        (fact.key = 'schema_version' AND jsonb_typeof(fact.value) <> 'number') OR
        (fact.key <> 'schema_version' AND jsonb_typeof(fact.value) <> 'string')
    ) THEN RAISE EXCEPTION 'invalid typed proof facts'; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER guard_rag_alias_receipt BEFORE INSERT OR UPDATE OR DELETE
ON rag_alias_recovery_receipts FOR EACH ROW EXECUTE FUNCTION guard_rag_alias_receipt();

CREATE FUNCTION check_rag_alias_recovery_integrity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE operation rag_alias_operations%ROWTYPE;
DECLARE evidence rag_alias_recovery_receipts%ROWTYPE;
DECLARE operation_uuid UUID;
BEGIN
    IF TG_TABLE_NAME = 'rag_alias_operations' THEN operation_uuid := NEW.id;
    ELSE operation_uuid := NEW.operation_id; END IF;
    SELECT * INTO operation FROM rag_alias_operations WHERE id = operation_uuid;
    SELECT * INTO evidence FROM rag_alias_recovery_receipts WHERE operation_id = operation_uuid;
    IF operation.result_code IN ('not_dispatched', 'recovered_terminated') THEN
        IF evidence.request_id IS NULL OR operation.state <> 'closed' OR
           evidence.cluster_uuid <> operation.cluster_uuid OR
           evidence.result_code <> operation.result_code OR
           evidence.created_at <> operation.closed_at THEN
            RAISE EXCEPTION 'recovery closure requires exact atomic receipt';
        END IF;
    ELSIF evidence.request_id IS NOT NULL THEN
        RAISE EXCEPTION 'receipt requires recovery closure';
    END IF;
    RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER check_rag_alias_recovery_operation AFTER INSERT OR UPDATE
ON rag_alias_operations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION check_rag_alias_recovery_integrity();
CREATE CONSTRAINT TRIGGER check_rag_alias_recovery_receipt AFTER INSERT
ON rag_alias_recovery_receipts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION check_rag_alias_recovery_integrity();
""")


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM rag_alias_operations WHERE phase <> 'legacy_unknown') OR
       EXISTS (SELECT 1 FROM rag_alias_recovery_receipts) OR
       EXISTS (SELECT 1 FROM rag_alias_cluster_gates) THEN
        RAISE EXCEPTION 'new alias data, evidence or maintenance gate prevents downgrade';
    END IF;
END $$;
DROP TRIGGER check_rag_alias_recovery_operation ON rag_alias_operations;
DROP TABLE rag_alias_recovery_receipts;
DROP TABLE rag_alias_cluster_gates;
DROP FUNCTION check_rag_alias_recovery_integrity();
DROP FUNCTION guard_rag_alias_receipt();
DROP FUNCTION guard_rag_alias_gate();
DROP TRIGGER guard_rag_alias_operation_delete ON rag_alias_operations;
ALTER TABLE rag_alias_operations DROP CONSTRAINT ck_rag_alias_terminal_phase;
ALTER TABLE rag_alias_operations DROP CONSTRAINT ck_rag_alias_phase;
ALTER TABLE rag_alias_operations DROP CONSTRAINT ck_rag_alias_state;
ALTER TABLE rag_alias_operations DROP COLUMN phase;
ALTER TABLE rag_alias_operations ADD CONSTRAINT ck_rag_alias_state CHECK (
    (state = 'open' AND closed_at IS NULL AND result_code IS NULL) OR
    (state = 'closed' AND closed_at IS NOT NULL AND
     result_code IS NOT NULL AND result_code = 'confirmed')
);
CREATE OR REPLACE FUNCTION guard_rag_alias_operation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.id, NEW.store_id, NEW.cluster_uuid, NEW.alias, NEW.indexing_profile_id,
        NEW.document_processing_profile_id, NEW.targets, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.store_id, OLD.cluster_uuid, OLD.alias, OLD.indexing_profile_id,
        OLD.document_processing_profile_id, OLD.targets, OLD.created_at)
       OR (OLD.state = 'closed' AND NEW IS DISTINCT FROM OLD) THEN
        RAISE EXCEPTION 'immutable alias operation';
    END IF;
    RETURN NEW;
END $$;
""")
