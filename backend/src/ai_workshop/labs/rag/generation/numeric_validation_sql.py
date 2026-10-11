"""The migration and guarded original-DB rollback trial share these exact statements."""
# ruff: noqa: E501

from ai_workshop.labs.rag.models.numeric_proof_policy import SOURCE_NUMERIC_PROOF_V1

NUMERIC_PROOF_DDL: tuple[str, ...] = (
    """
    CREATE TABLE rag_generation_numeric_validations (
      id uuid PRIMARY KEY,
      audit_id uuid NOT NULL UNIQUE REFERENCES rag_generation_execution_audits(id) ON DELETE RESTRICT,
      request_id uuid NOT NULL UNIQUE,
      execution_id uuid UNIQUE REFERENCES rag_executions(id) ON DELETE RESTRICT,
      configuration_version_id uuid NOT NULL REFERENCES rag_configuration_versions(id) ON DELETE RESTRICT,
      generation_profile_id uuid NOT NULL REFERENCES rag_profiles(id) ON DELETE RESTRICT,
      schema_version integer NOT NULL CHECK(schema_version=3),
      policy_ref varchar(80) NOT NULL CHECK(policy_ref='source-numeric-proof-v1'),
      policy_digest varchar(64) NOT NULL CHECK(policy_digest ~ '^[0-9a-f]{64}$'),
      catalogue_digest varchar(64) NOT NULL CHECK(catalogue_digest ~ '^[0-9a-f]{64}$'),
      payload_digest varchar(64) NOT NULL CHECK(payload_digest ~ '^[0-9a-f]{64}$'),
      created_at timestamptz NOT NULL
    )
    """,
    """
    CREATE FUNCTION rag_numeric_receipt_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'numeric_receipt_immutable'; END $$
    """,
    """
    CREATE TRIGGER rag_numeric_receipt_immutable
      BEFORE UPDATE OR DELETE ON rag_generation_numeric_validations
      FOR EACH ROW EXECUTE FUNCTION rag_numeric_receipt_immutable()
    """,
    """
    CREATE FUNCTION rag_require_generative_numeric_candidate(run_uuid uuid, version_uuid uuid)
    RETURNS void LANGUAGE plpgsql AS $numeric$
    DECLARE r rag_generative_runs; v rag_configuration_versions; a rag_generative_attempts;
      audit rag_generation_execution_audits; receipt rag_generation_numeric_validations;
      profile jsonb; live_profile jsonb; component jsonb; schema_version integer;
      envelope jsonb; payload jsonb; claims jsonb; claim jsonb; proof jsonb; operand jsonb;
      ordinal integer; proof_count integer; result_status text;
    BEGIN
      SELECT * INTO STRICT r FROM rag_generative_runs WHERE id=run_uuid;
      SELECT * INTO STRICT v FROM rag_configuration_versions WHERE id=version_uuid;
      SELECT entry->'component_snapshot' INTO component
        FROM jsonb_array_elements(r.snapshot->'candidates') entry
        WHERE entry->>'configuration_version_id'=version_uuid::text;
      SELECT entry INTO profile FROM jsonb_array_elements(component->'profiles') entry
        WHERE entry->>'id'=v.generation_profile_id::text AND entry->>'kind'='generation';
      SELECT config::jsonb INTO STRICT live_profile FROM rag_profiles WHERE id=v.generation_profile_id;
      IF profile IS NULL OR profile->'config' IS DISTINCT FROM live_profile THEN
        RAISE EXCEPTION 'numeric_profile_binding_invalid';
      END IF;
      schema_version:=coalesce((profile->'config'->'generation'->>'response_schema_version')::integer,1);
      IF schema_version IN (1,2) THEN RETURN; END IF;
      IF schema_version<>3 OR profile->'config'->'generation'->>'numeric_proof_policy_ref'
        IS DISTINCT FROM 'source-numeric-proof-v1'
        OR profile->'config'->>'prompt_ref' IS DISTINCT FROM 'rag-codex-answer-v6' THEN
        RAISE EXCEPTION 'numeric_profile_binding_invalid';
      END IF;
      FOR a IN SELECT DISTINCT ON (case_id,repetition) * FROM rag_generative_attempts
        WHERE run_id=r.id AND configuration_version_id=v.id
        ORDER BY case_id,repetition,attempt_number DESC
      LOOP
        IF a.status<>'completed' OR a.execution_id IS NULL THEN
          RAISE EXCEPTION 'numeric_execution_binding_invalid';
        END IF;
        BEGIN
          SELECT * INTO STRICT receipt FROM rag_generation_numeric_validations WHERE execution_id=a.execution_id;
          SELECT * INTO STRICT audit FROM rag_generation_execution_audits WHERE id=receipt.audit_id;
        EXCEPTION WHEN NO_DATA_FOUND THEN
          RAISE EXCEPTION 'numeric_validation_binding_invalid';
        END;
        result_status:=a.result->'observation'->>'generation_status';
        envelope:=a.result->'numeric_validation';
        IF envelope IS NULL OR envelope IS DISTINCT FROM jsonb_build_object(
          'validation_id',receipt.id,'audit_id',receipt.audit_id,'request_id',receipt.request_id,
          'configuration_version_id',receipt.configuration_version_id,'generation_profile_id',receipt.generation_profile_id,
          'schema_version',receipt.schema_version,'policy_ref',receipt.policy_ref,'policy_digest',receipt.policy_digest,
          'catalogue_digest',receipt.catalogue_digest,'payload_digest',receipt.payload_digest)
          OR receipt.configuration_version_id<>v.id OR receipt.generation_profile_id<>v.generation_profile_id
          OR receipt.policy_digest<>'__POLICY_DIGEST__' OR receipt.policy_ref<>'source-numeric-proof-v1'
          OR audit.execution_id IS DISTINCT FROM a.execution_id OR audit.actor_id<>r.owner_id
          OR audit.configuration_version_id<>v.id OR audit.generation_profile_id<>v.generation_profile_id
          OR audit.policy_allowed IS DISTINCT FROM true OR audit.safe_error_code IS NOT NULL
          OR audit.prompt_ref<>'rag-codex-answer-v6' OR audit.prompt_version<>6
          OR a.result->'observation'->>'execution_id' IS DISTINCT FROM a.execution_id::text
          OR NOT EXISTS(SELECT 1 FROM rag_executions e WHERE e.id=a.execution_id AND e.actor_id=r.owner_id
            AND e.evaluation_attempt_id=a.id AND e.status='completed' AND e.complete)
          OR to_jsonb(audit.evidence_ids) IS DISTINCT FROM a.result->'observation'->'selected_evidence_ids' THEN
          RAISE EXCEPTION 'numeric_validation_binding_invalid';
        END IF;
        claims:='[]'::jsonb; ordinal:=0; proof_count:=0;
        IF result_status='insufficient_evidence' THEN
          IF audit.status<>'allowed' OR a.result->'answer' IS DISTINCT FROM 'null'::jsonb
            OR a.result->'citations' IS DISTINCT FROM '[]'::jsonb THEN
            RAISE EXCEPTION 'numeric_abstention_invalid';
          END IF;
        ELSIF result_status='answered' THEN
          IF audit.status<>'succeeded' OR jsonb_typeof(a.result->'citations') IS DISTINCT FROM 'array'
            OR jsonb_array_length(a.result->'citations') NOT BETWEEN 1 AND 32 THEN
            RAISE EXCEPTION 'numeric_claims_invalid';
          END IF;
          FOR claim IN SELECT * FROM jsonb_array_elements(a.result->'citations') LOOP
            IF claim->>'claim_index' IS DISTINCT FROM ordinal::text OR jsonb_typeof(claim->'claim_text') IS DISTINCT FROM 'string'
              OR jsonb_typeof(claim->'calculations') IS DISTINCT FROM 'array'
              OR jsonb_array_length(claim->'calculations')>32
              OR jsonb_typeof(claim->'evidence_ids') IS DISTINCT FROM 'array'
              OR jsonb_array_length(claim->'evidence_ids')=0
              OR NOT (to_jsonb(audit.evidence_ids) @> (claim->'evidence_ids')) THEN
              RAISE EXCEPTION 'numeric_claims_invalid';
            END IF;
            claims:=claims||jsonb_build_array(jsonb_build_object('claim_index',ordinal,'text',claim->'claim_text',
              'evidence_ids',claim->'evidence_ids','calculations',claim->'calculations'));
            FOR proof IN SELECT * FROM jsonb_array_elements(claim->'calculations') LOOP
              proof_count:=proof_count+1;
              IF proof_count>128 OR proof->>'policy_ref' IS DISTINCT FROM 'source-numeric-proof-v1'
                OR proof->>'operation' NOT IN ('percentage_point_difference','convert_krw_unit')
                OR jsonb_typeof(proof->'operands') IS DISTINCT FROM 'array'
                OR jsonb_array_length(proof->'operands')<>(CASE WHEN proof->>'operation'='percentage_point_difference' THEN 2 ELSE 1 END)
                OR (proof->>'result_start') !~ '^[0-9]+$' OR (proof->>'result_end') !~ '^[0-9]+$'
                OR (proof->>'result_start')::integer >= (proof->>'result_end')::integer
                OR (proof->>'result_end')::integer > char_length(claim->>'claim_text') THEN
                RAISE EXCEPTION 'numeric_proof_invalid';
              END IF;
              FOR operand IN SELECT * FROM jsonb_array_elements(proof->'operands') LOOP
                IF NOT (claim->'evidence_ids' ? (operand->>'evidence_id'))
                  OR (operand->>'token_start') !~ '^[0-9]+$' OR (operand->>'token_end') !~ '^[0-9]+$'
                  OR (operand->>'token_start')::integer >= (operand->>'token_end')::integer
                  OR operand->>'unit' NOT IN ('%','원','만원','억원')
                  OR NOT EXISTS(SELECT 1 FROM rag_evidence_units eu
                    JOIN rag_document_projections dp ON dp.id=eu.projection_id
                    JOIN asset_versions av ON av.id=dp.asset_version_id
                    JOIN documents d ON d.id=av.document_id
                    JOIN rag_index_builds ib ON ib.projection_id=dp.id
                    WHERE eu.id=(operand->>'evidence_id')::uuid AND eu.element_id=(operand->>'element_id')::uuid
                      AND eu.retrieval_chunk_id=(operand->>'chunk_id')::uuid AND dp.id=(operand->>'projection_id')::uuid
                      AND av.id=(operand->>'asset_version_id')::uuid AND d.id=(operand->>'document_id')::uuid
                      AND eu.char_start+(operand->>'token_start')::integer=(operand->>'char_start')::integer
                      AND eu.char_start+(operand->>'token_end')::integer=(operand->>'char_end')::integer
                      AND eu.char_end>=(operand->>'char_end')::integer
                      AND (operand->>'token_end')::integer<=char_length(eu.text)
                      AND eu.page IS NOT DISTINCT FROM (operand->>'page')::integer
                      AND d.lifecycle='active' AND av.status='ready' AND dp.status='ready' AND ib.status='ready') THEN
                  RAISE EXCEPTION 'numeric_operand_origin_invalid';
                END IF;
              END LOOP;
            END LOOP;
            ordinal:=ordinal+1;
          END LOOP;
          IF a.result->>'answer' IS DISTINCT FROM (SELECT string_agg(item->>'text',' ' ORDER BY (item->>'claim_index')::integer)
            FROM jsonb_array_elements(claims) item) THEN RAISE EXCEPTION 'numeric_claim_answer_invalid'; END IF;
        ELSE RAISE EXCEPTION 'numeric_status_invalid'; END IF;
        payload:=jsonb_build_object('schema_version',3,'status',result_status,'answer',a.result->'answer','claims',claims,
          'request_id',receipt.request_id,'configuration_version_id',v.id,'generation_profile_id',v.generation_profile_id,
          'policy_ref',receipt.policy_ref,'policy_digest',receipt.policy_digest,'catalogue_digest',receipt.catalogue_digest);
        IF receipt.payload_digest<>encode(sha256(convert_to(rag_generative_canonical(payload),'UTF8')),'hex') THEN
          RAISE EXCEPTION 'numeric_payload_digest_invalid';
        END IF;
      END LOOP;
    END $numeric$
    """.replace("__POLICY_DIGEST__", SOURCE_NUMERIC_PROOF_V1.digest),
    """
    DO $inject$ DECLARE definition text; anchor text:='SELECT * INTO STRICT v FROM rag_configuration_versions WHERE id=version_uuid;';
      anchor_count integer;
    BEGIN
      SELECT pg_get_functiondef('rag_verify_generative_candidate(uuid,uuid)'::regprocedure) INTO definition;
      anchor_count:=(length(definition)-length(replace(definition,anchor,'')))/length(anchor);
      IF anchor_count<>1 OR position('rag_require_generative_numeric_candidate' IN definition)>0 THEN
        RAISE EXCEPTION 'numeric_gate_anchor_invalid';
      END IF;
      EXECUTE replace(definition,anchor,anchor||' PERFORM rag_require_generative_numeric_candidate(run_uuid,version_uuid);');
    END $inject$
    """,
)
