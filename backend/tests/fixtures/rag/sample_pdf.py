from pathlib import Path

import pymupdf


def create_sample_pdf(path: Path) -> Path:
    document = pymupdf.open()
    first_page = document.new_page(width=240, height=160)
    first_page.insert_text((24, 32), "PUBLIC RISK LIMIT")
    first_page.insert_text((24, 64), "Synthetic first page.")
    second_page = document.new_page(width=240, height=160)
    second_page.insert_text((24, 32), "PUBLIC REPORT DATE")
    document.save(path)
    document.close()
    return path


def create_image_only_pdf(path: Path) -> Path:
    document = pymupdf.open()
    page = document.new_page(width=240, height=160)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.Rect(0, 0, 1, 1), False)
    pixmap.set_pixel(0, 0, (255, 255, 255))
    page.insert_image(pymupdf.Rect(24, 24, 96, 96), pixmap=pixmap)
    document.save(path)
    document.close()
    return path
