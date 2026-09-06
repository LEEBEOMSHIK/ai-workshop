import hashlib
import json
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from ai_workshop.labs.rag.ocr.contracts import OcrProfileSpec, OcrRequest
from ai_workshop.labs.rag.ocr.paddle_structure import PaddleStructureV3Adapter

REPOSITORY_ROOT = Path(__file__).resolve().parents[6]
MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "model-profiles"
    / "rag"
    / "ocr"
    / "pp-structure-v3-v1.json"
)


@pytest.mark.integration
def test_pinned_paddle_runtime_packages_are_installed() -> None:
    assert version("paddlepaddle") == "3.2.2"
    assert version("paddleocr") == "3.7.0"


@pytest.mark.integration
def test_paddleocr_imports_in_a_fresh_worker_process() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "import paddleocr; print(paddleocr.__version__)"],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().endswith("3.7.0")


@pytest.mark.integration
def test_pinned_models_recognize_korean_text_and_normalized_bbox(
    tmp_path: Path,
) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    cache_root = REPOSITORY_ROOT / ".local-data" / "models"
    models = manifest["models"]
    directories = {
        model["runtime_role"]: (
            cache_root
            / "ocr"
            / model["model_kind"]
            / model["artifact_sha256"]
        )
        for model in models
    }
    if not all(directory.is_dir() for directory in directories.values()):
        pytest.skip("Pinned PP-StructureV3 artifacts are not provisioned.")
    font_path = Path("C:/Windows/Fonts/malgun.ttf")
    if not font_path.is_file():
        pytest.skip("The Windows Korean smoke-test font is unavailable.")
    image_path = tmp_path / "korean-policy.png"
    image = Image.new("RGB", (1200, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.text(
        (80, 110),
        "운용 한도 7%",
        font=ImageFont.truetype(str(font_path), 92),
        fill="black",
    )
    image.save(image_path)
    content = image_path.read_bytes()
    profile = OcrProfileSpec.create(
        pipeline_name=manifest["pipeline"]["name"],
        pipeline_version=manifest["pipeline"]["package_version"],
        model_names={
            model["runtime_role"]: model["name"] for model in models
        },
        languages=("ko", "en"),
        confidence_threshold=0.5,
        artifact_directories=directories,
        device="cpu",
    )

    adapter = PaddleStructureV3Adapter()
    result = adapter.recognize(
        OcrRequest(
            image_path=image_path,
            media_type="image/png",
            source_part="word/media/image1.png",
            image_sha256=hashlib.sha256(content).hexdigest(),
            pixel_width=image.width,
            pixel_height=image.height,
        ),
        profile,
    )

    recognized = " ".join(unit.text for unit in result.text_units)
    assert "운용" in recognized
    assert "7%" in recognized
    assert all(
        0 <= coordinate <= 1
        for unit in result.text_units
        for coordinate in unit.bbox
    )

    table_path = tmp_path / "korean-table.png"
    table_image = Image.new("RGB", (1200, 720), "white")
    table_draw = ImageDraw.Draw(table_image)
    for x in (100, 600, 1100):
        table_draw.line((x, 100, x, 620), fill="black", width=6)
    for y in (100, 270, 440, 620):
        table_draw.line((100, y, 1100, y), fill="black", width=6)
    table_font = ImageFont.truetype(str(font_path), 58)
    for position, text in (
        ((180, 150), "항목"),
        ((720, 150), "비율"),
        ((180, 320), "주식"),
        ((720, 320), "7%"),
        ((180, 490), "채권"),
        ((720, 490), "20%"),
    ):
        table_draw.text(position, text, font=table_font, fill="black")
    table_image.save(table_path)
    table_content = table_path.read_bytes()

    table_result = adapter.recognize(
        OcrRequest(
            image_path=table_path,
            media_type="image/png",
            source_part="word/media/image2.png",
            image_sha256=hashlib.sha256(table_content).hexdigest(),
            pixel_width=table_image.width,
            pixel_height=table_image.height,
        ),
        profile,
    )

    table_text = " ".join(cell.text for cell in table_result.table_cells)
    assert "주식" in table_text
    assert "7%" in table_text
    assert all(
        0 <= coordinate <= 1
        for cell in table_result.table_cells
        for coordinate in cell.bbox
    )
