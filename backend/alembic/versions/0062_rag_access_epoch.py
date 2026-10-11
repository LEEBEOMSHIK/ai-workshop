"""Persist exact access-epoch executions; never perform an ES cutover."""

from alembic import op

revision = "0062_rag_access_epoch"
down_revision = "0061_alias_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE rag_access_epochs (
 id UUID PRIMARY KEY,
 request_id UUID NOT NULL CONSTRAINT uq_rag_access_epoch_request UNIQUE,
 operation_id UUID NOT NULL CONSTRAINT fk_rag_access_epoch_operation REFERENCES
  rag_alias_operations(id),
 actor_id UUID NOT NULL CONSTRAINT fk_rag_access_epoch_actor REFERENCES users(id),
 store_id VARCHAR(80) NOT NULL,
 cluster_uuid VARCHAR(128) NOT NULL,
 snapshot_sha256 VARCHAR(64) NOT NULL,
 gate_revision INTEGER NOT NULL CONSTRAINT ck_rag_access_epoch_gate_revision
  CHECK (gate_revision > 0),
 ordinal INTEGER NOT NULL,
 previous_floor INTEGER NOT NULL,
 phase VARCHAR(24) NOT NULL,
 original JSONB NOT NULL,
 verified JSONB,
 manifests JSONB,
 stopped_sequence INTEGER,
 retired_sequence INTEGER,
 created_at TIMESTAMPTZ NOT NULL,
 verified_at TIMESTAMPTZ,
 receipted_at TIMESTAMPTZ,
 CONSTRAINT ck_rag_access_epoch_ordinal CHECK (ordinal > 0 AND previous_floor >= 0 AND ordinal >
  previous_floor),
 CONSTRAINT ck_rag_access_epoch_phase CHECK (phase IN
  ('prepared','old_stopped','old_retired','secured_started','verified','receipted')),
 CONSTRAINT ck_rag_access_epoch_manifest_digest CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
 CONSTRAINT ck_rag_access_epoch_store CHECK (store_id ~ '^[a-z][a-z0-9_]{0,79}$'),
 CONSTRAINT ck_rag_access_epoch_cluster CHECK (cluster_uuid ~ '^[A-Za-z0-9_-]{1,128}$')
);
CREATE UNIQUE INDEX uq_rag_access_epoch_active_cluster ON rag_access_epochs(cluster_uuid) WHERE
 phase <> 'receipted' ;
