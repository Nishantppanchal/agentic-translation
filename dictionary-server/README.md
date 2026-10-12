# Dictionary service

The translator looks up key terms in a dictionary service: any HTTP endpoint that answers the contract below.
This folder is a **dummy** implementation (standard library only, a small word list of the terms in the samples) to
develop and demo against. To use a real dictionary, point `DICTIONARY_URL` at your own service — for example a
small adapter in front of IATE, Wiktionary extracts (kaikki.org), CC-CEDICT, or a commercial API.

```bash
python3 dictionary-server/server.py                    # http://localhost:8200/lookup
python3 dictionary-server/server.py --port 8300 --key secret
```

`backend/.env`:

```bash
DICTIONARY_URL=http://localhost:8200/lookup
# DICTIONARY_API_KEY=secret                  # sent as "Authorization: Bearer secret"
# DICTIONARY_HEADERS={"X-Client": "translator"}
# DICTIONARY_TIMEOUT=15                      # seconds
```

## Contract

**Request:** `POST <DICTIONARY_URL>`, JSON:

```json
{"terms": ["réceptionnée avec réserves", "ASI"], "source_lang": "fr", "target_lang": "en"}
```

- `terms`: the terms as they appear in the document (inflected forms included — match them as best you can).
- `source_lang`: BCP-47 code of the document's language (`fr`, `de`, `zh-Hans`, …), or `""` if unknown.
- `target_lang`: always `en`.

**Response:** `200`, JSON:

```json
{"results": {
  "réceptionnée avec réserves": [
    {"term": "réception avec réserves", "translation": "acceptance with reservations",
     "definition": "Acceptance of the works subject to listed defects that the contractor must remedy.",
     "domain": "construction law", "source": "IATE", "url": "https://iate.europa.eu/entry/result/…"}
  ],
  "ASI": [{"translation": "UPS (uninterruptible power supply)", "source": "…"}]
}}
```

- One list of entries per requested term; a term with no entry has `[]` or is left out.
- Every field is optional except that an entry needs a `translation` or a `definition`. `term` is the dictionary's
  headword (e.g. the base form of an inflected term). At most 5 entries per term are used.
- Errors: any non-200 status. The translator logs it (`dictionary at <url> failed: HTTP 401: …`) and carries on
  without the dictionary — a lookup never blocks a translation.

## Where the translator uses it

- **Analysis:** all key terms of a document are looked up in one call. Each question card shows the entries
  (translation, domain, definition, source with its link), and a dictionary translation the analysis didn't offer
  is added as an option, credited to its source.
- **Chat editor:** a `look_up_term` tool (only offered when a dictionary is set up).
- **API:** `GET /api/dictionary?term=…&lang=…` for the UI and scripts; `/api/config` says whether one is set up.

Results are cached per term and language for the life of the backend process.
