"""Recompute generation acceptance from frozen rules and terminal raw results."""

# ruff: noqa: E501 -- PostgreSQL predicates are kept intact for review.
from alembic import op

revision = "0056_generative_evaluation_gate"
down_revision = "0055_generative_evaluation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE rag_generative_runs ADD COLUMN dispatched_at timestamptz;
    DO $$ DECLARE definition text; BEGIN
      SELECT pg_get_functiondef('rag_generative_run_guard()'::regprocedure) INTO definition;
      definition := replace(definition, '''runtime_environment'',''updated_at''',
                                        '''runtime_environment'',''updated_at'',''dispatched_at''');
      EXECUTE definition;
    END $$;
    CREATE TABLE rag_generative_acceptances (
      id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES rag_generative_runs(id),
      configuration_version_id uuid NOT NULL REFERENCES rag_configuration_versions(id),
      policy_id uuid NOT NULL REFERENCES rag_generative_policies(id),
      generation_profile_id uuid NOT NULL REFERENCES rag_profiles(id),
      rules_digest varchar(64) NOT NULL, snapshot_digest varchar(64) NOT NULL,
      metrics jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(run_id,configuration_version_id)
    );
    CREATE TRIGGER rag_generative_acceptance_immutable BEFORE UPDATE OR DELETE
      ON rag_generative_acceptances FOR EACH ROW EXECUTE FUNCTION rag_generative_immutable();
    CREATE FUNCTION rag_sync_generative_execution() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.status IN ('completed','failed','interrupted') THEN
        UPDATE rag_executions SET status=NEW.status, ended_at=NEW.finished_at,
          error_code=NEW.error_code, answer_status=NEW.result->'observation'->>'generation_status'
        WHERE evaluation_attempt_id=NEW.id AND status='running';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER rag_sync_generative_execution AFTER UPDATE OF status
      ON rag_generative_attempts FOR EACH ROW EXECUTE FUNCTION rag_sync_generative_execution();
    """)
    op.execute("""
    CREATE FUNCTION rag_verify_generative_candidate(run_uuid uuid, version_uuid uuid)
    RETURNS jsonb LANGUAGE plpgsql AS $$
    DECLARE
      r rag_generative_runs; p rag_generative_policies; v rag_configuration_versions;
      a rag_generative_attempts; c rag_evaluation_dataset_cases;
      component jsonb; rule jsonb; observation jsonb; group_value jsonb; evidence text;
      expected_count integer; actual_count integer:=0; positives integer:=0; negatives integer:=0;
      correct integer:=0; abstained integer:=0; covered float8:=0;
      groups integer; matched integer; content_ok boolean; judgment_status text;
      answer_text text; latencies float8[]:='{}'; p95 float8; candidate_metrics jsonb;
    BEGIN
      SELECT * INTO STRICT r FROM rag_generative_runs WHERE id=run_uuid;
      SELECT * INTO STRICT p FROM rag_generative_policies WHERE id=r.policy_id;
      SELECT * INTO STRICT v FROM rag_configuration_versions WHERE id=version_uuid;
      IF r.status<>'completed' OR r.metric_version<>'generative-v1' OR p.owner_id<>r.owner_id
        OR v.generation_profile_id IS NULL THEN
        RAISE EXCEPTION 'generative acceptance requires a complete exact run';
      END IF;
      IF (p.definition->>'version')::integer IS NULL
        OR p.definition->>'require_valid_citations' IS DISTINCT FROM 'true'
        OR p.definition->>'max_access_leaks' IS DISTINCT FROM '0'
        OR rag_evaluation_is_nonnegative_finite_float(p.definition->'min_context_coverage') IS DISTINCT FROM true
        OR rag_evaluation_is_nonnegative_finite_float(p.definition->'min_correctness') IS DISTINCT FROM true
        OR rag_evaluation_is_nonnegative_finite_float(p.definition->'min_abstention') IS DISTINCT FROM true
        OR rag_evaluation_is_nonnegative_finite_float(p.definition->'max_p95_latency_ms') IS DISTINCT FROM true
        OR (p.definition->>'min_context_coverage')::float8>1
        OR (p.definition->>'min_correctness')::float8>1
        OR (p.definition->>'min_abstention')::float8>1 THEN
        RAISE EXCEPTION 'invalid immutable generative acceptance policy';
      END IF;
      IF r.rules_digest<>encode(sha256(convert_to(rag_generative_canonical(r.expected_rules),'UTF8')),'hex') THEN
        RAISE EXCEPTION 'expected rule digest mismatch';
      END IF;
      SELECT entry->'component_snapshot' INTO component
        FROM jsonb_array_elements(r.snapshot->'candidates') entry
        WHERE entry->>'configuration_version_id'=version_uuid::text;
      IF component IS NULL OR component->'configuration'->>'version_id'<>version_uuid::text
        OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(component->'profiles') profile
          WHERE profile->>'id'=v.generation_profile_id::text AND profile->>'kind'='generation')
        OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(component->'profiles') profile
          WHERE profile->>'id'=v.indexing_profile_id::text)
        OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(component->'profiles') profile
          WHERE profile->>'id'=v.retrieval_profile_id::text)
        OR component->'answer_policy'->>'id'<>v.answer_policy_version_id::text THEN
        RAISE EXCEPTION 'generative profile binding mismatch';
      END IF;
      SELECT count(*)*r.repetition_count INTO expected_count FROM rag_evaluation_dataset_cases
        WHERE dataset_snapshot_id=r.dataset_snapshot_id;
      FOR a IN SELECT DISTINCT ON (case_id,repetition) * FROM rag_generative_attempts
        WHERE run_id=r.id AND configuration_version_id=v.id
        ORDER BY case_id,repetition,attempt_number DESC
      LOOP
        actual_count:=actual_count+1;
        SELECT * INTO STRICT c FROM rag_evaluation_dataset_cases
          WHERE dataset_snapshot_id=r.dataset_snapshot_id AND id=a.case_id;
        rule:=r.expected_rules->a.case_id::text;
        observation:=a.result->'observation';
        IF a.status<>'completed' OR rule IS NULL OR (rule->>'version')::integer<1
          OR observation IS NULL OR observation->>'generation_status' IS NULL
          OR observation->>'generation_status' NOT IN ('answered','insufficient_evidence')
          OR observation->>'failure_stage' IS NOT NULL OR observation->>'error_code' IS NOT NULL
          OR observation->>'execution_id'<>a.execution_id::text
          OR NOT EXISTS(SELECT 1 FROM rag_executions x WHERE x.id=a.execution_id
            AND x.evaluation_attempt_id=a.id AND x.actor_id=r.owner_id AND x.status='completed')
          OR jsonb_typeof(observation->'access_exposures') IS DISTINCT FROM 'array'
          OR jsonb_typeof(observation->'retrieved_evidence_ids') IS DISTINCT FROM 'array'
          OR jsonb_typeof(observation->'selected_evidence_ids') IS DISTINCT FROM 'array'
          OR jsonb_typeof(observation->'cited_evidence_ids') IS DISTINCT FROM 'array'
          OR jsonb_array_length(observation->'access_exposures')<>0
          OR rag_evaluation_is_nonnegative_finite_float(observation->'duration_ms') IS DISTINCT FROM true THEN
          RAISE EXCEPTION 'incomplete or invalid raw generative observation';
        END IF;
        IF NOT EXISTS(SELECT 1 FROM rag_generation_execution_audits audit
          WHERE audit.execution_id=a.execution_id AND audit.actor_id=r.owner_id
            AND audit.configuration_version_id=v.id AND audit.generation_profile_id=v.generation_profile_id
            AND audit.policy_allowed AND audit.status=CASE
              WHEN observation->>'generation_status'='answered' THEN 'succeeded' ELSE 'allowed' END
            AND to_jsonb(audit.evidence_ids) @> (observation->'selected_evidence_ids')
            AND (observation->'selected_evidence_ids') @> to_jsonb(audit.evidence_ids)) THEN
          RAISE EXCEPTION 'matching authorized generation audit is required';
        END IF;
        FOR evidence IN SELECT jsonb_array_elements_text(
            (observation->'retrieved_evidence_ids')||(observation->'selected_evidence_ids')||(observation->'cited_evidence_ids'))
        LOOP
          IF NOT c.authorized_source_ids::jsonb ? evidence OR c.forbidden_source_ids::jsonb ? evidence
            OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(r.snapshot->'sources') source,
                jsonb_array_elements(source->'evidence_units') unit,
                jsonb_array_elements(component->'index_builds') build
              WHERE unit->>'id'=evidence AND source->>'index_build_id'=build->>'index_build_id') THEN
            RAISE EXCEPTION 'generative evidence outside authorized snapshot';
          END IF;
        END LOOP;
        IF observation->>'generation_status'='answered' AND (
          observation->>'citation_valid' IS DISTINCT FROM 'true'
          OR jsonb_array_length(observation->'cited_evidence_ids')=0
          OR NOT (observation->'selected_evidence_ids') @> (observation->'cited_evidence_ids')) THEN
          RAISE EXCEPTION 'generative citation validation failed';
        END IF;
        IF rule->>'expected_answer_status' IS NULL
          OR rule->>'expected_answer_status' NOT IN ('answered','insufficient_evidence') THEN
          RAISE EXCEPTION 'unknown expected rule status';
        END IF;
        IF rule->>'expected_answer_status'='insufficient_evidence' THEN
          negatives:=negatives+1;
          IF observation->>'generation_status'='insufficient_evidence' THEN
            abstained:=abstained+1; correct:=correct+1;
          END IF;
        ELSE
          positives:=positives+1;
          groups:=jsonb_array_length(rule->'required_evidence_groups'); matched:=0;
          IF groups IS NULL OR groups=0 THEN RAISE EXCEPTION 'positive case requires evidence'; END IF;
          FOR group_value IN SELECT * FROM jsonb_array_elements(rule->'required_evidence_groups') LOOP
            IF jsonb_array_length(group_value)=0 OR NOT c.expected_evidence_ids::jsonb @> group_value THEN
              RAISE EXCEPTION 'expected rule evidence mismatch';
            END IF;
            IF EXISTS(SELECT 1 FROM jsonb_array_elements_text(group_value) e
              WHERE observation->'selected_evidence_ids' ? e) THEN matched:=matched+1; END IF;
          END LOOP;
          covered:=covered+matched::float8/groups;
          answer_text:=lower(regexp_replace(normalize(coalesce(a.result->>'answer',''),NFKC),'\\s+',' ','g'));
          judgment_status:=NULL;
          SELECT j.status INTO judgment_status FROM rag_generative_judgments j JOIN users u ON u.id=j.reviewer_id
            WHERE j.attempt_id=a.id AND j.result_digest=a.result_digest AND j.reviewer_id=r.owner_id
              AND u.role='owner' AND j.rule_digest=encode(sha256(convert_to(
                rag_generative_canonical(rule),'UTF8')),'hex')
            ORDER BY j.created_at DESC,j.id DESC LIMIT 1;
          IF judgment_status IS NULL THEN
            content_ok:=jsonb_array_length(rule->'required_propositions')>0;
            FOR evidence IN SELECT jsonb_array_elements_text(rule->'required_propositions') LOOP
              content_ok:=content_ok AND position(lower(regexp_replace(normalize(evidence,NFKC),'\\s+',' ','g')) IN answer_text)>0;
            END LOOP;
            FOR evidence IN SELECT jsonb_array_elements_text(rule->'forbidden_propositions') LOOP
              content_ok:=content_ok AND position(lower(regexp_replace(normalize(evidence,NFKC),'\\s+',' ','g')) IN answer_text)=0;
            END LOOP;
            IF jsonb_array_length(rule->'required_propositions')=0 THEN
              RAISE EXCEPTION 'unreviewed generative content cannot qualify';
            END IF;
          ELSE
            IF judgment_status='unreviewed' THEN RAISE EXCEPTION 'unreviewed content'; END IF;
            content_ok:=judgment_status='passed';
          END IF;
          IF content_ok AND observation->>'generation_status'='answered' THEN correct:=correct+1; END IF;
        END IF;
        latencies:=array_append(latencies,(observation->>'duration_ms')::float8);
      END LOOP;
      IF actual_count<>expected_count OR positives=0 OR negatives=0 THEN
        RAISE EXCEPTION 'complete positive and negative repetitions are required';
      END IF;
      SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY duration) INTO p95 FROM unnest(latencies) duration;
      IF covered/positives < (p.definition->>'min_context_coverage')::float8
        OR correct::float8/actual_count < (p.definition->>'min_correctness')::float8
        OR abstained::float8/negatives < (p.definition->>'min_abstention')::float8
        OR p95 > (p.definition->>'max_p95_latency_ms')::float8 THEN
        RAISE EXCEPTION 'generative acceptance policy failed';
      END IF;
      candidate_metrics:=jsonb_build_object('metric_version','generative-v1',
        'context_coverage',covered/positives,'context_count',positives,
        'correctness',correct::float8/actual_count,'correctness_count',actual_count,
        'abstention',abstained::float8/negatives,'abstention_count',negatives,
        'p95_ms',p95,'duration_count',actual_count,'duration_missing',0,'access_leaks',0);
      RETURN candidate_metrics;
    END $$;
    """)
    # Canonical JSON is shared with Python's sorted compact serialization for digests.
    op.execute("""
    CREATE FUNCTION rag_generative_canonical(value jsonb) RETURNS text LANGUAGE plpgsql IMMUTABLE AS $$
    DECLARE result text;
    BEGIN
      CASE jsonb_typeof(value)
      WHEN 'object' THEN SELECT '{'||coalesce(string_agg(to_jsonb(key)::text||':'||rag_generative_canonical(val),',' ORDER BY key COLLATE "C"),'')||'}'
        INTO result FROM jsonb_each(value) AS e(key,val);
      WHEN 'array' THEN SELECT '['||coalesce(string_agg(rag_generative_canonical(val),',' ORDER BY ordinal),'')||']'
        INTO result FROM jsonb_array_elements(value) WITH ORDINALITY AS e(val,ordinal);
      ELSE result:=value::text;
      END CASE;
      RETURN result;
    END $$;
    CREATE FUNCTION rag_generative_acceptance_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE r rag_generative_runs; v rag_configuration_versions;
    BEGIN
      SELECT * INTO STRICT r FROM rag_generative_runs WHERE id=NEW.run_id;
      SELECT * INTO STRICT v FROM rag_configuration_versions WHERE id=NEW.configuration_version_id;
      IF NEW.policy_id<>r.policy_id OR NEW.generation_profile_id<>v.generation_profile_id
        OR NEW.rules_digest<>r.rules_digest OR NEW.snapshot_digest<>r.snapshot_digest THEN
        RAISE EXCEPTION 'generative acceptance version binding mismatch';
      END IF;
      NEW.metrics:=rag_verify_generative_candidate(NEW.run_id,NEW.configuration_version_id);
      RETURN NEW;
    END $$;
    CREATE TRIGGER rag_generative_acceptance_guard BEFORE INSERT ON rag_generative_acceptances
      FOR EACH ROW EXECUTE FUNCTION rag_generative_acceptance_guard();
    DO $$ DECLARE definition text; BEGIN
      SELECT pg_get_functiondef('rag_require_qualifying_evaluation_for_promotion()'::regprocedure) INTO definition;
      definition:=regexp_replace(definition,'BEGIN',
        'BEGIN
         IF (NEW.evaluation_state=''passed'' OR NEW.is_default) AND EXISTS(
           SELECT 1 FROM rag_generative_acceptances a WHERE a.configuration_version_id=NEW.id
           AND rag_verify_generative_candidate(a.run_id,NEW.id) IS NOT NULL) THEN RETURN NEW; END IF;');
      EXECUTE definition;
    END $$;
    """)


def downgrade() -> None:
    raise RuntimeError("Generative promotion evidence requires a reviewed retention migration.")
