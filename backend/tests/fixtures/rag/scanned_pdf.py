from pathlib import Path

import pymupdf


def create_scanned_pdf(
    path: Path,
    *,
    rotation: int = 0,
    cropped: bool = False,
    text_first: bool = False,
    whitespace: bool = False,
) -> Path:
    """Synthetic scan with a red upper-left quarter; no private source material."""
    with pymupdf.open() as document:
        if text_first:
            page = document.new_page(width=240, height=160)
            page.insert_text((24, 32), "PUBLIC TEXT")
        page = document.new_page(width=240, height=160)
        page.draw_rect(pymupdf.Rect(20, 20, 120, 80), color=None, fill=(1, 0, 0))
        if whitespace:
            page.insert_text((24, 100), "   ")
        if cropped:
            page.set_cropbox(pymupdf.Rect(20, 20, 220, 140))
        page.set_rotation(rotation)
        document.save(path)
    return path


def create_mixed_page_pdf(
    path: Path,
    *,
    rotation: int = 0,
    cropped: bool = False,
    image_rects: tuple[tuple[float, float, float, float], ...] = ((40.25, 60.25, 140.25, 120.25),),
    overlay: bool = False,
) -> Path:
    """Public synthetic image plus independent native text on the same page."""
    with pymupdf.open() as raster_source:
        image_page = raster_source.new_page(width=100, height=60)
        image_page.draw_rect(image_page.rect, color=None, fill=(1, 0, 0))
        blob = image_page.get_pixmap().tobytes("png")
    with pymupdf.open() as document:
        page = document.new_page(width=240, height=160)
        for rect in image_rects:
            page.insert_image(pymupdf.Rect(rect), stream=blob, keep_proportion=False)
        page.insert_text((40, 45), "PUBLIC TEXT", fontsize=10)
        if overlay:
            page.insert_text((50, 90), "SAME TEXT", fontsize=10)
        if cropped:
            page.set_cropbox(pymupdf.Rect(20, 20, 220, 140))
        page.set_rotation(rotation)
        document.save(path)
    return path
