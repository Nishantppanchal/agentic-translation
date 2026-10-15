"""Word, PowerPoint and Excel files: the text is read straight from the file (no OCR) and the translation is written
back into a copy of it, keeping its layout and formatting.

    extract(data, fmt) → (segments, info)     segments with `loc` (where in the file) and `where` (for people);
                                              pictures are figure segments whose text the vision model reads later
    write(data, fmt, segments) → (bytes, report)

Word: office/word.py (python-docx) · PowerPoint: office/slides.py (python-pptx) · Excel: office/sheets.py (the
strings patched in the package; openpyxl reads the grid for the Layout view, office/view.py).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from . import pictures, sheets, slides, word
from .common import Report, number

FORMATS = {".docx": "docx", ".docm": "docx", ".pptx": "pptx", ".pptm": "pptx", ".xlsx": "xlsx", ".xlsm": "xlsx"}
MEDIA = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".docm": "application/vnd.ms-word.document.macroEnabled.12",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pptm": "application/vnd.ms-powerpoint.presentation.macroEnabled.12",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
}
LABEL = {"docx": "Word document", "pptx": "PowerPoint presentation", "xlsx": "Excel workbook"}
UNIT = {"docx": "part", "pptx": "slide", "xlsx": "sheet"}
_OLD = {
    ".doc": "Word 97–2003 files (.doc) aren't supported: save it as .docx in Word, or export it to PDF.",
    ".xls": "Excel 97–2003 files (.xls) aren't supported: save it as .xlsx in Excel, or export it to PDF.",
    ".ppt": "PowerPoint 97–2003 files (.ppt) aren't supported: save it as .pptx in PowerPoint, or export it to PDF.",
    ".odt": "OpenDocument files aren't supported yet: save it as .docx, or export it to PDF.",
    ".ods": "OpenDocument files aren't supported yet: save it as .xlsx, or export it to PDF.",
    ".odp": "OpenDocument files aren't supported yet: save it as .pptx, or export it to PDF.",
    ".dotx": "Templates aren't supported: save a document from the template (.docx).",
    ".dotm": "Templates aren't supported: save a document from the template (.docx).",
    ".potx": "Templates aren't supported: save a presentation from the template (.pptx).",
    ".xltx": "Templates aren't supported: save a workbook from the template (.xlsx).",
    ".rtf": "RTF isn't supported: save it as .docx, or export it to PDF.",
}
_MODULES = {"docx": word, "pptx": slides, "xlsx": sheets}


def detect(filename: str) -> str | None:
    """docx | pptx | xlsx for an Office file this app reads, else None."""
    return FORMATS.get(Path(filename).suffix.lower())


def unsupported(filename: str) -> str | None:
    """Why an Office-like file can't be read (an older or other format), else None."""
    return _OLD.get(Path(filename).suffix.lower())


def media_type(filename: str) -> str:
    return MEDIA.get(Path(filename).suffix.lower(), "application/octet-stream")


def check(data: bytes, fmt: str) -> None:
    """Raise ValueError (a message for the person) if the file can't be read."""
    if data[:4] == b"\xd0\xcf\x11\xe0":
        raise ValueError("This file is password-protected or in an old binary format: save it as a normal "
                         f"{LABEL[fmt]} ({'/'.join(k for k, v in FORMATS.items() if v == fmt)}) and try again.")
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise ValueError(f"This isn't a readable {LABEL[fmt]}.")
    try:
        units, _ = _MODULES[fmt].extract(data, pictures.Finder())  # a file of pictures only is fine
    except Exception as exc:  # noqa: BLE001 — any library error means the same to the person
        raise ValueError(f"Could not read the {LABEL[fmt]}: {exc}") from exc
    if not any(u.segments for u in units):
        raise ValueError(f"No text or pictures found in the {LABEL[fmt]}.")


def extract(data: bytes, fmt: str, *, read_pictures: bool = True, min_cm: float = 1.5,
            max_pictures: int = 60) -> tuple[list[dict], dict]:
    """→ (segments, info): info has the unit labels ("Part 1", "Slide 3", a sheet's name), what was left out,
    `pictures` (what was found and left out) and `picture_files` (sha1 → the bytes of each picture whose text is to
    be read: take them out before storing the info). `read_pictures=False`: no figure segments (pictures' alt texts
    are still segments)."""
    finder = pictures.Finder(min_cm, max_pictures, read=read_pictures)
    units, info = _MODULES[fmt].extract(data, finder)
    units = [u for u in units if u.segments]
    segments = number(units)
    pictures.finish(segments)
    info = {**info, "unit": UNIT[fmt], "page_labels": [u.label for u in units],
            "not_translated": {**info.get("not_translated", {}), **finder.not_translated()},
            "pictures": finder.summary(), "picture_files": finder.pictures}
    return segments, info


def write(data: bytes, fmt: str, segments: list[dict], *, marks: bool = False) -> tuple[bytes, Report]:
    """The original file with the translations written in. `marks` (Word, for the Layout view only): a hidden
    bookmark `_seg_<id>` at each segment's paragraph, to find it in the rendered page."""
    return _MODULES[fmt].write(data, segments, marks=marks)
