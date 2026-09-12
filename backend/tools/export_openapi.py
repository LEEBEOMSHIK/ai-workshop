import json
from pathlib import Path

from ai_workshop.main import create_app
from ai_workshop.public_app import create_public_app

DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "build" / "openapi.json"


def export_openapi(output: Path = DEFAULT_OUTPUT) -> None:
    schema = create_app().openapi()
    public_schema = create_public_app().openapi()
    for path, definition in public_schema.get("paths", {}).items():
        if path in schema["paths"]:
            raise RuntimeError(f"duplicate OpenAPI path: {path}")
        schema["paths"][path] = definition
    target_components = schema.setdefault("components", {})
    for category, definitions in public_schema.get("components", {}).items():
        target_definitions = target_components.setdefault(category, {})
        for name, definition in definitions.items():
            existing = target_definitions.get(name)
            if existing is not None and existing != definition:
                raise RuntimeError(f"conflicting OpenAPI component: {category}.{name}")
            target_definitions[name] = definition
    serialized = json.dumps(
        schema,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"{serialized}\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    export_openapi()
