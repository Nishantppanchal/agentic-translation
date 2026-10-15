"""Pictures in Word, PowerPoint and Excel files: the text inside them is read by the vision model (as for a PDF's
figures) and translated; the translation goes back as the picture's alt text, plus a caption under it in Word and a
line in the slide's notes in PowerPoint (the picture itself can't be changed).

Each format's reader hands every picture it meets to a `Finder`, which decides what becomes a figure segment:
decorative pictures, small ones (icons, bullets, logos in a corner), vector formats the model can't look at
(EMF/WMF) and any beyond the limit are left out and counted. A picture used more than once (a logo on every slide)
is one segment, read and translated once, written back at every place it is used (`locs`).

A picture's own alt text (what its author wrote in Office's alt-text pane, not a file name) is a segment of kind
"alt" right before its figure — also for pictures whose text isn't read (small, EMF, over the limit). Written back,
the alt text is its translation, followed by the picture's text: "<alt text> — Text in the picture: <English>".
"""

from __future__ import annotations

import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass, field

from .common import A, R, has_letters, local, q

WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"

EMU_PER_CM = 360_000
MAX_SIDE = 2000  # px: the long side of the image the model looks at
VECTOR = {"image/x-emf", "image/x-wmf", "image/emf", "image/wmf", "image/x-pict"}
RASTER = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/bmp", "image/x-ms-bmp", "image/tiff", "image/webp"}
EXTENSION = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "jpe": "image/jpeg", "gif": "image/gif",
             "bmp": "image/bmp", "tif": "image/tiff", "tiff": "image/tiff", "webp": "image/webp", "emf": "image/x-emf",
             "wmf": "image/x-wmf", "svg": "image/svg+xml"}
_FILE_NAME = re.compile(r"^[^/\\]*\.(?:png|jpe?g|gif|bmp|tiff?|emf|wmf|svg|webp|heic)$", re.I)
PICTURE_TEXT = "Text in the picture: "
SKIPPED_LABEL = {"vector": "pictures in EMF/WMF format (not read)", "format": "pictures in other formats (not read)",
                 "limit": "pictures over the limit (not read)", "linked": "linked pictures (not read)",
                 "not_read": "pictures (their text not read)"}


@dataclass
class Picture:
    sha1: str
    blob: bytes
    content_type: str


def digest(blob: bytes) -> str:
    return hashlib.sha1(blob).hexdigest()


def decorative(nv_props) -> bool:
    """Marked "decorative" in Office's alt-text pane (an extension of the shape's properties)."""
    return nv_props is not None and any(local(el) == "decorative" and el.get("val", "1") in ("1", "true")
                                        for el in nv_props.iter())


def describe(nv_props, text: str) -> bool:
    """Set a picture's alt text (`descr` of its cNvPr / docPr) → whether it changed."""
    if nv_props is None or nv_props.get("descr") == text:
        return False
    nv_props.set("descr", text)
    return True


def content_type_of(name: str) -> str:
    return EXTENSION.get(name.rsplit(".", 1)[-1].lower(), "application/octet-stream")


def alt_source(descr: str | None) -> str | None:
    """A picture's alt text worth translating: written by a person — not empty, not just a file name ("image1.png",
    which Office puts there), not without letters."""
    text = (descr or "").strip()
    return text if text and has_letters(text) and not _FILE_NAME.match(text) else None


