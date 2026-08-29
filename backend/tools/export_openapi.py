import json
from pathlib import Path

from ai_workshop.main import create_app

DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "build" / "openapi.json"


def export_openapi(output: Path = DEFAULT_OUTPUT) -> None:
    serialized = json.dumps(
        create_app().openapi(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"{serialized}\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    export_openapi()
