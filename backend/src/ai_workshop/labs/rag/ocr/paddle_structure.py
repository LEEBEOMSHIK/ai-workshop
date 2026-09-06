from collections.abc import Callable, Iterable, Mapping, Sequence
from importlib import import_module
from typing import Protocol, cast

from ai_workshop.labs.rag.ocr.contracts import (
    OcrProfileSpec,
    OcrRequest,
    OcrResult,
    OcrRuntimeError,
    OcrTableCell,
    OcrTextUnit,
)


class _Prediction(Protocol):
    @property
    def json(self) -> Mapping[str, object]: ...


class _PaddleRuntime(Protocol):
    def predict(self, *, input: str) -> Iterable[_Prediction]: ...


RuntimeFactory = Callable[[OcrProfileSpec], _PaddleRuntime]


class PaddleStructureV3Adapter:
    def __init__(self, runtime_factory: RuntimeFactory | None = None) -> None:
        self._runtime_factory = runtime_factory or _create_runtime
        self._runtime: _PaddleRuntime | None = None

    def recognize(self, request: OcrRequest, profile: OcrProfileSpec) -> OcrResult:
        missing = [
            role
            for role, directory in profile.artifact_directories.items()
            if not directory.is_dir()
        ]
        if missing:
            raise OcrRuntimeError(
                "ocr_model_artifact_missing",
                "A required local OCR model artifact is unavailable.",
            )
        if not request.image_path.is_file():
            raise OcrRuntimeError("embedded_image_corrupt", "The OCR input image is unavailable.")
        try:
            if self._runtime is None:
                self._runtime = self._runtime_factory(profile)
            predictions = tuple(self._runtime.predict(input=str(request.image_path)))
        except OcrRuntimeError:
            raise
        except Exception as exc:
            raise OcrRuntimeError(
                "ocr_runtime_unavailable",
                "The configured OCR runtime could not process the image.",
            ) from exc
        if len(predictions) != 1:
            raise OcrRuntimeError(
                "ocr_output_invalid",
                "The OCR runtime returned an invalid image result count.",
            )
        return _normalize_result(predictions[0].json, request=request, profile=profile)


def _normalize_result(
    value: Mapping[str, object],
    *,
    request: OcrRequest,
    profile: OcrProfileSpec,
) -> OcrResult:
    result = _mapping(value.get("res"))
    overall = _mapping(result.get("overall_ocr_res"))
    texts = _sequence(overall.get("rec_texts"))
    scores = _sequence(overall.get("rec_scores"))
    boxes = _sequence(overall.get("rec_boxes"))
    if not (len(texts) == len(scores) == len(boxes)):
        raise OcrRuntimeError("ocr_output_invalid", "The OCR text result is inconsistent.")

    units: list[OcrTextUnit] = []
    has_low_confidence = False
    for text, score, box in zip(texts, scores, boxes, strict=True):
        if not isinstance(text, str) or not isinstance(score, int | float):
            raise OcrRuntimeError("ocr_output_invalid", "The OCR text result is invalid.")
        confidence = float(score)
        eligible = confidence >= profile.confidence_threshold
        has_low_confidence = has_low_confidence or not eligible
        units.append(
            OcrTextUnit(
                text=text,
                confidence=confidence,
                bbox=_normalize_box(box, request=request),
                evidence_eligible=eligible,
            )
        )

    table_cells: list[OcrTableCell] = []
    raw_tables = result.get("table_res_list")
    table_values = () if raw_tables is None else _sequence(raw_tables)
    for table_value in table_values:
        table = _mapping(table_value)
        table_ocr = _mapping(table.get("table_ocr_pred"))
        cell_texts = _sequence(table_ocr.get("rec_texts"))
        cell_scores = _sequence(table_ocr.get("rec_scores"))
        cell_boxes = _sequence(table_ocr.get("rec_boxes"))
        if not (len(cell_texts) == len(cell_scores) == len(cell_boxes)):
            raise OcrRuntimeError("ocr_output_invalid", "The OCR table result is inconsistent.")
        for text, score, box in zip(cell_texts, cell_scores, cell_boxes, strict=True):
            if not isinstance(text, str) or not isinstance(score, int | float):
                raise OcrRuntimeError("ocr_output_invalid", "The OCR table result is invalid.")
            confidence = float(score)
            eligible = confidence >= profile.confidence_threshold
            has_low_confidence = has_low_confidence or not eligible
            table_cells.append(
                OcrTableCell(
                    text=text,
                    confidence=confidence,
                    bbox=_normalize_box(box, request=request),
                    evidence_eligible=eligible,
                )
            )
    warnings = ("ocr_confidence_below_threshold",) if has_low_confidence else ()
    return OcrResult(
        text_units=tuple(units),
        table_cells=tuple(table_cells),
        warnings=warnings,
    )


