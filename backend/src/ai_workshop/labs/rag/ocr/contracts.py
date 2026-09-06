from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Self


class OcrConfigurationError(ValueError):
    pass


class OcrRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class OcrTextUnit:
    text: str
    confidence: float
    bbox: tuple[float, float, float, float]
    evidence_eligible: bool

    def __post_init__(self) -> None:
        left, top, right, bottom = self.bbox
        if not (0 <= left <= right <= 1 and 0 <= top <= bottom <= 1):
            raise OcrConfigurationError("OCR coordinates must use normalized image bounds.")


@dataclass(frozen=True, slots=True)
class OcrTableCell:
    text: str
    confidence: float
    bbox: tuple[float, float, float, float]
    row_index: int | None = None
    column_index: int | None = None
    evidence_eligible: bool = True

    def __post_init__(self) -> None:
        left, top, right, bottom = self.bbox
        if not (0 <= left <= right <= 1 and 0 <= top <= bottom <= 1):
            raise OcrConfigurationError("OCR coordinates must use normalized image bounds.")


@dataclass(frozen=True, slots=True)
class OcrResult:
    text_units: tuple[OcrTextUnit, ...]
    table_cells: tuple[OcrTableCell, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OcrRequest:
    image_path: Path
    media_type: str
    source_part: str
    image_sha256: str
    pixel_width: int
    pixel_height: int

    def __post_init__(self) -> None:
        if len(self.image_sha256) != 64:
            raise OcrConfigurationError("OCR requests require an image SHA-256 digest.")
        if self.pixel_width < 1 or self.pixel_height < 1:
            raise OcrConfigurationError("OCR requests require positive image dimensions.")


@dataclass(frozen=True, slots=True)
class OcrProfileSpec:
    pipeline_name: str
    pipeline_version: str
    detection_model_name: str
    recognition_model_name: str
    table_model_name: str
    languages: tuple[str, ...]
    confidence_threshold: float
    artifact_directories: dict[str, Path]

    @classmethod
    def create(
        cls,
        *,
        pipeline_name: str,
        pipeline_version: str,
        detection_model_name: str,
        recognition_model_name: str,
        table_model_name: str,
        languages: tuple[str, ...],
        confidence_threshold: float,
        artifact_directories: dict[str, Path],
    ) -> Self:
        if set(artifact_directories) != {"detection", "recognition", "table"}:
            raise OcrConfigurationError(
                "An OCR profile requires all required local model artifacts."
            )
        if not 0 <= confidence_threshold <= 1:
            raise OcrConfigurationError(
                "An OCR profile confidence threshold must be between zero and one."
            )
        return cls(
            pipeline_name=pipeline_name,
            pipeline_version=pipeline_version,
            detection_model_name=detection_model_name,
            recognition_model_name=recognition_model_name,
            table_model_name=table_model_name,
            languages=languages,
            confidence_threshold=confidence_threshold,
            artifact_directories=artifact_directories,
        )


class OcrRuntimePort(Protocol):
    def recognize(self, request: OcrRequest, profile: OcrProfileSpec) -> OcrResult: ...
