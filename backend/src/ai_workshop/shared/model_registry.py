"""Load every SQLAlchemy model used by application and worker processes."""


def load_models() -> None:
    from ai_workshop.labs.rag.documents import models as rag_document_models
    from ai_workshop.labs.rag.ingestion import models as rag_ingestion_models
    from ai_workshop.labs.rag.models import models as rag_models
    from ai_workshop.platform.assets import models as asset_models
    from ai_workshop.platform.identity import models as identity_models
    from ai_workshop.platform.jobs import models as job_models
    from ai_workshop.platform.workspaces import models as workspace_models

    _ = (
        asset_models.AssetVersionRecord,
        identity_models.UserRecord,
        job_models.JobRecord,
        rag_document_models.RagIndexBuildRecord,
        rag_ingestion_models.RagIngestionJobRecord,
        rag_models.ModelDefinitionRecord,
        workspace_models.WorkspaceRecord,
    )