def _normalize_box(value: object, *, request: OcrRequest) -> tuple[float, float, float, float]:
    coordinates = _sequence(value)
    if len(coordinates) != 4:
        raise OcrRuntimeError("ocr_output_invalid", "The OCR bounding box is invalid.")
    numeric_coordinates: list[float] = []
    for item in coordinates:
        if not isinstance(item, int | float):
            raise OcrRuntimeError("ocr_output_invalid", "The OCR bounding box is invalid.")
        numeric_coordinates.append(float(item))
    left, top, right, bottom = numeric_coordinates
    normalized = (
        left / request.pixel_width,
        top / request.pixel_height,
        right / request.pixel_width,
        bottom / request.pixel_height,
    )
    try:
        OcrTextUnit("validation", 1.0, normalized, True)
    except ValueError as exc:
        raise OcrRuntimeError("ocr_output_invalid", "The OCR bounding box is invalid.") from exc
    return normalized


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise OcrRuntimeError("ocr_output_invalid", "The OCR result is not an object.")
    return cast(Mapping[str, object], value)


def _sequence(value: object) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise OcrRuntimeError("ocr_output_invalid", "The OCR result is not a sequence.")
    return cast(Sequence[object], value)


def _create_runtime(profile: OcrProfileSpec) -> _PaddleRuntime:
    try:
        runtime_type = cast(
            Callable[..., _PaddleRuntime],
            vars(import_module("paddleocr"))["PPStructureV3"],
        )
        names = profile.model_names
        directories = profile.artifact_directories
        runtime = runtime_type(
            device=profile.device,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            use_formula_recognition=False,
            use_seal_recognition=False,
            use_chart_recognition=False,
            use_region_detection=False,
            use_table_recognition=True,
            layout_detection_model_name=names["layout"],
            layout_detection_model_dir=str(directories["layout"]),
            text_detection_model_name=names["detection"],
            text_detection_model_dir=str(directories["detection"]),
            text_recognition_model_name=names["recognition"],
            text_recognition_model_dir=str(directories["recognition"]),
            textline_orientation_model_name=names["textline_orientation"],
            textline_orientation_model_dir=str(directories["textline_orientation"]),
            table_classification_model_name=names["table_classification"],
            table_classification_model_dir=str(directories["table_classification"]),
            wired_table_structure_recognition_model_name=names[
                "wired_table_structure"
            ],
            wired_table_structure_recognition_model_dir=str(
                directories["wired_table_structure"]
            ),
            wireless_table_structure_recognition_model_name=names[
                "wireless_table_structure"
            ],
            wireless_table_structure_recognition_model_dir=str(
                directories["wireless_table_structure"]
            ),
            wired_table_cells_detection_model_name=names["wired_table_cells"],
            wired_table_cells_detection_model_dir=str(
                directories["wired_table_cells"]
            ),
            wireless_table_cells_detection_model_name=names[
                "wireless_table_cells"
            ],
            wireless_table_cells_detection_model_dir=str(
                directories["wireless_table_cells"]
            ),
            table_orientation_classify_model_name=names["table_orientation"],
            table_orientation_classify_model_dir=str(
                directories["table_orientation"]
            ),
        )
    except Exception as exc:
        raise OcrRuntimeError(
            "ocr_runtime_unavailable",
            "The configured PaddleOCR runtime is unavailable.",
        ) from exc
    return runtime
