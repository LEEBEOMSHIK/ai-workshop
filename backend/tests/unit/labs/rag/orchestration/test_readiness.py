from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_workshop.labs.rag.deployments.domain import ExecutionLocation
from tests.unit.labs.rag.generation.test_readiness import (
    PROFILE_ID,
    VERSION_ID,
    deployment,
    readiness,
)
from tests.unit.labs.rag.orchestration.test_policy import configuration


@pytest.mark.parametrize("case,expected", [
    ("supported", True), ("schema1", False), ("retry", False),
    ("on_premise", False), ("invalid_policy", False),
])
async def test_sdk_readiness_requires_supported_binding_and_policy(case, expected):
    exact = deployment()
    if case == "retry":
        exact = replace(exact, max_retries=1)
    if case == "on_premise":
        exact = replace(exact, location=ExecutionLocation.ON_PREMISE)
    config = {"generation": {"response_schema_version": 1 if case == "schema1" else 2},
              "orchestration": None if case == "invalid_policy" else configuration()}
    target = readiness(SimpleNamespace(bindings=(), deployment_version_id=VERSION_ID,
                                      config=config),
                       SimpleNamespace(status="ready", safe_error_code=None,
                                       observed_provider_model_id=exact.provider_model_id))
    target.deployments.get_version = AsyncMock(return_value=exact)
    assert await target.is_ready(PROFILE_ID) is expected
