"""Exercise the Claude wrapper against a fake API (no network, no key needed)."""

import json

import anthropic
import httpx2
import pytest

from portfolio.llm import Claude, ClaudeError


def message(content, stop_reason="end_turn"):
    return {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": content, "stop_reason": stop_reason, "stop_sequence": None, "stop_details": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def sse(msg):
    """Render a full message as a server-sent event stream."""
    events = [("message_start", {"type": "message_start", "message": {**msg, "content": [], "stop_reason": None}})]
    for i, block in enumerate(msg["content"]):
        if block["type"] == "text":
            events.append(("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}}))
            events.append(("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": block["text"]}}))
        else:
            events.append(("content_block_start", {"type": "content_block_start", "index": i, "content_block": block}))
        events.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
    events.append(("message_delta", {"type": "message_delta", "delta": {"stop_reason": msg["stop_reason"], "stop_sequence": None}, "usage": {"output_tokens": 1}}))
    events.append(("message_stop", {"type": "message_stop"}))
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)


def fake_claude(responses, requests):
    def handler(request):
        body = json.loads(request.content)
        requests.append({"body": body, "headers": dict(request.headers)})
        msg = responses.pop(0)
        if body.get("stream"):
            return httpx2.Response(200, text=sse(msg), headers={"content-type": "text/event-stream"})
        return httpx2.Response(200, json=msg)

    claude = Claude("test-key", "claude-opus-5-5")
    claude.client = anthropic.Anthropic(
        api_key="test-key", http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)), max_retries=0
    )
    return claude


def test_json_request_shape():
    requests = []
    claude = fake_claude([message([{"type": "text", "text": '{"kind": "exterior"}'}])], requests)
    out = claude.json([{"type": "text", "text": "hi"}], {"type": "object"}, system="sys")
    assert out == {"kind": "exterior"}
    body = requests[0]["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["effort"] == "low"
    assert "server-side-fallback-2026-07-01" in requests[0]["headers"]["anthropic-beta"]
    assert "thinking" not in body and "temperature" not in body


def test_json_refusal_raises():
    requests = []
    refusal = message([], stop_reason="refusal")
    refusal["stop_details"] = {"type": "refusal", "category": "cyber", "explanation": None}
    claude = fake_claude([refusal], requests)
    with pytest.raises(ClaudeError, match="declined"):
        claude.json("x", {"type": "object"}, system="s")


def test_research_resumes_after_pause_and_collects_sources():
    requests = []
    search_result = {
        "type": "web_search_tool_result", "tool_use_id": "srvtoolu_1",
        "content": [{"type": "web_search_result", "url": "https://news.example.com/rnr", "title": "RNR opens",
                     "encrypted_content": "x", "page_age": None}],
    }
    first = message([
        {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "rnr mansfield"}},
        search_result,
        {"type": "text", "text": "Part one."},
    ], stop_reason="pause_turn")
    second = message([{"type": "text", "text": "Part two."}])
    claude = fake_claude([first, second], requests)
    result = claude.research("prompt", system="s")
    assert result.text == "Part one.\nPart two."
    assert result.sources == [{"url": "https://news.example.com/rnr", "title": "RNR opens"}]
    assert len(requests) == 2
    tools = {t["name"]: t["type"] for t in requests[0]["body"]["tools"]}
    assert tools == {"web_search": "web_search_20260209", "web_fetch": "web_fetch_20260209"}
    # The paused assistant turn is sent back so Claude can continue it.
    assert requests[1]["body"]["messages"][-1]["role"] == "assistant"