CREATE UNIQUE INDEX uq_rag_access_epoch_cluster_ordinal ON rag_access_epochs(cluster_uuid,ordinal);
CREATE TABLE rag_access_epoch_executions (
 id UUID PRIMARY KEY,
 epoch_id UUID NOT NULL CONSTRAINT uq_rag_access_epoch_execution UNIQUE
   CONSTRAINT fk_rag_access_epoch_execution REFERENCES rag_access_epochs(id),
 executor_generation VARCHAR(128) NOT NULL,
 created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE rag_access_epoch_events (
 id UUID PRIMARY KEY,
 execution_id UUID NOT NULL CONSTRAINT fk_rag_access_epoch_event_execution REFERENCES
  rag_access_epoch_executions(id),
 action_id UUID NOT NULL,
 sequence INTEGER NOT NULL,
 action_sequence INTEGER NOT NULL,
 kind VARCHAR(32) NOT NULL,
 outcome VARCHAR(16) NOT NULL,
 expected_json TEXT NOT NULL,
 executor_generation VARCHAR(128) NOT NULL,
 manifest_json TEXT,
 observed_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT ck_rag_access_epoch_event_outcome CHECK (outcome IN ('pending','unknown','settled')),
 CONSTRAINT ck_rag_access_epoch_event_sequence CHECK (sequence > 0 AND action_sequence > 0),
 CONSTRAINT ck_rag_access_epoch_event_json CHECK (jsonb_typeof(expected_json::jsonb) = 'object' AND
   (manifest_json IS NULL OR jsonb_typeof(manifest_json::jsonb) = 'object')),
 CONSTRAINT uq_rag_access_epoch_event_sequence UNIQUE(execution_id,sequence),
 CONSTRAINT uq_rag_access_epoch_action_outcome UNIQUE(action_id,outcome)
);
CREATE TABLE rag_access_epoch_floors (
 cluster_uuid VARCHAR(128) PRIMARY KEY,
 store_id VARCHAR(80) NOT NULL,
 ordinal INTEGER NOT NULL,
 epoch_id UUID NOT NULL CONSTRAINT fk_rag_access_epoch_floor_epoch REFERENCES rag_access_epochs(id)
  CONSTRAINT uq_rag_access_epoch_floor_epoch UNIQUE,
 identity JSONB NOT NULL,
 CONSTRAINT ck_rag_access_epoch_floor CHECK (ordinal > 0)
);
ALTER TABLE rag_alias_recovery_receipts ADD COLUMN access_epoch_id UUID;
ALTER TABLE rag_alias_recovery_receipts ADD COLUMN execution_id UUID;
ALTER TABLE rag_alias_recovery_receipts ADD CONSTRAINT fk_rag_alias_receipt_access_epoch
 FOREIGN KEY(access_epoch_id) REFERENCES rag_access_epochs(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE rag_alias_recovery_receipts ADD CONSTRAINT fk_rag_alias_receipt_execution
 FOREIGN KEY(execution_id) REFERENCES rag_access_epoch_executions(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE rag_alias_recovery_receipts ADD CONSTRAINT ck_rag_alias_receipt_epoch_binding CHECK (
 (schema_version=1 AND access_epoch_id IS NULL AND execution_id IS NULL) OR
 (schema_version=2 AND access_epoch_id IS NOT NULL AND execution_id IS NOT NULL)
);
ALTER TABLE rag_alias_recovery_receipts DROP CONSTRAINT ck_rag_alias_receipt_proof;
ALTER TABLE rag_alias_recovery_receipts ADD CONSTRAINT ck_rag_alias_receipt_proof CHECK (
 jsonb_typeof(proof)='object' AND (
 (schema_version=1 AND (
   (result_code='not_dispatched' AND proof_kind='reserved_cas' AND proof='{}'::jsonb) OR
   (result_code='recovered_terminated' AND proof_kind='local_single_node_controlled_restart' AND
    proof->>'proof_kind'=proof_kind AND (proof->>'schema_version')::integer=1 AND
    proof->>'request_id'=request_id::text AND proof->>'operation_id'=operation_id::text AND
    proof->>'snapshot_sha256'=snapshot_sha256 AND proof->>'cluster_uuid'=cluster_uuid))) OR
 (schema_version=2 AND result_code='recovered_terminated' AND
  proof_kind='local_single_node_access_epoch' AND
   proof->>'proof_kind'=proof_kind AND proof->>'schema_version'='2' AND
   proof->>'request_id'=request_id::text AND proof->>'operation_id'=operation_id::text AND
   proof->>'actor_id'=actor_id::text AND proof->>'cluster_uuid'=cluster_uuid AND
   proof->>'snapshot_sha256'=snapshot_sha256 AND proof->>'gate_revision'=gate_revision::text))
);
CREATE FUNCTION rag_access_epoch_canonical_proof(value JSONB) RETURNS TEXT
 LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT '{' || string_agg(to_json(k)::text || ':' || v::text, ',' ORDER BY k) || '}'
 FROM jsonb_each(value) AS item(k,v)
$$;
CREATE FUNCTION validate_rag_access_epoch_proof(value JSONB) RETURNS BOOLEAN
 LANGUAGE plpgsql AS $$
DECLARE uuid_keys TEXT[] :=
 ARRAY['access_epoch_id','actor_id','execution_id','operation_id','request_id'];
DECLARE integer_keys TEXT[] := ARRAY['gate_revision','minimum_access_epoch','schema_version'];
DECLARE identifier_keys TEXT[] :=
 ARRAY['cluster_uuid','new_ephemeral_id','old_ephemeral_id','stable_node_id','store_id'];
DECLARE time_keys TEXT[] := ARRAY['access_verified_at','new_jvm_start_at','new_server_started_at',
 'old_container_retired_at','old_jvm_start_at','old_server_stopped_at','verified_at'];
DECLARE digest_keys TEXT[] :=
 ARRAY['auth_policy_sha256','control_settlement_sha256','credential_deployment_sha256',
 'daemon_identity_sha256'
  ,'deployment_history_sha256','new_config_sha256','new_container_id','new_deployment_sha256',
 'old_config_sha256','old_container_id','old_deployment_sha256','original_volume_identity_sha256',
 'protected_image_sha256'
  ,'protected_mount_sha256','route_policy_sha256','snapshot_sha256','tls_public_ca_sha256'];
DECLARE expected TEXT[];
DECLARE key TEXT;
BEGIN
 expected := uuid_keys || integer_keys || identifier_keys || time_keys || digest_keys ||
  ARRAY['proof_kind'];
 IF jsonb_typeof(value) IS DISTINCT FROM 'object' OR
   (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(value) k) IS DISTINCT FROM
   (SELECT array_agg(k ORDER BY k) FROM unnest(expected) k) THEN RETURN FALSE; END IF;
 FOREACH key IN ARRAY uuid_keys LOOP
   IF jsonb_typeof(value->key)<>'string' OR value->>key !~
    '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   THEN RETURN FALSE; END IF;
 END LOOP;
 FOREACH key IN ARRAY digest_keys LOOP
   IF jsonb_typeof(value->key)<>'string' OR value->>key !~ '^[0-9a-f]{64}$' THEN RETURN FALSE; END
    IF;
 END LOOP;
 FOREACH key IN ARRAY identifier_keys LOOP
   IF jsonb_typeof(value->key)<>'string' OR value->>key !~ '^[A-Za-z0-9_-]{1,128}$' THEN RETURN
    FALSE; END IF;
 END LOOP;
 IF value->>'store_id' !~ '^[a-z][a-z0-9_]{0,79}$' THEN RETURN FALSE; END IF;
 FOREACH key IN ARRAY integer_keys LOOP
   IF jsonb_typeof(value->key)<>'number' OR value->>key !~ '^[1-9][0-9]*$' THEN RETURN FALSE; END
    IF;
 END LOOP;
 IF value->>'schema_version'<>'2' OR jsonb_typeof(value->'proof_kind')<>'string' OR
   value->>'proof_kind'<>'local_single_node_access_epoch' OR
   value->>'old_container_id'=value->>'new_container_id' OR
   value->>'old_ephemeral_id'=value->>'new_ephemeral_id' THEN RETURN FALSE; END IF;
 FOREACH key IN ARRAY time_keys LOOP
   IF jsonb_typeof(value->key)<>'string' OR
     value->>key !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[.][0-9]{6}[+]00:00$'
   THEN RETURN FALSE; END IF;
 END LOOP;
 RETURN (value->>'old_jvm_start_at')::timestamptz <= (value->>'old_server_stopped_at')::timestamptz
  AND
   (value->>'old_server_stopped_at')::timestamptz <=
    (value->>'old_container_retired_at')::timestamptz AND
   (value->>'old_container_retired_at')::timestamptz <
    (value->>'new_server_started_at')::timestamptz AND
   (value->>'new_server_started_at')::timestamptz <= (value->>'new_jvm_start_at')::timestamptz AND
   (value->>'new_jvm_start_at')::timestamptz <= (value->>'access_verified_at')::timestamptz AND
   (value->>'access_verified_at')::timestamptz <= (value->>'verified_at')::timestamptz AND
   (value->>'verified_at')::timestamptz <= clock_timestamp();
 EXCEPTION WHEN OTHERS THEN RETURN FALSE;
END $$;
CREATE OR REPLACE FUNCTION guard_rag_alias_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE claim rag_alias_cluster_gates%ROWTYPE;
DECLARE epoch rag_access_epochs%ROWTYPE;
DECLARE execution rag_access_epoch_executions%ROWTYPE;
DECLARE expected_keys TEXT[] := ARRAY[
 'client_inventory_sha256','clients_terminated_at','cluster_uuid','config_sha256','container_id',
 'deployment_history_sha256','new_ephemeral_id','new_jvm_start_at','old_ephemeral_id',
 'old_jvm_start_at','operation_id','proof_kind','protected_mount_sha256','request_id',
 'schema_version'
  ,'server_started_at','server_stopped_at','snapshot_sha256','stable_node_id','verified_at'];
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'immutable alias recovery receipt'; END IF;
 SELECT * INTO claim FROM rag_alias_cluster_gates WHERE cluster_uuid=NEW.cluster_uuid FOR UPDATE;
 IF NOT FOUND OR claim.state<>'frozen' OR
   (claim.request_id,claim.actor_id,claim.operation_id,claim.snapshot_sha256,claim.revision) IS
    DISTINCT FROM
   (NEW.request_id,NEW.actor_id,NEW.operation_id,NEW.snapshot_sha256,NEW.gate_revision)
 THEN RAISE EXCEPTION 'receipt requires exact frozen claim'; END IF;
 IF NEW.schema_version=1 THEN
   IF NEW.result_code='recovered_terminated' AND
    (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(NEW.proof) k) IS DISTINCT FROM
     expected_keys
   THEN RAISE EXCEPTION 'unallowlisted proof facts'; END IF;
   IF NEW.result_code='recovered_terminated' AND EXISTS (
    SELECT 1 FROM jsonb_each(NEW.proof) fact WHERE
    (fact.key='schema_version' AND jsonb_typeof(fact.value)<>'number') OR
    (fact.key<>'schema_version' AND jsonb_typeof(fact.value)<>'string'))
   THEN RAISE EXCEPTION 'invalid typed proof facts'; END IF;
 ELSIF NEW.schema_version=2 THEN
   IF NOT validate_rag_access_epoch_proof(NEW.proof) THEN RAISE EXCEPTION
    'invalid access epoch proof' ; END IF;
   NEW.access_epoch_id := (NEW.proof->>'access_epoch_id')::uuid;
   NEW.execution_id := (NEW.proof->>'execution_id')::uuid;
   SELECT * INTO epoch FROM rag_access_epochs WHERE id=NEW.access_epoch_id FOR UPDATE;
   SELECT * INTO execution FROM rag_access_epoch_executions WHERE id=NEW.execution_id FOR UPDATE;
   IF epoch.id IS NULL OR execution.epoch_id IS DISTINCT FROM epoch.id OR
     epoch.phase NOT IN ('verified','receipted') OR epoch.verified IS DISTINCT FROM NEW.proof OR
     (epoch.request_id,epoch.actor_id,epoch.operation_id,epoch.snapshot_sha256,epoch.gate_revision,epoch.cluster_uuid)
      IS DISTINCT FROM
     (NEW.request_id,NEW.actor_id,NEW.operation_id,NEW.snapshot_sha256,NEW.gate_revision,NEW.cluster_uuid)
      OR
     NEW.proof->>'minimum_access_epoch' <> epoch.ordinal::text OR
     NEW.proof_sha256 <>
      encode(sha256(convert_to(rag_access_epoch_canonical_proof(NEW.proof),'UTF8')),'hex')
   THEN RAISE EXCEPTION 'unbound access epoch receipt'; END IF;
 ELSE RAISE EXCEPTION 'unknown recovery schema'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION guard_rag_access_epoch_event() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE execution rag_access_epoch_executions%ROWTYPE;
DECLARE prior rag_access_epoch_events%ROWTYPE;
DECLARE last_sequence INTEGER;
DECLARE next_kind TEXT;
DECLARE active_epoch rag_access_epochs%ROWTYPE;
DECLARE command_order TEXT[] := ARRAY['stop_registered_apps','stop_old','retire_old',
 'prepare_tls','start_bootstrap','bootstrap_admin','revoke_historical','issue_role_key',
 'stop_bootstrap','retire_bootstrap','start_secured','verify_access'];
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'immutable access epoch event'; END IF;
 SELECT * INTO execution FROM rag_access_epoch_executions WHERE id=NEW.execution_id FOR UPDATE;
 SELECT * INTO active_epoch FROM rag_access_epochs WHERE id=execution.epoch_id;
 SELECT coalesce(max(sequence),0) INTO last_sequence FROM rag_access_epoch_events WHERE
  execution_id=NEW.execution_id;
 IF execution.id IS NULL OR active_epoch.phase IN ('verified','receipted') OR
    NEW.executor_generation IS DISTINCT FROM execution.executor_generation OR
    NEW.sequence<>last_sequence+1 THEN RAISE EXCEPTION 'unbound access epoch event'; END IF;
 IF NEW.outcome='pending' THEN
   SELECT command_order[count(*)::integer+1] INTO next_kind
    FROM rag_access_epoch_events WHERE execution_id=NEW.execution_id AND outcome='settled';
   IF NEW.kind IS DISTINCT FROM next_kind THEN RAISE EXCEPTION 'invalid fixed command order';
   END IF;
   IF NEW.action_sequence<>NEW.sequence OR NEW.manifest_json IS NOT NULL OR EXISTS (
     SELECT 1 FROM rag_access_epoch_events e WHERE e.execution_id=NEW.execution_id AND
      e.outcome='pending' AND NOT EXISTS (
       SELECT 1 FROM rag_access_epoch_events settled WHERE settled.action_id=e.action_id AND
        settled.outcome='settled'))
   THEN RAISE EXCEPTION 'unsettled preceding control'; END IF;
 ELSE
   SELECT * INTO prior FROM rag_access_epoch_events WHERE action_id=NEW.action_id AND
    outcome='pending';
   IF prior.id IS NULL OR NEW.manifest_json IS NULL OR
     (prior.execution_id,prior.kind,prior.action_sequence,prior.expected_json,prior.executor_generation)
      IS DISTINCT FROM
     (NEW.execution_id,NEW.kind,NEW.action_sequence,NEW.expected_json,NEW.executor_generation) OR
     NEW.observed_at<prior.observed_at OR EXISTS (
       SELECT 1 FROM rag_access_epoch_events e WHERE e.action_id=NEW.action_id AND
        e.outcome='settled')
   THEN RAISE EXCEPTION 'unbound control settlement'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_rag_access_epoch_event BEFORE INSERT OR UPDATE OR DELETE ON
 rag_access_epoch_events
 FOR EACH ROW EXECUTE FUNCTION guard_rag_access_epoch_event();
CREATE FUNCTION guard_rag_access_epoch_transition() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE required_kind TEXT;
DECLARE linked_execution UUID;
DECLARE item RECORD;
DECLARE claim rag_alias_cluster_gates%ROWTYPE;
DECLARE operation rag_alias_operations%ROWTYPE;
DECLARE manifest_names TEXT[] := ARRAY['auth_policy','control_settlement','credential_deployment',
 'daemon_identity','deployment_history','new_config','new_deployment','old_config',
 'old_deployment','original_volume_identity','protected_image','protected_mount',
 'route_policy','tls_public_ca'];
DECLARE original_names TEXT[] := ARRAY['cluster_uuid','config_sha256','container_id',
 'daemon_sha256','deployment_sha256','ephemeral_id','image_sha256','jvm_start_at',
 'mount_sha256','stable_node_id','volume_sha256'];
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable access epoch'; END IF;
 IF TG_OP='INSERT' THEN
   IF NEW.phase<>'prepared' OR NEW.verified IS NOT NULL OR NEW.manifests IS NOT NULL THEN
     RAISE EXCEPTION 'invalid initial access epoch'; END IF;
   PERFORM 1 FROM users WHERE id=NEW.actor_id AND is_active AND role='owner' FOR UPDATE;
   IF NOT FOUND THEN RAISE EXCEPTION 'access epoch owner denied'; END IF;
   SELECT * INTO claim FROM rag_alias_cluster_gates
    WHERE cluster_uuid=NEW.cluster_uuid FOR UPDATE;
   SELECT * INTO operation FROM rag_alias_operations WHERE id=NEW.operation_id FOR UPDATE;
   IF claim.state IS DISTINCT FROM 'frozen' OR operation.state IS DISTINCT FROM 'open' OR
    operation.phase NOT IN ('legacy_unknown','dispatching') OR
    (claim.request_id,claim.actor_id,claim.operation_id,claim.snapshot_sha256,claim.revision)
     IS DISTINCT FROM
    (NEW.request_id,NEW.actor_id,NEW.operation_id,NEW.snapshot_sha256,NEW.gate_revision) OR
    (operation.cluster_uuid,operation.store_id) IS DISTINCT FROM
     (NEW.cluster_uuid,NEW.store_id) OR
    jsonb_typeof(NEW.original) IS DISTINCT FROM 'object' OR
    (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(NEW.original) k)
      IS DISTINCT FROM original_names OR
    NEW.original->>'cluster_uuid' IS DISTINCT FROM NEW.cluster_uuid
   THEN RAISE EXCEPTION 'unbound initial access epoch'; END IF;
   RETURN NEW;
 END IF;
 IF (NEW.id,NEW.request_id,NEW.operation_id,NEW.actor_id,NEW.store_id,NEW.cluster_uuid,
   NEW.snapshot_sha256,NEW.gate_revision,NEW.ordinal,NEW.previous_floor,NEW.original,NEW.created_at)
    IS DISTINCT FROM
   (OLD.id,OLD.request_id,OLD.operation_id,OLD.actor_id,OLD.store_id,OLD.cluster_uuid,
   OLD.snapshot_sha256,OLD.gate_revision,OLD.ordinal,OLD.previous_floor,OLD.original,OLD.created_at)
    OR
   (OLD.phase IN ('verified','receipted') AND
    (NEW.verified,NEW.manifests,NEW.verified_at,NEW.stopped_sequence,NEW.retired_sequence) IS
    DISTINCT FROM
   (OLD.verified,OLD.manifests,OLD.verified_at,OLD.stopped_sequence,OLD.retired_sequence))
 THEN RAISE EXCEPTION 'immutable access epoch identity'; END IF;
 IF NEW.phase=OLD.phase THEN
   IF NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'unbound epoch update'; END IF;
   RETURN NEW;
 END IF;
 IF NOT ((OLD.phase='prepared' AND NEW.phase='old_stopped') OR
   (OLD.phase='old_stopped' AND NEW.phase='old_retired') OR
   (OLD.phase='old_retired' AND NEW.phase='secured_started') OR
   (OLD.phase='secured_started' AND NEW.phase='verified') OR
   (OLD.phase='verified' AND NEW.phase='receipted')) THEN RAISE EXCEPTION 'invalid epoch transition'
    ; END IF;
 SELECT id INTO linked_execution FROM rag_access_epoch_executions WHERE epoch_id=NEW.id;
 required_kind := CASE NEW.phase WHEN 'old_stopped' THEN 'stop_old' WHEN 'old_retired' THEN
  'retire_old'
   WHEN 'secured_started' THEN 'start_secured' WHEN 'verified' THEN 'verify_access' ELSE NULL END;
 IF required_kind IS NOT NULL AND NOT EXISTS (SELECT 1 FROM rag_access_epoch_events
   WHERE execution_id=linked_execution AND kind=required_kind AND outcome='settled')
 THEN RAISE EXCEPTION 'epoch requires settled external action'; END IF;
 IF NEW.phase='verified' THEN
   IF jsonb_typeof(NEW.manifests) IS DISTINCT FROM 'object' OR
    (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(NEW.manifests) k)
      IS DISTINCT FROM manifest_names OR
    EXISTS (SELECT 1 FROM jsonb_each(NEW.manifests) WHERE jsonb_typeof(value)<>'string')
   THEN RAISE EXCEPTION 'incomplete manifest set'; END IF;
   IF NOT validate_rag_access_epoch_proof(NEW.verified) OR NEW.manifests IS NULL OR
     NEW.stopped_sequence IS NULL OR NEW.retired_sequence<=NEW.stopped_sequence OR
     NEW.verified->>'access_epoch_id'<>NEW.id::text OR
      NEW.verified->>'execution_id'<>linked_execution::text OR
     NEW.verified->>'minimum_access_epoch'<>NEW.ordinal::text OR
     NEW.verified->>'request_id'<>NEW.request_id::text OR
      NEW.verified->>'actor_id'<>NEW.actor_id::text OR
     NEW.verified->>'operation_id'<>NEW.operation_id::text OR
      NEW.verified->>'snapshot_sha256'<>NEW.snapshot_sha256 OR
     NEW.verified->>'gate_revision'<>NEW.gate_revision::text OR
      NEW.verified->>'store_id'<>NEW.store_id OR
     NEW.verified->>'cluster_uuid'<>NEW.cluster_uuid OR
     NEW.verified_at IS DISTINCT FROM (NEW.verified->>'verified_at')::timestamptz
   THEN RAISE EXCEPTION 'invalid verified epoch binding'; END IF;
   IF (NEW.verified->>'old_container_id',NEW.verified->>'cluster_uuid',
       NEW.verified->>'stable_node_id',NEW.verified->>'old_ephemeral_id',
       NEW.verified->>'old_jvm_start_at',NEW.verified->>'daemon_identity_sha256',
       NEW.verified->>'original_volume_identity_sha256',NEW.verified->>'protected_mount_sha256',
       NEW.verified->>'protected_image_sha256',NEW.verified->>'old_config_sha256',
       NEW.verified->>'old_deployment_sha256') IS DISTINCT FROM
      (NEW.original->>'container_id',NEW.original->>'cluster_uuid',
       NEW.original->>'stable_node_id',NEW.original->>'ephemeral_id',
       NEW.original->>'jvm_start_at',NEW.original->>'daemon_sha256',
       NEW.original->>'volume_sha256',NEW.original->>'mount_sha256',
       NEW.original->>'image_sha256',NEW.original->>'config_sha256',
       NEW.original->>'deployment_sha256') OR
      (SELECT count(*) FROM rag_access_epoch_events
       WHERE execution_id=linked_execution AND outcome='settled')<>12 OR
      NOT EXISTS (SELECT 1 FROM rag_access_epoch_events WHERE execution_id=linked_execution
       AND kind='stop_old' AND outcome='settled' AND sequence=NEW.stopped_sequence
       AND manifest_json::jsonb->>'container_id'=NEW.original->>'container_id'
       AND manifest_json::jsonb->>'finished_at'=NEW.verified->>'old_server_stopped_at') OR
      NOT EXISTS (SELECT 1 FROM rag_access_epoch_events WHERE execution_id=linked_execution
       AND kind='retire_old' AND outcome='settled' AND sequence=NEW.retired_sequence
       AND manifest_json::jsonb->>'container_id'=NEW.original->>'container_id'
       AND manifest_json::jsonb->>'retired_at'=NEW.verified->>'old_container_retired_at')
   THEN RAISE EXCEPTION 'unbound original or control history'; END IF;
   FOR item IN SELECT key,value FROM jsonb_each_text(NEW.manifests) LOOP
     IF NEW.verified->>(item.key||'_sha256') IS DISTINCT FROM
       encode(sha256(convert_to(item.value,'UTF8')),'hex') THEN RAISE EXCEPTION
        'manifest digest mismatch' ; END IF;
   END LOOP;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_rag_access_epoch_transition BEFORE INSERT OR UPDATE OR DELETE ON
 rag_access_epochs
 FOR EACH ROW EXECUTE FUNCTION guard_rag_access_epoch_transition();
CREATE FUNCTION guard_rag_access_epoch_execution() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'immutable cutover execution'; END $$;
CREATE TRIGGER guard_rag_access_epoch_execution BEFORE UPDATE OR DELETE ON
 rag_access_epoch_executions
 FOR EACH ROW EXECUTE FUNCTION guard_rag_access_epoch_execution();
CREATE FUNCTION guard_rag_access_epoch_floor() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE epoch rag_access_epochs%ROWTYPE;
DECLARE identity_names TEXT[] := ARRAY['access_epoch_id','auth_sha256','ca_sha256',
 'cluster_uuid','config_sha256','container_id','ordinal','route_sha256','stable_node_id','store_id'];
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'access floor cannot be deleted'; END IF;
 SELECT * INTO epoch FROM rag_access_epochs WHERE id=NEW.epoch_id;
 IF jsonb_typeof(NEW.identity) IS DISTINCT FROM 'object' OR
   (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(NEW.identity) k)
     IS DISTINCT FROM identity_names OR
   jsonb_typeof(NEW.identity->'ordinal') IS DISTINCT FROM 'number' OR
   EXISTS (SELECT 1 FROM jsonb_each(NEW.identity) WHERE key<>'ordinal'
           AND jsonb_typeof(value)<>'string') OR
   epoch.id IS NULL OR epoch.cluster_uuid<>NEW.cluster_uuid OR epoch.store_id<>NEW.store_id OR
  epoch.ordinal<>NEW.ordinal OR
   NEW.identity->>'access_epoch_id'<>NEW.epoch_id::text OR
    NEW.identity->>'ordinal'<>NEW.ordinal::text OR
   NEW.identity->>'cluster_uuid'<>NEW.cluster_uuid OR NEW.identity->>'store_id'<>NEW.store_id OR
   (TG_OP='UPDATE' AND (NEW.ordinal<=OLD.ordinal OR NEW.store_id<>OLD.store_id OR
    NEW.cluster_uuid<>OLD.cluster_uuid))
 THEN RAISE EXCEPTION 'access floor cannot decrease or change identity'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_rag_access_epoch_floor BEFORE INSERT OR UPDATE OR DELETE ON
 rag_access_epoch_floors
 FOR EACH ROW EXECUTE FUNCTION guard_rag_access_epoch_floor();
CREATE FUNCTION check_rag_access_epoch_receipt_integrity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE epoch rag_access_epochs%ROWTYPE;
DECLARE evidence rag_alias_recovery_receipts%ROWTYPE;
DECLARE floor rag_access_epoch_floors%ROWTYPE;
DECLARE epoch_uuid UUID;
BEGIN
 IF TG_TABLE_NAME='rag_access_epochs' THEN epoch_uuid:=NEW.id;
 ELSIF TG_TABLE_NAME='rag_access_epoch_floors' THEN epoch_uuid:=NEW.epoch_id;
 ELSE epoch_uuid:=NEW.access_epoch_id; END IF;
 IF epoch_uuid IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO epoch FROM rag_access_epochs WHERE id=epoch_uuid;
 SELECT * INTO evidence FROM rag_alias_recovery_receipts WHERE access_epoch_id=epoch_uuid;
 SELECT * INTO floor FROM rag_access_epoch_floors WHERE epoch_id=epoch_uuid;
 IF epoch.phase IN ('verified','receipted') AND (floor.epoch_id IS NULL OR
  floor.ordinal<>epoch.ordinal OR
   floor.identity->>'container_id'<>epoch.verified->>'new_container_id' OR
   floor.identity->>'auth_sha256'<>epoch.verified->>'auth_policy_sha256' OR
   floor.identity->>'route_sha256'<>epoch.verified->>'route_policy_sha256' OR
   floor.identity->>'config_sha256'<>epoch.verified->>'new_config_sha256' OR
   floor.identity->>'ca_sha256' IS DISTINCT FROM epoch.verified->>'tls_public_ca_sha256' OR
   floor.identity->>'stable_node_id' IS DISTINCT FROM epoch.verified->>'stable_node_id')
 THEN RAISE EXCEPTION 'verified epoch requires exact authentication floor'; END IF;
 IF (epoch.phase='receipted' AND (evidence.access_epoch_id IS NULL OR
  epoch.receipted_at IS NULL OR evidence.created_at IS DISTINCT FROM epoch.receipted_at OR
    evidence.proof IS DISTINCT FROM epoch.verified)) OR
    (epoch.phase<>'receipted' AND evidence.access_epoch_id IS NOT NULL)
 THEN RAISE EXCEPTION 'epoch receipt and closure must be atomic'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER check_rag_access_epoch_integrity AFTER INSERT OR UPDATE ON
 rag_access_epochs
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION
  check_rag_access_epoch_receipt_integrity();
CREATE CONSTRAINT TRIGGER check_rag_access_epoch_receipt_integrity AFTER INSERT ON
 rag_alias_recovery_receipts
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION
  check_rag_access_epoch_receipt_integrity();
CREATE CONSTRAINT TRIGGER check_rag_access_epoch_floor_integrity AFTER INSERT OR UPDATE ON
 rag_access_epoch_floors
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION
  check_rag_access_epoch_receipt_integrity();""")


def downgrade() -> None:
    # Evidence cannot be removed to make a downgrade look safe.
    op.execute("""
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM rag_access_epochs) OR EXISTS(SELECT 1 FROM rag_access_epoch_floors) OR
   EXISTS(SELECT 1 FROM rag_alias_recovery_receipts WHERE schema_version=2)
 THEN RAISE EXCEPTION 'access epoch evidence prevents downgrade'; END IF;
END $$;""")
    op.execute("""
DROP TRIGGER check_rag_access_epoch_receipt_integrity ON rag_alias_recovery_receipts;
DROP TRIGGER check_rag_access_epoch_integrity ON rag_access_epochs;
DROP TRIGGER check_rag_access_epoch_floor_integrity ON rag_access_epoch_floors;
DROP FUNCTION check_rag_access_epoch_receipt_integrity();
ALTER TABLE rag_alias_recovery_receipts DROP CONSTRAINT ck_rag_alias_receipt_epoch_binding;
ALTER TABLE rag_alias_recovery_receipts DROP CONSTRAINT fk_rag_alias_receipt_access_epoch;
ALTER TABLE rag_alias_recovery_receipts DROP CONSTRAINT fk_rag_alias_receipt_execution;
ALTER TABLE rag_alias_recovery_receipts DROP COLUMN access_epoch_id;
ALTER TABLE rag_alias_recovery_receipts DROP COLUMN execution_id;
ALTER TABLE rag_alias_recovery_receipts DROP CONSTRAINT ck_rag_alias_receipt_proof;
ALTER TABLE rag_alias_recovery_receipts ADD CONSTRAINT ck_rag_alias_receipt_proof CHECK (
 schema_version=1 AND jsonb_typeof(proof)='object' AND
 ((result_code='not_dispatched' AND proof_kind='reserved_cas' AND proof='{}'::jsonb) OR
  (result_code='recovered_terminated' AND
   proof_kind='local_single_node_controlled_restart' AND proof->>'proof_kind'=proof_kind AND
   (proof->>'schema_version')::integer=1 AND proof->>'request_id'=request_id::text AND
   proof->>'operation_id'=operation_id::text AND proof->>'snapshot_sha256'=snapshot_sha256 AND
   proof->>'cluster_uuid'=cluster_uuid)));
CREATE OR REPLACE FUNCTION guard_rag_alias_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE claim rag_alias_cluster_gates%ROWTYPE;
DECLARE expected_keys TEXT[] := ARRAY[
 'client_inventory_sha256','clients_terminated_at','cluster_uuid','config_sha256','container_id',
 'deployment_history_sha256','new_ephemeral_id','new_jvm_start_at','old_ephemeral_id',
 'old_jvm_start_at','operation_id','proof_kind','protected_mount_sha256','request_id',
 'schema_version','server_started_at','server_stopped_at','snapshot_sha256','stable_node_id',
 'verified_at'];
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'immutable alias recovery receipt'; END IF;
 SELECT * INTO claim FROM rag_alias_cluster_gates WHERE cluster_uuid=NEW.cluster_uuid FOR UPDATE;
 IF NOT FOUND OR claim.state<>'frozen' OR
  (claim.request_id,claim.actor_id,claim.operation_id,claim.snapshot_sha256,claim.revision)
   IS DISTINCT FROM
  (NEW.request_id,NEW.actor_id,NEW.operation_id,NEW.snapshot_sha256,NEW.gate_revision)
 THEN RAISE EXCEPTION 'receipt requires exact frozen claim'; END IF;
 IF NEW.result_code='recovered_terminated' AND
  (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(NEW.proof) k)
   IS DISTINCT FROM expected_keys THEN RAISE EXCEPTION 'unallowlisted proof facts'; END IF;
 IF NEW.result_code='recovered_terminated' AND EXISTS (
  SELECT 1 FROM jsonb_each(NEW.proof) fact WHERE
  (fact.key='schema_version' AND jsonb_typeof(fact.value)<>'number') OR
  (fact.key<>'schema_version' AND jsonb_typeof(fact.value)<>'string'))
 THEN RAISE EXCEPTION 'invalid typed proof facts'; END IF;
 RETURN NEW;
END $$;
DROP TABLE rag_access_epoch_events;
DROP FUNCTION guard_rag_access_epoch_event();
DROP TABLE rag_access_epoch_floors;
DROP FUNCTION guard_rag_access_epoch_floor();
DROP TABLE rag_access_epoch_executions;
DROP FUNCTION guard_rag_access_epoch_execution();
DROP TABLE rag_access_epochs;
DROP FUNCTION guard_rag_access_epoch_transition();
DROP FUNCTION validate_rag_access_epoch_proof(JSONB);
DROP FUNCTION rag_access_epoch_canonical_proof(JSONB);
""")
