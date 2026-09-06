from typing import Annotated

from fastapi import APIRouter, Depends

from ai_workshop.platform.identity.api import require_owner
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.runtime_topology.schemas import RuntimeTopologyResponse
from ai_workshop.platform.runtime_topology.service import RuntimeTopologyService

router = APIRouter(prefix="/api/v1/admin/system", tags=["admin-system"])


def get_runtime_topology_service() -> RuntimeTopologyService:
    return RuntimeTopologyService()


@router.get("/runtime-topology", response_model=RuntimeTopologyResponse)
async def get_runtime_topology(
    _user: Annotated[User, Depends(require_owner)],
    service: Annotated[RuntimeTopologyService, Depends(get_runtime_topology_service)],
) -> RuntimeTopologyResponse:
    return RuntimeTopologyResponse.from_domain(service.load())
