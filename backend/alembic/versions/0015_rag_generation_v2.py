"""Allow immutable grounded generation configurations."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_rag_generation_v2"
down_revision: str | Sequence[str] | None = "0014_asset_content_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_rag_configuration_versions_validate_v1 "
        "ON rag_configuration_versions"
    )
    op.execute("DROP FUNCTION rag_validate_configuration_version_v1()")
    op.drop_constraint(
        "ck_rag_answer_policy_versions_mode",
        "rag_answer_policy_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_rag_answer_policy_versions_mode",
        "rag_answer_policy_versions",
        "mode IN ('extractive', 'generative')",
    )
    op.drop_constraint(
        "ck_rag_configuration_versions_no_generation_v1",
        "rag_configuration_versions",
        type_="check",
    )
    op.execute(_V2_VALIDATION_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER trg_rag_configuration_versions_validate_v2
        BEFORE INSERT OR UPDATE ON rag_configuration_versions
        FOR EACH ROW EXECUTE FUNCTION rag_validate_configuration_version_v2()
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    generative_count = connection.scalar(
        sa.text(
            """
            SELECT count(*)
            FROM rag_configuration_versions AS version
            JOIN rag_answer_policy_versions AS policy
              ON policy.id = version.answer_policy_version_id
             AND policy.configuration_id = version.configuration_id
             AND policy.version = version.version
            WHERE policy.mode = 'generative'
               OR version.generation_profile_id IS NOT NULL
            """
        )
    )
    if generative_count:
        raise RuntimeError(
            "Cannot downgrade while generative RAG configuration versions exist."
        )
    op.execute(
        "DROP TRIGGER trg_rag_configuration_versions_validate_v2 "
        "ON rag_configuration_versions"
    )
    op.execute("DROP FUNCTION rag_validate_configuration_version_v2()")
    op.create_check_constraint(
        "ck_rag_configuration_versions_no_generation_v1",
        "rag_configuration_versions",
        "generation_profile_id IS NULL",
    )
    op.drop_constraint(
        "ck_rag_answer_policy_versions_mode",
        "rag_answer_policy_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_rag_answer_policy_versions_mode",
        "rag_answer_policy_versions",
        "mode = 'extractive'",
    )
    op.execute(_V1_VALIDATION_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER trg_rag_configuration_versions_validate_v1
        BEFORE INSERT OR UPDATE ON rag_configuration_versions
        FOR EACH ROW EXECUTE FUNCTION rag_validate_configuration_version_v1()
        """
    )


_RERANKER_VALIDATION = """
    SELECT config::jsonb INTO retrieval_config
    FROM rag_profiles
    WHERE id = NEW.retrieval_profile_id AND kind = 'retrieval';
    IF retrieval_config IS NULL THEN
        RAISE EXCEPTION 'configuration retrieval profile is invalid';
    END IF;
    IF retrieval_config ? 'reranker'
       AND retrieval_config -> 'reranker' <> '{"enabled": false}'::jsonb THEN
        RAISE EXCEPTION 'configured reranker execution is not supported';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_object_keys(retrieval_config) AS key
        WHERE key LIKE 'reranker%' AND key <> 'reranker'
    ) THEN
        RAISE EXCEPTION 'configured reranker selection is not supported';
    END IF;
    IF EXISTS (
        SELECT 1 FROM rag_profile_model_bindings
        WHERE profile_id = NEW.retrieval_profile_id AND role = 'reranker'
    ) THEN
        RAISE EXCEPTION 'configured reranker binding is not supported';
    END IF;
"""

_V2_VALIDATION_FUNCTION = f"""
CREATE FUNCTION rag_validate_configuration_version_v2()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    selected_profile_ids uuid[];
    bound_model_ids uuid[];
    retrieval_config jsonb;
    generation_config jsonb;
    answer_mode text;
    llm_binding_count integer;
BEGIN
    selected_profile_ids := array_remove(
        ARRAY[NEW.indexing_profile_id, NEW.retrieval_profile_id, NEW.generation_profile_id],
        NULL
    );
    PERFORM rag_lock_technical_components(selected_profile_ids, ARRAY[]::uuid[]);
    SELECT COALESCE(array_agg(DISTINCT model_id ORDER BY model_id), ARRAY[]::uuid[])
      INTO bound_model_ids
      FROM rag_profile_model_bindings
     WHERE profile_id = ANY(selected_profile_ids);
    PERFORM rag_lock_technical_components(ARRAY[]::uuid[], bound_model_ids);

    SELECT mode INTO answer_mode
      FROM rag_answer_policy_versions
     WHERE id = NEW.answer_policy_version_id
       AND configuration_id = NEW.configuration_id
       AND version = NEW.version;
    IF answer_mode IS NULL THEN
        RAISE EXCEPTION 'configuration answer policy is invalid';
    END IF;
    IF answer_mode = 'extractive' AND NEW.generation_profile_id IS NOT NULL THEN
        RAISE EXCEPTION 'extractive configuration cannot select generation';
    END IF;
    IF answer_mode = 'generative' AND NEW.generation_profile_id IS NULL THEN
        RAISE EXCEPTION 'generative configuration requires generation';
    END IF;

    {_RERANKER_VALIDATION}

    IF NEW.generation_profile_id IS NOT NULL THEN
        SELECT config::jsonb INTO generation_config
          FROM rag_profiles
         WHERE id = NEW.generation_profile_id AND kind = 'generation';
        IF generation_config IS NULL
           OR NOT generation_config ?& ARRAY[
                'prompt_ref', 'context_prompt_ref', 'citation_mode',
                'context_policy', 'generation'
           ]
           OR generation_config ->> 'citation_mode' <> 'required' THEN
            RAISE EXCEPTION 'configuration generation profile is invalid';
        END IF;
        SELECT count(*) INTO llm_binding_count
          FROM rag_profile_model_bindings AS binding
          JOIN rag_model_definitions AS model ON model.id = binding.model_id
         WHERE binding.profile_id = NEW.generation_profile_id
           AND binding.role = 'llm'
           AND model.kind = 'llm';
        IF llm_binding_count <> 1 OR EXISTS (
            SELECT 1 FROM rag_profile_model_bindings
             WHERE profile_id = NEW.generation_profile_id AND role <> 'llm'
        ) THEN
            RAISE EXCEPTION 'configuration generation LLM binding is invalid';
        END IF;
    END IF;
    RETURN NEW;
END;
$$
"""

_V1_VALIDATION_FUNCTION = f"""
CREATE FUNCTION rag_validate_configuration_version_v1()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    selected_profile_ids uuid[];
    bound_model_ids uuid[];
    retrieval_config jsonb;
BEGIN
    selected_profile_ids := ARRAY[NEW.indexing_profile_id, NEW.retrieval_profile_id];
    PERFORM rag_lock_technical_components(selected_profile_ids, ARRAY[]::uuid[]);
    SELECT COALESCE(array_agg(DISTINCT model_id ORDER BY model_id), ARRAY[]::uuid[])
      INTO bound_model_ids
      FROM rag_profile_model_bindings
     WHERE profile_id = ANY(selected_profile_ids);
    PERFORM rag_lock_technical_components(ARRAY[]::uuid[], bound_model_ids);
    {_RERANKER_VALIDATION}
    RETURN NEW;
END;
$$
"""
