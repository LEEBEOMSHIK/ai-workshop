import json
from collections.abc import Iterator
from importlib import import_module
from pathlib import Path
from typing import Any

from ai_workshop.main import create_app

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
EXPECTED_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/me",
    "/api/v1/documents/{document_id}/versions",
    "/api/v1/health",
    "/api/v1/jobs/{job_id}",
    "/api/v1/rag/models",
    "/api/v1/rag/profiles/{kind}",
    "/api/v1/rag/profiles/{kind}/yaml",
    "/api/v1/rag/profiles/{profile_id}/default",
    "/api/v1/workspaces",
    "/api/v1/workspaces/{workspace_id}/documents",
    "/api/v1/workspaces/{workspace_id}/folders",
}
PUBLIC_PATHS = {"/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/health"}
COMMON_ERROR_STATUSES = {"401", "404", "409", "422"}


def operations(schema: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method in HTTP_METHODS:
                yield path, operation


def test_openapi_has_all_public_paths_and_unique_operation_ids() -> None:
    schema = create_app().openapi()
    operation_ids = [operation["operationId"] for _, operation in operations(schema)]

    assert set(schema["paths"]) == EXPECTED_PATHS
    assert len(operation_ids) == len(set(operation_ids))


def test_openapi_documents_common_errors_and_cookie_security() -> None:
    schema = create_app().openapi()
    components = schema["components"]

    assert components["schemas"]["ErrorEnvelope"] == {
        "properties": {
            "error": {"$ref": "#/components/schemas/ErrorDetail"},
        },
        "required": ["error"],
        "title": "ErrorEnvelope",
        "type": "object",
    }
    assert components["securitySchemes"]["SessionCookie"] == {
        "in": "cookie",
        "name": "ai_workshop_session",
        "type": "apiKey",
    }

    for path, operation in operations(schema):
        for status in COMMON_ERROR_STATUSES:
            assert operation["responses"][status]["content"]["application/json"][
                "schema"
            ] == {"$ref": "#/components/schemas/ErrorEnvelope"}
        if path not in PUBLIC_PATHS:
            assert operation["security"] == [{"SessionCookie": []}]


def test_openapi_export_is_deterministic_sorted_json_with_a_final_newline(tmp_path: Path) -> None:
    exporter = import_module("tools.export_openapi")
    output = tmp_path / "openapi.json"

    exporter.export_openapi(output)
    first = output.read_text(encoding="utf-8")
    exporter.export_openapi(output)
    second = output.read_text(encoding="utf-8")

    parsed = json.loads(first)
    expected = json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert first == second == expected
