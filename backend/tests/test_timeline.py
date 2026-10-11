from google.adk.events import Event
from google.genai import types

from translator.timeline import stream_events


def _chunk(text: str, **kw) -> Event:
    return Event(invocation_id="inv", author="editor", content=types.Content(role="model", parts=[types.Part(text=text)]), **kw)


def test_streamed_chunks_keep_whitespace_and_final_replaces_draft():
    partial: dict[str, str] = {}
    out = []
    for piece in ["I have", " added", " **it**."]:
        out += stream_events(_chunk(piece, partial=True), partial)
    assert out[-1]["item"]["text"] == "I have added **it**."
    assert out[-1]["item"]["partial"] is True

    final = stream_events(_chunk("I have added **it**."), partial)
    assert final[0]["item"]["kind"] == "assistant" and not final[0]["item"].get("partial")
    assert partial == {}


def test_partial_function_calls_are_not_emitted():
    fc = types.Part(function_call=types.FunctionCall(id="c1", name="update_segment", args={}))
    ev = Event(invocation_id="inv", author="editor", partial=True, content=types.Content(role="model", parts=[fc]))
    assert stream_events(ev, {}) == []
