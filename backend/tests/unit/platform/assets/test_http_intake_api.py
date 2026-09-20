from fastapi.routing import APIRoute

from ai_workshop.platform.assets.api import router


def test_upload_routes_do_not_declare_framework_parsed_bodies():
    routes = [
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.methods == {"POST"}
        and route.path
        in {
            "/api/v1/workspaces/{workspace_id}/documents",
            "/api/v1/documents/{document_id}/versions",
        }
    ]
    assert len(routes) == 2
    for route in routes:
        assert route.body_field is None
        assert route.openapi_extra["requestBody"]["content"]["multipart/form-data"]
