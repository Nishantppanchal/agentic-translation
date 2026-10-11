"""The "vendor" XLIFF for the demo: an English translation of samples/pruefbericht.docx with planted errors.

    cd backend && uv run python scripts/make_vendor_xliff.py ../samples/pruefbericht.docx ../samples/demo/pruefbericht.vendor.en.xlf
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run from anywhere

from translator.filters import office, xliff  # noqa: E402

VENDOR = {
    'Seite <x id="1"/>1<x id="2"/>': 'Page <x id="1"/>1<x id="2"/>',
    # planted: the site name the termbase says to translate ("Substation North")
    "Umspannwerk Nord · Projekt UW-2291 · Vertraulich": "Substation Nord · Project UW-2291 · Confidential",
    "Prüfbericht Erdungsanlage": "Earthing System Test Report",
    # planted: forbidden term "cable bridge"
    'Am 12.05.2026 wurde die <g id="1">Erdungsanlage</g> im Kellergeschoss geprüft. Der Übergangswiderstand der <g id="2">Kabelpritsche</g> liegt mit 0,08 Ω <g id="3">unter</g> dem Grenzwert von 0,1 Ω.':
        'On 12.05.2026 the <g id="1">earthing system</g> in the basement was tested. The contact resistance of the '
        '<g id="2">cable bridge</g> is 0.08 Ω, <g id="3">below</g> the limit of 0.1 Ω.',
    "Messergebnisse": "Measurement results",
    "Messpunkt": "Measuring point",
    "Wert": "Value",
    "Bewertung": "Assessment",
    "Kabelpritsche KG": "Cable tray, basement",
    "Schaltschrank 1": "Switchgear cabinet 1",
    "0,08 Ω": "0.08 Ω",
    "0,05 Ω": "0.05 Ω",
    "0,12 Ω": "0.12 Ω",
    "USV-Anlage": "UPS system",
    "Nachbesserung erforderlich": "Rework required",
    # planted: the footnote mark <x id="2"/> is missing (the import refuses this one)
    'Die Prüfung erfolgte nach den Vorgaben des <g id="1">Netzbetreibers</g> und der DIN VDE 0100-540.<x id="2"/>':
        'The test was carried out in accordance with the requirements of the <g id="1">network operator</g> and DIN VDE 0100-540.',
    # planted: left untranslated
    "Die Anlage ist uneingeschränkt betriebsbereit.": "Die Anlage ist uneingeschränkt betriebsbereit.",
    # planted: wrong date (31.05. in the source)
    "Die Nachbesserung an der USV-Anlage ist bis zum 31.05.2026 durchzuführen.": "The rework on the UPS system must be completed by 31.03.2026.",
    "Für den Prüfer: K. Albrecht": "For the inspector: K. Albrecht",
    '<x id="1"/> Errichten von Niederspannungsanlagen – Erdungsanlagen und Schutzleiter.':
        '<x id="1"/> Low-voltage electrical installations – Earthing arrangements and protective conductors.',
}

segments, _ = office.extract(open(sys.argv[1], "rb").read(), "docx")
seen_ok = 0
for s in segments:
    if s["source"] == "in Ordnung":
        seen_ok += 1
        s["target"] = "OK" if seen_ok == 1 else "satisfactory"  # planted: the same cell text translated two ways
    elif s["translatable"]:
        s["target"] = VENDOR[s["source"]]
    s["status"] = "draft"
open(sys.argv[2], "wb").write(xliff.export(segments, src="de", tgt="en", original="pruefbericht.docx"))
print(len(segments), "segments")
