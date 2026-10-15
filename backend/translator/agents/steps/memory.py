"""The translation memory before anything is translated: 100/101% matches fill their segments (no model call),
fuzzy matches are kept as references for the translator. It runs before the analysis, so terms in segments the TM
already filled aren't asked about. See document/memory.py."""

from __future__ import annotations

import asyncio
from typing import Any

from google.adk import Context, Event
from google.adk.workflow import node

from ... import references
from ...document import memory as tm
from ...document import state as st


@node(rerun_on_resume=True)
async def memory(ctx: Context, node_input: Any):
    segments = st.get_segments(ctx.state)
    delta, refs, stats = await asyncio.to_thread(tm.prefill, ctx.state, segments)
    reused = stats["context"] + stats["exact"]
    if delta or refs:
        source = {x["id"]: x["source"] for x in segments}
        results = [{"query": source[seg["id"]][:160], "entries": [{"target": seg["target"][:300], "score": seg["match"]}],
                    "outcome": "reused, confirmed" if seg["status"] == "confirmed" else "reused as a draft"}
                   for seg in delta.values()]
        results += [{"query": source[sid][:160], "entries": [references.tm_entry(m)], "outcome": "to adapt"}
                    for sid, m in refs.items()]
        n = sum(1 for x in segments if x.get("translatable", True))
        yield references.lookup_event(
            references.lookup_payload("tm", "The translation memory, before translating", results, queries=n),
            f"Translation memory: {reused} segment{'s' if reused != 1 else ''} reused ({stats['words']} words, no model "
            f"call), {stats['fuzzy']} fuzzy match{'es' if stats['fuzzy'] != 1 else ''} to adapt",
            state={**delta, "doc:tm_stats": stats, "doc:tm_refs": refs},
        )
    yield Event(output={"reused": reused, "fuzzy": stats["fuzzy"]})
