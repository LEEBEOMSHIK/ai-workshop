from ai_workshop.main import create_app


def test_evaluation_run_created_at_is_a_required_datetime() -> None:
    schema = create_app().openapi()["components"]["schemas"]["EvaluationRunResponse"]

    assert "created_at" in schema["required"]
    assert schema["properties"]["created_at"] == {
        "format": "date-time",
        "title": "Created At",
        "type": "string",
    }
