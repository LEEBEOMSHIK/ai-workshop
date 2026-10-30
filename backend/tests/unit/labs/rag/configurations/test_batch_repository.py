"""Synthetic SQL tests: no server, production rows, models, or network."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import Column, MetaData, Table, create_engine, delete, event, update
from sqlalchemy.orm import Session

from ai_workshop.labs.rag.configurations.models import (
    AnswerPolicyVersionRecord,
    RagConfigurationRecord,
    RagConfigurationVersionRecord,
    RagConfigurationWorkspaceSubscriptionRecord,
)
from ai_workshop.labs.rag.configurations.repository import SqlAlchemyRagConfigurationRepository
from ai_workshop.labs.rag.deployments.models import ModelDeploymentVersionRecord
from ai_workshop.labs.rag.deployments.repository import _version_record
from ai_workshop.labs.rag.models.models import (
    ModelDefinitionRecord,
    ProfileDeploymentBindingRecord,
    ProfileModelBindingRecord,
    ProfileRecord,
)
from tests.unit.labs.rag.generation.test_readiness import deployment


class AwaitableSession:
    """Run the repository's SQL against a disposable in-memory SQLite database."""

    def __init__(self, session):
        self.session = session

    async def scalars(self, statement):
        return self.session.scalars(statement)

    async def scalar(self, statement):
        return self.session.scalar(statement)

    async def execute(self, statement):
        return self.session.execute(statement)

    async def get(self, model, identity):
        return self.session.get(model, identity)


@pytest.fixture
def database():
    engine = create_engine("sqlite://")
    for model in (
        ModelDefinitionRecord, ModelDeploymentVersionRecord,
        ProfileRecord, ProfileModelBindingRecord, ProfileDeploymentBindingRecord,
        RagConfigurationRecord, AnswerPolicyVersionRecord, RagConfigurationVersionRecord,
        RagConfigurationWorkspaceSubscriptionRecord,
    ):
        # Exercise actual SELECTs and corrupt/missing relations without pretending
        # SQLite validates PostgreSQL-specific checks, indexes, or foreign keys.
        Table(model.__tablename__, MetaData(), *(
            Column(column.name, column.type, primary_key=column.primary_key,
                   nullable=column.nullable, server_default=column.server_default)
            for column in model.__table__.columns
        )).create(engine)
    queries = []

    @event.listens_for(engine, "before_cursor_execute")
    def count(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    with Session(engine) as session:
        yield session, SqlAlchemyRagConfigurationRepository(AwaitableSession(session)), queries
    engine.dispose()


def add_configuration(session, *, owner_id, name, versions=(1,), system=False):
    identity = RagConfigurationRecord(id=uuid4(), owner_id=owner_id, name=name, is_system=system)
    session.add(identity)
    indexing_id = uuid4()
    retrieval = ProfileRecord(
        id=uuid4(), kind="retrieval", name=name, version=1,
        config={"indexing_profile_id": str(indexing_id)}, evaluation_state="pending",
        is_default=False,
    )
    session.add(retrieval)
    for number in versions:
        policy = AnswerPolicyVersionRecord(
            id=uuid4(), configuration_id=identity.id, version=number, mode="extractive",
            min_semantic_score=0.8, min_keyword_coverage=0.7,
            require_complete_provenance=True, conflict_mode="separate_sources",
        )
        version = RagConfigurationVersionRecord(
            id=uuid4(), configuration_id=identity.id, version=number,
            document_processing_profile_id=uuid4(), indexing_profile_id=indexing_id,
            retrieval_profile_id=retrieval.id, generation_profile_id=None,
            answer_policy_version_id=policy.id, evaluation_state="pending", is_default=False,
        )
        session.add_all([policy, version])
        if not system:
            for workspace in (UUID(int=9), UUID(int=3)):
                session.add(RagConfigurationWorkspaceSubscriptionRecord(
                    configuration_version_id=version.id, workspace_id=workspace,
                ))
    session.commit()
    return identity.id


@pytest.mark.parametrize("count", [1, 16])
async def test_visible_list_has_bounded_queries_and_exact_latest_order(database, count):
    session, repository, queries = database
    actor = uuid4()
    for number in reversed(range(count)):
        add_configuration(session, owner_id=actor, name=f"owned-{number:02}", versions=(3, 1, 7))
    add_configuration(session, owner_id=None, name="system", system=True)
    add_configuration(session, owner_id=uuid4(), name="hidden", versions=())
    session.expunge_all()
    queries.clear()

    results = await repository.list_visible(actor)

    assert [item.name for item in results] == ["system", *[f"owned-{n:02}" for n in range(count)]]
    assert [item.version for item in results] == [1, *([7] * count)]
    assert results[0].workspace_ids == ()
    assert all(item.workspace_ids == (UUID(int=3), UUID(int=9)) for item in results[1:])
    assert len(queries) <= 4, f"List query count grew to {len(queries)}"


async def test_visible_list_rechecks_owner_and_handles_empty_result(database):
    session, repository, _queries = database
    actor = uuid4()
    identity_id = add_configuration(session, owner_id=actor, name="private")
    assert len(await repository.list_visible(actor)) == 1
    session.execute(update(RagConfigurationRecord).where(
        RagConfigurationRecord.id == identity_id,
    ).values(owner_id=uuid4()))
    session.commit()
    assert await repository.list_visible(actor) == []


@pytest.mark.parametrize("missing", ["version", "policy", "retrieval"])
async def test_visible_list_does_not_drop_broken_relations(database, missing):
    session, repository, _queries = database
    actor = uuid4()
    add_configuration(session, owner_id=actor, name="broken")
    model = {
        "version": RagConfigurationVersionRecord,
        "policy": AnswerPolicyVersionRecord,
        "retrieval": ProfileRecord,
    }[missing]
    session.execute(delete(model))
    session.commit()
    session.expunge_all()
    with pytest.raises(RuntimeError):
        await repository.list_visible(actor)


async def test_generation_components_use_exact_batched_ids_and_omit_missing(database):
    session, repository, queries = database
    binding = deployment()
    profile_id = uuid4()
    session.add(_version_record(binding))
    session.add(ModelDefinitionRecord(
        id=binding.model_definition_id, kind="llm", name="synthetic", version=1, config={},
    ))
    session.add(ProfileRecord(
        id=profile_id, kind="generation", name="synthetic", version=1,
        config={}, evaluation_state="pending", is_default=False,
    ))
    session.add(ProfileDeploymentBindingRecord(
        profile_id=profile_id, deployment_version_id=binding.id,
    ))
    session.commit()
    session.expunge_all()
    queries.clear()

    profiles = await repository.find_profiles((profile_id, uuid4(), profile_id))
    deployments = await repository.get_deployment_versions((binding.id, uuid4(), binding.id))
    models = await repository.get_model_definitions((binding.model_definition_id, uuid4()))

    assert set(profiles) == {profile_id}
    assert profiles[profile_id].deployment_version_id == binding.id
    assert set(deployments) == {binding.id}
    assert deployments[binding.id].provider_model_id == binding.provider_model_id
    assert set(models) == {binding.model_definition_id}
    assert len(queries) <= 4
    queries.clear()
    assert await repository.find_profiles(()) == {}
    assert await repository.get_deployment_versions(()) == {}
    assert await repository.get_model_definitions(()) == {}
    assert queries == []
