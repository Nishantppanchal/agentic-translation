"""Seed the demo through the API: two projects (German → English and Chinese → English), each with a
style guide, a termbase and a translation memory, and with --upload the first demo documents.
See "Demo" in the README and docs/TESTING.md for what to try.

    cd backend
    uv run python scripts/seed_demo.py                       # backend on http://localhost:8000
    uv run python scripts/seed_demo.py --reset --upload      # start over and upload the demo documents
    uv run python scripts/seed_demo.py --only zh             # just the Chinese project
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"
DEMO = SAMPLES / "demo"


@dataclass
class Project:
    key: str
    name: str
    source_lang: str
    style_guide: str
    imports: list[Path]
    uploads: list[Path]
    notes: list[tuple[Path, str]]


PROJECTS = [
    Project(
        key="de",
        name="Acme Energie – Umspannwerk Nord",
        source_lang="German",
        style_guide="""\
Register: formal and technical; the readers are utility engineers and site managers.
Keep document and item codes unchanged (UW-2291, BA-17, LV position 4.2.7, DIN VDE 0100-540).
Always follow the termbase; never use its forbidden variants.
British spelling (earthing, organisation, metre). Dates as 31 May 2026. Decimal point (0.08 Ω).
""",
        imports=[DEMO / "termbase.csv", DEMO / "memory.tmx"],
        uploads=[SAMPLES / "nachbegehung.pdf", SAMPLES / "pruefbericht.docx"],
        notes=[
            (SAMPLES / "nachbegehung.pdf", "repeats abnahmeprotokoll.pdf → translation-memory matches"),
            (SAMPLES / "pruefbericht.docx", "Word round trip; then import the vendor file below"),
            (DEMO / "pruefbericht.vendor.en.xlf", 'a "vendor" translation with planted errors'),
            (SAMPLES / "vertragsauszug.pdf", "AG/AN defined only on page 2, legal terms → questions up front"),
            (SAMPLES / "abnahmeprotokoll-scanned.pdf", "a scan → layout-preserving PDF (needs the layout server)"),
        ],
    ),
    Project(
        key="zh",
        name="北区变电站改造 – UW-2291",
        source_lang="Chinese (Simplified)",
        style_guide="""\
Register: formal and technical; the readers are utility engineers and site managers.
Keep document and item codes unchanged (UW-2291, BA-17, 4.2.7).
Always follow the termbase; never use its forbidden variants. Contract parties are "the Client" and
"the Contractor" — never "Party A" / "Party B".
British spelling (earthing, organisation, metre). Dates as 20 May 2026. Amounts as CNY 12,500.00.
""",
        imports=[DEMO / "zh" / "termbase.csv", DEMO / "zh" / "memory.tmx"],
        uploads=[SAMPLES / "fucha-baogao.pdf", SAMPLES / "jiance-baogao.docx"],
        notes=[
            (SAMPLES / "fucha-baogao.pdf", "repeats yanshou-baogao.pdf → TM matches; 三措一案 defined on page 2"),
            (SAMPLES / "jiance-baogao.docx", "Word round trip with tracked changes; then import the vendor file below"),
            (DEMO / "zh" / "jiance-baogao.vendor.en.xlf", 'a "vendor" translation with planted errors'),
            (SAMPLES / "anquan-peixun.pptx", "五防 / 两票三制 used on slide 1, explained later → questions"),
            (SAMPLES / "quexian-qingdan.xlsx", "status texts used inside COUNTIF formulas"),
            (SAMPLES / "fucha-baogao-scanned.pdf", "a Chinese scan → layout-preserving PDF (needs the layout server)"),
        ],
    ),
]


def seed(api: httpx.Client, p: Project, reset: bool, upload: bool) -> None:
    existing = [x for x in api.get("/api/projects").json() if x["name"] == p.name]
    if existing and reset:
        for x in existing:
            api.delete(f"/api/projects/{x['id']}").raise_for_status()
        existing = []
    if existing:
        project = existing[0]
        print(f"Using the existing project “{p.name}” (pass --reset to start over).")
    else:
        project = api.post("/api/projects", json={"name": p.name, "source_lang": p.source_lang, "instructions": p.style_guide}).json()
        print(f"Created the project “{p.name}”: {p.source_lang} → English.")

    pid = project["id"]
    for path in p.imports:
        if not path.exists():
            print(f"  ! {path.relative_to(ROOT)} is missing (run scripts/make_samples.py)")
            continue
        with path.open("rb") as f:
            r = api.post(f"/api/projects/{pid}/import", files={"file": (path.name, f)})
        r.raise_for_status()
        rep = r.json()
        what = "terms" if rep["kind"] == "terms" else "translation-memory units"
        print(f"  {path.name}: {rep['added']} {what} added, {rep['updated']} updated" + "".join(f"\n    ! {w}" for w in rep["warnings"]))

    if upload:
        for path in p.uploads:
            if not path.exists():
                print(f"  ! {path.relative_to(ROOT)} is missing (run scripts/make_samples.py)")
                continue
            with path.open("rb") as f:
                r = api.post("/api/sessions", data={"project_id": pid}, files={"file": (path.name, f)})
            r.raise_for_status()
            print(f"  uploaded {path.name} → document {r.json()['id']} (translating now)")

    width = max(len(str(path.relative_to(ROOT))) for path, _ in p.notes)
    print("  Files to try:")
    for path, note in p.notes:
        print(f"    {str(path.relative_to(ROOT)).ljust(width)}  {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000", help="backend URL")
    parser.add_argument("--reset", action="store_true", help="delete the existing demo projects first")
    parser.add_argument("--upload", action="store_true", help="also upload the demo documents into the projects")
    parser.add_argument("--only", choices=[p.key for p in PROJECTS], help="seed just one project")
    args = parser.parse_args()

    api = httpx.Client(base_url=args.api, timeout=120)
    try:
        api.get("/api/config").raise_for_status()
    except httpx.HTTPError as exc:
        print(f"Can't reach the backend at {args.api} ({exc}). Start it first: uv run uvicorn translator.api:app --port 8000")
        return 1

    for p in PROJECTS:
        if not args.only or args.only == p.key:
            seed(api, p, args.reset, args.upload)
            print()
    print("Ready. Open http://localhost:3000 and pick a project in the sidebar. The test script is docs/TESTING.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