@dataclass
class Finder:
    """Collects the pictures of one file as a reader walks it, in reading order."""

    min_cm: float = 1.5
    max_pictures: int = 60
    read: bool = True  # False: the text in pictures isn't read (no figure segments); their alt text still is a segment
    pictures: dict[str, Picture] = field(default_factory=dict)  # sha1 → the picture
    stubs: dict[str, dict] = field(default_factory=dict)  # sha1 → its figure segment
    alts: dict[tuple[str, str], dict] = field(default_factory=dict)  # (picture, alt text) → its alt segment
    found: int = 0
    skipped: Counter = field(default_factory=Counter)

    def add(self, loc: str, where: str, blob: bytes | None, content_type: str, size_emu: tuple[int, int] | None,
            nv_props, *, linked: bool = False, descr: str | None = None) -> list[dict]:
        """A picture at `loc` → its new segments: its alt text (if it has one of its own) and its figure (unless the
        picture is left out, or was seen before: then this place is added to the earlier segments)."""
        self.found += 1
        if decorative(nv_props):
            self.skipped["decorative"] += 1
            return []
        sha = digest(blob) if blob is not None and not linked else ""
        out = []
        if (text := alt_source(descr)) is not None:
            key = (sha or loc, text)
            if (seen := self.alts.get(key)) is not None:
                seen["locs"].append(f"{loc}#alt")
            else:
                alt = {"id": "", "page": 0, "kind": "alt", "source": text, "target": None, "translatable": True,
                       "where": f"{where} · alt text", "loc": f"{loc}#alt", "locs": [f"{loc}#alt"]}
                self.alts[key] = alt
                out.append(alt)
        if (stub := self._figure(loc, where, blob, content_type, size_emu, linked, sha)) is not None:
            out.append(stub)
        return out

    def _figure(self, loc, where, blob, content_type, size_emu, linked, sha) -> dict | None:
        if not self.read:
            self.skipped["not_read"] += 1
            return None
        if linked or blob is None:
            self.skipped["linked"] += 1
            return None
        if size_emu and all(size_emu) and min(size_emu) < self.min_cm * EMU_PER_CM:
            self.skipped["small"] += 1
            return None
        ct = (content_type or "").lower()
        if ct in VECTOR:
            self.skipped["vector"] += 1
            return None
        if ct not in RASTER:
            self.skipped["format"] += 1
            return None
        if (seen := self.stubs.get(sha)) is not None:
            seen["locs"].append(loc)
            return None
        if len(self.stubs) >= self.max_pictures:
            self.skipped["limit"] += 1
            return None
        self.pictures[sha] = Picture(sha, blob, ct)
        stub = {"id": "", "page": 0, "kind": "figure", "source": "", "target": "", "translatable": False,
                "where": where, "loc": loc, "locs": [loc], "sha1": sha}
        self.stubs[sha] = stub
        return stub

    def summary(self) -> dict:
        """What the file holds (kept with the document) — `files` (the bytes) are taken out before it's stored."""
        return {"found": self.found, "segments": len(self.stubs), "alt_texts": len(self.alts), "skipped": dict(self.skipped)}

    def not_translated(self) -> dict[str, int]:
        return {SKIPPED_LABEL[k]: n for k, n in self.skipped.items() if k in SKIPPED_LABEL}


def finish(segments: list[dict]) -> None:
    """After numbering: each figure's number on its page, its image's name, and where else it is used."""
    count: Counter = Counter()
    for seg in segments:
        if seg.get("kind") == "alt" and (more := len(seg.get("locs", [])) - 1) > 0:
            seg["where"] = seg["where"].replace(" · alt text", f" (+{more} more) · alt text")
        if seg.get("kind") != "figure":
            continue
        count[seg["page"]] += 1
        seg["figure"] = count[seg["page"]]
        seg["image"] = f"figure-p{seg['page']}-{seg['figure']}.png"
        if (more := len(seg.get("locs", [])) - 1) > 0:
            seg["where"] = f"{seg['where']} (+{more} more)"


def count_figures(segments: list[dict], report) -> None:
    """Figures and alt texts in the writer's totals: written when they had a translation (and their picture was
    still there)."""
    for seg in segments:
        if seg.get("kind") not in ("figure", "alt") or seg["id"] in report.mismatch:
            continue
        if seg.get("translatable", True) and plain_lines(seg.get("target") or ""):
            report.written += 1
        else:
            report.unchanged += 1


