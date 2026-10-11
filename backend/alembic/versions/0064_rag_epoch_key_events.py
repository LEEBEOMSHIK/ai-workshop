"""Track every role key issue/invalidation without changing installed0062."""

from alembic import op

revision = "0064_rag_epoch_key_events"
down_revision = "0063_rag_numeric_proof"
branch_labels = None
depends_on = None

SCHEMA = r"""
CREATE TABLE rag_access_epoch_key_events (
 id UUID PRIMARY KEY,
 execution_id UUID NOT NULL CONSTRAINT fk_rag_epoch_key_execution
  REFERENCES rag_access_epoch_executions(id),
 parent_action_id UUID NOT NULL,
 action_id UUID NOT NULL,
 sequence INTEGER NOT NULL,
 action_sequence INTEGER NOT NULL,
 executor_generation VARCHAR(36) NOT NULL,
 role VARCHAR(16) NOT NULL,
 issuance_id UUID NOT NULL,
 kind VARCHAR(16) NOT NULL,
 key_id VARCHAR(256),
 replaces_issuance_id UUID,
 permissions_sha256 VARCHAR(64) NOT NULL,
 outcome VARCHAR(16) NOT NULL,
 manifest_json TEXT,
 observed_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT uq_rag_epoch_key_event_sequence UNIQUE(execution_id,sequence),
 CONSTRAINT uq_rag_epoch_key_action_outcome UNIQUE(action_id,outcome),
 CONSTRAINT ck_rag_epoch_key_sequence CHECK(sequence>0 AND action_sequence>0),
 CONSTRAINT ck_rag_epoch_key_role CHECK(role IN ('reader','writer','collector')),
 CONSTRAINT ck_rag_epoch_key_kind CHECK(kind IN ('issue','invalidate')),
 CONSTRAINT ck_rag_epoch_key_outcome CHECK(outcome IN ('pending','unknown','settled')),
 CONSTRAINT ck_rag_epoch_key_permissions CHECK(permissions_sha256 ~ '^[0-9a-f]{64}$'),
 CONSTRAINT ck_rag_epoch_key_manifest CHECK((outcome='pending')=(manifest_json IS NULL))
);
CREATE UNIQUE INDEX uq_rag_epoch_key_issue ON rag_access_epoch_key_events(issuance_id)
 WHERE outcome='pending' AND kind='issue';
CREATE UNIQUE INDEX uq_rag_epoch_key_invalidate ON rag_access_epoch_key_events(issuance_id)
 WHERE outcome='pending' AND kind='invalidate';

CREATE FUNCTION rag_access_epoch_key_group(exec_id UUID, parent_id UUID) RETURNS JSONB
 LANGUAGE plpgsql STABLE AS $$
DECLARE public_keys JSONB;
DECLARE public_issuances JSONB;
DECLARE public_permissions JSONB;
DECLARE count_roles INTEGER;
DECLARE count_keys INTEGER;
BEGIN
 IF EXISTS (
   SELECT 1 FROM (
     SELECT DISTINCT ON(action_id) outcome FROM rag_access_epoch_key_events
     WHERE execution_id=exec_id AND parent_action_id=parent_id
     ORDER BY action_id,sequence DESC
   ) latest WHERE outcome<>'settled'
 ) THEN RETURN NULL; END IF;
 WITH latest AS (
   SELECT DISTINCT ON(role) role,issuance_id,permissions_sha256,manifest_json::jsonb facts
   FROM rag_access_epoch_key_events WHERE execution_id=exec_id AND parent_action_id=parent_id
     AND kind='issue' AND outcome='settled' ORDER BY role,sequence DESC
 ) SELECT count(*),count(DISTINCT facts->>'key_id'),
   jsonb_object_agg(role,facts->>'key_id'),jsonb_object_agg(role,issuance_id::text),
   jsonb_object_agg(role,permissions_sha256)
 INTO count_roles,count_keys,public_keys,public_issuances,public_permissions
 FROM latest WHERE facts->>'result'='issued';
 IF count_roles<>3 OR count_keys<>3 OR NOT(public_keys ?& ARRAY['reader','writer','collector'])
 THEN RETURN NULL; END IF;
 RETURN jsonb_build_object('schema_version',1,'execution_id',exec_id::text,
   'parent_action_id',parent_id::text,'keys',public_keys,
   'issuances',public_issuances,'permissions',public_permissions);
END $$;

CREATE FUNCTION guard_rag_epoch_key_event() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE execution rag_access_epoch_executions%ROWTYPE;
DECLARE epoch rag_access_epochs%ROWTYPE;
DECLARE claim rag_alias_cluster_gates%ROWTYPE;
DECLARE operation rag_alias_operations%ROWTYPE;
DECLARE parent rag_access_epoch_events%ROWTYPE;
DECLARE prior rag_access_epoch_key_events%ROWTYPE;
DECLARE old_issue rag_access_epoch_key_events%ROWTYPE;
DECLARE last_sequence INTEGER;
DECLARE needed_role TEXT;
DECLARE facts JSONB;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'immutable role key event'; END IF;
 SELECT * INTO execution FROM rag_access_epoch_executions WHERE id=NEW.execution_id FOR UPDATE;
 SELECT * INTO epoch FROM rag_access_epochs WHERE id=execution.epoch_id;
 IF execution.id IS NULL OR epoch.id IS NULL OR epoch.phase<>'old_retired' OR
   NEW.executor_generation IS DISTINCT FROM execution.executor_generation
 THEN RAISE EXCEPTION 'unbound role key event'; END IF;
 SELECT * INTO claim FROM rag_alias_cluster_gates WHERE cluster_uuid=epoch.cluster_uuid FOR UPDATE;
 SELECT * INTO operation FROM rag_alias_operations WHERE id=epoch.operation_id FOR UPDATE;
 PERFORM 1 FROM users WHERE id=epoch.actor_id AND is_active AND role='owner' FOR UPDATE;
 IF NOT FOUND OR operation.state IS DISTINCT FROM 'open' OR claim.state IS DISTINCT FROM 'frozen'
   OR (claim.request_id,claim.actor_id,claim.operation_id,claim.snapshot_sha256,claim.revision)
    IS DISTINCT FROM
   (epoch.request_id,epoch.actor_id,epoch.operation_id,epoch.snapshot_sha256,epoch.gate_revision)
 THEN RAISE EXCEPTION 'role key frozen owner required'; END IF;
 SELECT * INTO parent FROM rag_access_epoch_events WHERE execution_id=NEW.execution_id
   ORDER BY sequence DESC LIMIT 1;
 IF parent.action_id IS DISTINCT FROM NEW.parent_action_id OR parent.kind<>'issue_role_key'
   OR parent.outcome NOT IN ('pending','unknown')
   OR parent.executor_generation IS DISTINCT FROM NEW.executor_generation
 THEN RAISE EXCEPTION 'role key parent not pending'; END IF;
 SELECT coalesce(max(sequence),0) INTO last_sequence FROM rag_access_epoch_key_events
   WHERE execution_id=NEW.execution_id;
 IF NEW.sequence<>last_sequence+1 OR NEW.observed_at>clock_timestamp()
 THEN RAISE EXCEPTION 'invalid role key sequence or time'; END IF;

 IF NEW.outcome='pending' THEN
   IF NEW.action_sequence<>NEW.sequence OR EXISTS(
     SELECT 1 FROM rag_access_epoch_key_events WHERE action_id=NEW.action_id
   ) OR EXISTS(
     SELECT 1 FROM (
       SELECT DISTINCT ON(action_id) outcome FROM rag_access_epoch_key_events
       WHERE execution_id=NEW.execution_id ORDER BY action_id,sequence DESC
     ) latest WHERE outcome<>'settled'
   ) THEN RAISE EXCEPTION 'unsettled prior role key action'; END IF;
   IF NEW.kind='issue' THEN
     IF NEW.key_id IS NOT NULL THEN RAISE EXCEPTION 'issuance cannot preclaim key id'; END IF;
     WITH latest AS (
       SELECT DISTINCT ON(role) role,manifest_json::jsonb facts
       FROM rag_access_epoch_key_events WHERE execution_id=NEW.execution_id
        AND kind='issue' AND outcome='settled' ORDER BY role,sequence DESC
     ) SELECT role INTO needed_role FROM unnest(ARRAY['reader','writer','collector'])
       WITH ORDINALITY wanted(role,position) WHERE NOT EXISTS(
         SELECT 1 FROM latest WHERE latest.role=wanted.role AND latest.facts->>'result'='issued'
       ) ORDER BY position LIMIT 1;
     IF needed_role IS DISTINCT FROM NEW.role THEN RAISE EXCEPTION 'invalid role order'; END IF;
     SELECT * INTO old_issue FROM rag_access_epoch_key_events WHERE execution_id=NEW.execution_id
       AND kind='issue' AND role=NEW.role AND outcome='settled' ORDER BY sequence DESC LIMIT 1;
     IF old_issue.id IS NULL THEN
       IF NEW.replaces_issuance_id IS NOT NULL THEN
         RAISE EXCEPTION 'unknown replaced issuance'; END IF;
     ELSIF old_issue.manifest_json::jsonb->>'result'<>'issued_inaccessible' OR
       NEW.replaces_issuance_id IS DISTINCT FROM old_issue.issuance_id OR
       NEW.permissions_sha256 IS DISTINCT FROM old_issue.permissions_sha256 OR NOT EXISTS(
         SELECT 1 FROM rag_access_epoch_key_events WHERE execution_id=NEW.execution_id
          AND kind='invalidate' AND issuance_id=old_issue.issuance_id AND outcome='settled'
          AND manifest_json::jsonb->>'result'='invalidated'
          AND manifest_json::jsonb->>'key_id'=old_issue.manifest_json::jsonb->>'key_id'
       ) THEN RAISE EXCEPTION 'exact invalidation required before replacement'; END IF;
   ELSE
     SELECT * INTO old_issue FROM rag_access_epoch_key_events WHERE execution_id=NEW.execution_id
       AND issuance_id=NEW.issuance_id AND kind='issue' AND outcome='settled';
     IF old_issue.id IS NULL OR old_issue.manifest_json::jsonb->>'result'<>'issued_inaccessible' OR
       (NEW.role,NEW.permissions_sha256,NEW.key_id) IS DISTINCT FROM
       (old_issue.role,old_issue.permissions_sha256,old_issue.manifest_json::jsonb->>'key_id')
       OR NEW.replaces_issuance_id IS NOT NULL
     THEN RAISE EXCEPTION 'unbound role key invalidation'; END IF;
   END IF;
 ELSE
   SELECT * INTO prior FROM rag_access_epoch_key_events WHERE action_id=NEW.action_id
     AND outcome='pending';
   IF prior.id IS NULL OR
    (NEW.execution_id,NEW.parent_action_id,NEW.action_sequence,NEW.executor_generation,
     NEW.role,NEW.issuance_id,NEW.kind,NEW.key_id,NEW.replaces_issuance_id,NEW.permissions_sha256)
    IS DISTINCT FROM
    (prior.execution_id,prior.parent_action_id,prior.action_sequence,prior.executor_generation,
     prior.role,prior.issuance_id,prior.kind,prior.key_id,prior.replaces_issuance_id,prior.permissions_sha256)
    OR NEW.observed_at<prior.observed_at OR EXISTS(
      SELECT 1 FROM rag_access_epoch_key_events WHERE action_id=NEW.action_id AND outcome='settled'
    ) THEN RAISE EXCEPTION 'unbound role key settlement'; END IF;
   facts := NEW.manifest_json::jsonb;
   IF NEW.outcome='unknown' THEN
     IF facts IS DISTINCT FROM jsonb_build_object('schema_version',1,'result','unknown')
     THEN RAISE EXCEPTION 'invalid role key unknown'; END IF;
   ELSE
     IF jsonb_typeof(facts) IS DISTINCT FROM 'object' OR
       (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(facts) k) IS DISTINCT FROM
       ARRAY['issuance_id','key_id','permissions_sha256','result','role','schema_version'] OR
       facts->'schema_version' IS DISTINCT FROM '1'::jsonb OR
       jsonb_typeof(facts->'result') IS DISTINCT FROM 'string' OR
       jsonb_typeof(facts->'key_id') IS DISTINCT FROM 'string' OR
       length(facts->>'key_id') NOT BETWEEN 1 AND 256 OR
       facts->>'key_id' !~ '^[A-Za-z0-9_-]+$' OR
       facts->'role' IS DISTINCT FROM to_jsonb(NEW.role) OR
       facts->'issuance_id' IS DISTINCT FROM to_jsonb(NEW.issuance_id::text) OR
       facts->'permissions_sha256' IS DISTINCT FROM to_jsonb(NEW.permissions_sha256) OR
       (NEW.kind='issue' AND facts->>'result' NOT IN ('issued','issued_inaccessible')) OR
       (NEW.kind='invalidate' AND (facts->'result' IS DISTINCT FROM '"invalidated"'::jsonb OR
         facts->'key_id' IS DISTINCT FROM to_jsonb(NEW.key_id)))
     THEN RAISE EXCEPTION 'invalid public role key facts'; END IF;
     IF NEW.kind='issue' AND EXISTS(
       SELECT 1 FROM rag_access_epoch_key_events WHERE execution_id=NEW.execution_id
        AND kind='issue' AND outcome='settled' AND issuance_id<>NEW.issuance_id
        AND manifest_json::jsonb->>'key_id'=facts->>'key_id'
     ) THEN RAISE EXCEPTION 'role keys must be distinct'; END IF;
   END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_rag_epoch_key_event BEFORE INSERT OR UPDATE OR DELETE ON
 rag_access_epoch_key_events FOR EACH ROW EXECUTE FUNCTION guard_rag_epoch_key_event();

CREATE FUNCTION guard_rag_epoch_key_parent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE execution rag_access_epoch_executions%ROWTYPE;
DECLARE expected JSONB;
BEGIN
 IF NEW.kind='issue_role_key' AND NEW.outcome='settled' THEN
   SELECT * INTO execution FROM rag_access_epoch_executions WHERE id=NEW.execution_id FOR UPDATE;
   expected := rag_access_epoch_key_group(NEW.execution_id,NEW.action_id);
   IF expected IS NULL OR NEW.manifest_json::jsonb IS DISTINCT FROM expected
   THEN RAISE EXCEPTION 'all three exact role keys required'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_rag_epoch_key_parent BEFORE INSERT ON rag_access_epoch_events
 FOR EACH ROW EXECUTE FUNCTION guard_rag_epoch_key_parent();
"""


def upgrade() -> None:
    op.execute(SCHEMA)


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM rag_access_epoch_key_events) THEN
   RAISE EXCEPTION 'recorded role key actions cannot be discarded';
 END IF;
END $$;
DROP TRIGGER guard_rag_epoch_key_parent ON rag_access_epoch_events;
DROP FUNCTION guard_rag_epoch_key_parent();
DROP TABLE rag_access_epoch_key_events;
DROP FUNCTION guard_rag_epoch_key_event();
DROP FUNCTION rag_access_epoch_key_group(UUID,UUID);
""")
