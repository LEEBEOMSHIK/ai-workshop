import json
from pathlib import Path
from typing import Any

import pytest

from ai_workshop.labs.rag.evaluation.vector_comparison.cli import main

FIXTURE = Path(__file__).resolve().parents[4] / "fixtures" / "rag" / "vector_comparison"


def _prepare(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    output = tmp_path / "plan.json"
    assert (
        main(
            [
                "prepare",
                "--snapshot",
                str(FIXTURE / "snapshot.json"),
                "--settings",
                str(FIXTURE / "settings.json"),
                "--targets",
                str(FIXTURE / "targets.json"),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    return output, json.loads(output.read_text(encoding="utf-8"))


def test_prepare_fixture_is_offline_reproducible_and_does_not_overwrite(tmp_path: Path) -> None:
    assert main(["validate", "--snapshot", str(FIXTURE / "snapshot.json")]) == 0
    output, bundle = _prepare(tmp_path)
    assert bundle["mode"] == "offline_preparation_only"
    assert len(bundle["plan"]["attempts"]) == 132
    assert len(bundle["requests"]) == 9
    assert sum(row["status"] == "skipped_empty_scope" for row in bundle["requests"]) == 3
    before = output.read_bytes()
    assert (
        main(
            [
                "prepare",
                "--snapshot",
                str(FIXTURE / "snapshot.json"),
                "--settings",
                str(FIXTURE / "settings.json"),
                "--targets",
                str(FIXTURE / "targets.json"),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert output.read_bytes() == before


def test_score_no_observations_reports_missing_not_zero_performance(tmp_path: Path) -> None:
    plan_path, bundle = _prepare(tmp_path)
    observations = tmp_path / "observations.json"
    observations.write_text(
        json.dumps(
            {
                "plan_digest": bundle["plan_digest"],
                "evidence_kind": "synthetic",
                "records": [],
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"
    assert (
        main(
            [
                "score",
                "--snapshot",
                str(FIXTURE / "snapshot.json"),
                "--plan",
                str(plan_path),
                "--observations",
                str(observations),
                "--output",
                str(report_path),
            ]
        )
        == 0
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "partial"
    assert report["execution_verified"] is False
    assert report["evidence_kind"] == "synthetic"
    for summary in report["engines"].values():
        assert summary["counts"]["observed"] == 0
        assert summary["counts"]["missing"] == 44
        assert summary["phases"]["repeated"]["latency_ms"]["p50"] is None


def test_score_rejects_tampered_requests_without_emitting_input(tmp_path: Path) -> None:
    plan_path, bundle = _prepare(tmp_path)
    bundle["requests"] = []
    plan_path.write_text(json.dumps(bundle), encoding="utf-8")
    output = tmp_path / "report.json"
    assert (
        main(
            [
                "score",
                "--snapshot",
                str(FIXTURE / "snapshot.json"),
                "--plan",
                str(plan_path),
                "--observations",
                str(tmp_path / "unused.json"),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert not output.exists()


@pytest.mark.parametrize("mutation", ["vector_boolean", "schema_boolean"])
def test_sealed_json_distinguishes_boolean_from_number(tmp_path: Path, mutation: str) -> None:
    plan_path, bundle = _prepare(tmp_path)
    if mutation == "vector_boolean":
        body = bundle["requests"][0]["request"]["body"]
        body["query"]["script_score"]["script"]["params"]["query_vector"][0] = True
    else:
        bundle["schema_version"] = True
    plan_path.write_text(json.dumps(bundle), encoding="utf-8")
    observations = tmp_path / "observations.json"
    observations.write_text(
        json.dumps(
            {
                "plan_digest": bundle["plan_digest"],
                "evidence_kind": "synthetic",
                "records": [],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "rejected.json"
    assert (
        main(
            [
                "score",
                "--snapshot",
                str(FIXTURE / "snapshot.json"),
                "--plan",
                str(plan_path),
                "--observations",
                str(observations),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert not output.exists()


@pytest.mark.parametrize(
    "raw",
    [
        '{"schema_version":1,"schema_version":2}',
        '{"bad":NaN}',
        '{"bad":Infinity}',
        '{"secret":"do-not-echo-value"}',
        "[]",
        "{",
    ],
)
def test_bad_input_is_rejected_without_payload_echo(
    raw: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "invalid.json"
    source.write_text(raw, encoding="utf-8")
    assert main(["validate", "--snapshot", str(source)]) == 2
    captured = capsys.readouterr()
    assert "do-not-echo-value" not in captured.err
    assert captured.out == ""


def test_fixture_input_remains_byte_identical(tmp_path: Path) -> None:
    original = {path: path.read_bytes() for path in FIXTURE.glob("*.json")}
    _prepare(tmp_path)
    assert all(path.read_bytes() == content for path, content in original.items())


def test_excessive_json_nesting_is_rejected_without_traceback(tmp_path: Path) -> None:
    source = tmp_path / "too_deep.json"
    source.write_text("[" * 50000 + "0" + "]" * 50000, encoding="utf-8")
    assert main(["validate", "--snapshot", str(source)]) == 2