def to_png(blob: bytes) -> bytes | None:
    """The picture as a PNG the model can read (the long side at most MAX_SIDE px), or None if it can't be opened."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(blob)) as img:
            img.seek(0)
            img.load()
            if img.mode not in ("RGB", "RGBA", "L", "LA"):
                img = img.convert("RGBA" if "transparency" in img.info or img.mode in ("P", "PA") else "RGB")
            else:
                img = img.copy()
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None


def plain_lines(text: str) -> str:
    """A translation as plain text for alt text and captions: markdown markers dropped, one line per line."""
    from ..text import plain

    return "\n".join(line.strip() for line in plain(text or "").replace("\\", "").splitlines() if line.strip())


def word_pictures(p, in_fallback) -> list[tuple[object, object]]:
    """The pictures a Word paragraph holds itself (not those of a text box inside it, which has paragraphs of its
    own): [(the drawing's wp:inline / wp:anchor, pic:pic)] in order."""
    out = []
    for pic in p.iter(q(PIC, "pic")):
        if in_fallback(pic):
            continue
        holder, container = pic.getparent(), None
        while holder is not None and holder is not p:
            if holder.tag in (q(WP, "inline"), q(WP, "anchor")) and container is None:
                container = holder
            if local(holder) == "p":
                break
            holder = holder.getparent()
        if holder is p and container is not None:
            out.append((container, pic))
    return out


def word_size(container, pic) -> tuple[int, int] | None:
    single = len(list(container.iter(q(PIC, "pic")))) == 1
    ext = container.find(q(WP, "extent")) if single else pic.find(f"{q(PIC, 'spPr')}/{q(A, 'xfrm')}/{q(A, 'ext')}")
    try:
        return (int(ext.get("cx")), int(ext.get("cy"))) if ext is not None else None
    except (TypeError, ValueError):
        return None



def word_alt_targets(container, pic) -> list:
    """Where a Word picture's alt text lives: its own cNvPr and, when the drawing is just this picture, the
    drawing's docPr (what Word shows)."""
    out = [pic.find(f"{q(PIC, 'nvPicPr')}/{q(PIC, 'cNvPr')}")]
    if len(list(container.iter(q(PIC, "pic")))) == 1:
        out.append(container.find(q(WP, "docPr")))
    return [el for el in out if el is not None]


def word_descr(container, pic) -> str | None:
    """A Word picture's alt text as Word shows it: the drawing's docPr, else the picture's own cNvPr."""
    targets = word_alt_targets(container, pic)
    return next((el.get("descr") for el in reversed(targets) if el.get("descr")), None)


def blip_rid(pic) -> tuple[str | None, bool]:
    """(the relationship id of a picture's image, whether it is linked rather than embedded)."""
    blip = pic.find(f".//{q(A, 'blip')}")
    if blip is None:
        return None, False
    if blip.get(q(R, "embed")):
        return blip.get(q(R, "embed")), False
    return blip.get(q(R, "link")), True


def one_line(text: str) -> str:
    return "; ".join(plain_lines(text).splitlines())


def by_place(segments: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    """(picture loc → its figure segment, picture loc → its alt-text segment) for every place a picture is used."""
    figures = {loc: s for s in segments if s.get("kind") == "figure" for loc in s.get("locs") or [s.get("loc")] if loc}
    alts = {loc.removesuffix("#alt"): s for s in segments if s.get("kind") == "alt"
            for loc in s.get("locs") or [s.get("loc")] if loc}
    return figures, alts


def new_alt_text(current: str | None, figure: dict | None, alt: dict | None, report) -> str | None:
    """The alt text a picture gets: its own alt text translated (or kept, if not translated), then the English of
    the text in the picture: "<alt text> — Text in the picture: <English>". None: leave it as it is."""
    own, translated = "", False
    if alt is not None:
        if (current or "").strip() != alt["source"]:  # the file's alt text is no longer the one translated
            if alt["id"] not in report.mismatch:
                report.mismatch.append(alt["id"])
            own = (current or "").strip()
        elif alt.get("translatable", True) and (english := one_line(alt.get("target") or "")):
            own, translated = english, True
        else:
            own = alt["source"]
    elif alt_source(current):  # an alt text that isn't a segment (decorative pictures have none): kept
        own = (current or "").strip()
    picture = one_line(figure.get("target") or "") if figure is not None and figure.get("translatable", True) else ""
    if translated:
        report.pictures["alt_translated"] += 1
    if picture:
        return f"{own} — {PICTURE_TEXT}{picture}" if own else f"{PICTURE_TEXT}{picture}"
    return own if translated else None
