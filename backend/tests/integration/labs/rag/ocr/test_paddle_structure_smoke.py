import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from ai_workshop.labs.rag.ocr.artifacts import verify_artifacts
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
ACTUAL_SMOKE = pytest.mark.skipif(
    os.environ.get("AI_WORKSHOP_OCR_ACTUAL_SMOKE") != "1",
    reason="Set AI_WORKSHOP_OCR_ACTUAL_SMOKE=1 to run actual OCR inference.",
)


@dataclass(frozen=True, slots=True)
class SmokeFixture:
    text_image: Path
    table_image: Path
    text_tokens: tuple[str, str]
    table_tokens: tuple[str, str]


def test_smoke_runtime_paths_and_device_are_configurable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "manifest.json"
    cache = tmp_path / "models"
    monkeypatch.setenv("AI_WORKSHOP_OCR_SMOKE_MANIFEST_PATH", str(manifest))
    monkeypatch.setenv("AI_WORKSHOP_MODEL_CACHE_ROOT", str(cache))
    monkeypatch.setenv("AI_WORKSHOP_OCR_SMOKE_DEVICE", "cpu")

    assert smoke_manifest_path() == manifest
    assert smoke_cache_root() == cache
    assert smoke_device() == "cpu"


def test_linux_fixture_uses_portable_font_and_expected_tokens(tmp_path: Path) -> None:
    fixture = create_smoke_fixture(tmp_path, platform="linux")

    assert fixture.text_tokens == ("POLICY", "7%")
    assert fixture.table_tokens == ("EQUITY", "7%")
    assert fixture.text_image.is_file()
    assert fixture.table_image.is_file()


def smoke_manifest_path() -> Path:
    configured = os.environ.get("AI_WORKSHOP_OCR_SMOKE_MANIFEST_PATH")
    return Path(configured) if configured else MANIFEST_PATH


def smoke_cache_root() -> Path:
    configured = os.environ.get("AI_WORKSHOP_MODEL_CACHE_ROOT")
    return Path(configured) if configured else REPOSITORY_ROOT / ".local-data" / "models"


def smoke_device() -> str:
    return os.environ.get("AI_WORKSHOP_OCR_SMOKE_DEVICE", "cpu")


def create_smoke_fixture(tmp_path: Path, *, platform: str) -> SmokeFixture:
    if platform == "windows":
        font_path = Path("C:/Windows/Fonts/malgun.ttf")
        if not font_path.is_file():
            raise RuntimeError("The Windows Korean smoke-test font is unavailable.")
        text_font = ImageFont.truetype(str(font_path), 92)
        table_font = ImageFont.truetype(str(font_path), 58)
        text_value = "운용 한도 7%"
        table_values = ("항목", "비율", "주식", "7%", "채권", "20%")
        text_tokens = ("운용", "7%")
        table_tokens = ("주식", "7%")
    else:
        text_font = ImageFont.load_default(size=92)
        table_font = ImageFont.load_default(size=58)
        text_value = "POLICY LIMIT 7%"
        table_values = ("ITEM", "RATIO", "EQUITY", "7%", "BOND", "20%")
        text_tokens = ("POLICY", "7%")
        table_tokens = ("EQUITY", "7%")

    text_image = Image.new("RGB", (1200, 360), "white")
    text_draw = ImageDraw.Draw(text_image)
    text_draw.text((80, 110), text_value, font=text_font, fill="black")
    text_path = tmp_path / "policy.png"
    text_image.save(text_path)

    table_image = Image.new("RGB", (1200, 720), "white")
    table_draw = ImageDraw.Draw(table_image)
    for x in (100, 600, 1100):
        table_draw.line((x, 100, x, 620), fill="black", width=6)
    for y in (100, 270, 440, 620):
        table_draw.line((100, y, 1100, y), fill="black", width=6)
    for position, text in zip(
        ((180, 150), (720, 150), (180, 320), (720, 320), (180, 490), (720, 490)),
        table_values,
        strict=True,
    ):
        table_draw.text(position, text, font=table_font, fill="black")
    table_path = tmp_path / "table.png"
    table_image.save(table_path)
    return SmokeFixture(text_path, table_path, text_tokens, table_tokens)


@pytest.mark.integration
@ACTUAL_SMOKE
def test_pinned_paddle_runtime_packages_are_installed() -> None:
    assert version("paddlepaddle") == "3.2.2"
    assert version("paddleocr") == "3.7.0"
    assert version("paddlex") == "3.7.2"


@pytest.mark.integration
@ACTUAL_SMOKE
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
@ACTUAL_SMOKE
def test_pinned_models_recognize_text_table_and_normalized_bbox(
    tmp_path: Path,
) -> None:
    manifest = json.loads(smoke_manifest_path().read_text(encoding="utf-8"))
    cache_root = smoke_cache_root()
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
    verify_artifacts(manifest_path=smoke_manifest_path(), cache_root=cache_root)
    fixture = create_smoke_fixture(
        tmp_path,
        platform="windows" if sys.platform == "win32" else "linux",
    )
    image_path = fixture.text_image
    with Image.open(image_path) as image:
        pixel_width, pixel_height = image.size
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
        device=smoke_device(),
    )

    adapter = PaddleStructureV3Adapter()
    result = adapter.recognize(
        OcrRequest(
            image_path=image_path,
            media_type="image/png",
            source_part="word/media/image1.png",
            image_sha256=hashlib.sha256(content).hexdigest(),
            pixel_width=pixel_width,
            pixel_height=pixel_height,
        ),
        profile,
    )

    recognized = " ".join(unit.text for unit in result.text_units)
    assert all(token in recognized for token in fixture.text_tokens)
    assert all(
        0 <= coordinate <= 1
        for unit in result.text_units
        for coordinate in unit.bbox
    )

    table_path = fixture.table_image
    with Image.open(table_path) as table_image:
        table_width, table_height = table_image.size
    table_content = table_path.read_bytes()

    table_result = adapter.recognize(
        OcrRequest(
            image_path=table_path,
            media_type="image/png",
            source_part="word/media/image2.png",
            image_sha256=hashlib.sha256(table_content).hexdigest(),
            pixel_width=table_width,
            pixel_height=table_height,
        ),
        profile,
    )

    table_text = " ".join(cell.text for cell in table_result.table_cells)
    assert all(token in table_text for token in fixture.table_tokens)
    assert all(
        0 <= coordinate <= 1
        for cell in table_result.table_cells
        for coordinate in cell.bbox
    )
