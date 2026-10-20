"""Prepare a local report from approved synthetic exports. Never executes a model.

Use the project's approved Python environment with backend/src on PYTHONPATH.
The reviewed experiment JSON contains classification, capture_kind, and the exact
prefix/original/replacement/suffix instruction_change. Review criteria live in a
separate JSON object keyed by case UUID. Existing output directories are refused.
"""

import argparse
import json
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from ai_workshop.labs.rag.evaluation.offline_input_artifacts import load_records
from ai_workshop.labs.rag.evaluation.offline_input_diagnosis import (
    InstructionChange,
    object_value,
    parse_object,
)
from ai_workshop.labs.rag.evaluation.offline_input_report import (
    build_report,
    write_report,
)
from ai_workshop.labs.rag.evaluation.offline_rubric import Rubric


def main() -> None:
    from typing import Literal

    class Experiment(BaseModel):
        model_config = ConfigDict(extra="forbid")
        classification: Literal["public_synthetic"]
        capture_kind: Literal["actual_capture", "synthetic_fixture"]
        instruction_change: InstructionChange

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    experiment = Experiment.model_validate(
        parse_object(args.experiment.read_text(encoding="utf-8"))
    )
    records = load_records(
        parse_object(args.captures.read_text(encoding="utf-8")),
        parse_object(args.results.read_text(encoding="utf-8")), kind=experiment.capture_kind,
    )
    reviews = {UUID(key): Rubric.model_validate(object_value(value)) for key, value in
               parse_object(args.reviews.read_text(encoding="utf-8")).items()}
    report = build_report(records, experiment.instruction_change, reviews)
    write_report(report, args.output)
    print(json.dumps({"report": str(args.output / "index.html"), "attempts": len(records),
                      "prepared_candidates": 3 * len(records), "model_calls": 0,
                      "execution_status": "not_run"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
