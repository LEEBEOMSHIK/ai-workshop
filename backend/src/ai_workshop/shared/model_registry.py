"""Load every SQLAlchemy model used by application and worker processes."""


def load_models() -> None:
    from ai_workshop.labs.rag.documents import models as rag_document_models
    from ai_workshop.labs.rag.domains import models as rag_domain_models
    from ai_workshop.labs.rag.evaluation import models as rag_evaluation_models
    from ai_workshop.labs.rag.generation import codex_slot_models, codex_verification_models
    from ai_workshop.labs.rag.ingestion import models as rag_ingestion_models
    from ai_workshop.labs.rag.models import models as rag_models
    from ai_workshop.platform.assets import models as asset_models
    from ai_workshop.platform.assets import purge_models as asset_purge_models
    from ai_workshop.platform.assets import trash_models as asset_trash_models
    from ai_workshop.platform.identity import models as identity_models
    from ai_workshop.platform.jobs import models as job_models
    from ai_workshop.platform.learning import models as learning_models
    from ai_workshop.platform.workspaces import models as workspace_models

    _ = (
        asset_models.AssetVersionRecord,
        asset_purge_models.AssetPurgeJobRecord,
        asset_purge_models.AssetPurgeDispatchRecord,
        asset_trash_models.AssetRetentionPolicyRecord,
        asset_trash_models.AssetTrashBatchRecord,
        identity_models.UserRecord,
        job_models.JobRecord,
        learning_models.LearningRecordRow,
        learning_models.LearningRecordRevisionRow,
        rag_document_models.RagIndexBuildRecord,
        rag_domain_models.RagDomainRecord,
        rag_evaluation_models.EvaluationRunRecord,
        codex_slot_models.CodexExecutionSlotRecord,
        codex_verification_models.CodexVerificationAttemptRecord,
        codex_verification_models.CodexStageAuditRecord,
        rag_ingestion_models.RagIngestionJobRecord,
        rag_models.ModelDefinitionRecord,
        workspace_models.WorkspaceRecord,
    )
