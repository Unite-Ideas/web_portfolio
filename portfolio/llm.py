"""Thin wrapper around the Claude API for the three jobs Claude does here:
web research, judging photos and writing the post text."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field

import anthropic

# Server-side refusal fallback: if a request is declined, the API retries it on
# the model Anthropic recommends instead of returning an empty answer.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_PAUSE_RESTARTS = 5


class ClaudeError(RuntimeError):
    pass


@dataclass
class ResearchResult:
    text: str
    sources: list[dict] = field(default_factory=list)  # {"url", "title"}


def image_block(jpeg_bytes: bytes) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.standard_b64encode(jpeg_bytes).decode("ascii"),
        },
    }


def _text_of(response) -> str:
    return "".join(b.text for b in response.content if b.type == "text")


def _check(response) -> None:
    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None) if response.stop_details else None
        raise ClaudeError(f"Claude declined this request (category: {category}).")
    if response.stop_reason == "max_tokens":
        raise ClaudeError("Claude's answer was cut off (max_tokens).")


class Claude:
    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key or None)
        self.model = model

    def json(
        self,
        content: list[dict] | str,
        schema: dict,
        system: str,
        effort: str = "low",
        max_tokens: int = 16000,
    ) -> dict:
        """One request whose answer must match a JSON schema."""
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": schema},
            },
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        _check(response)
        return json.loads(_text_of(response))

    def research(self, prompt: str, system: str, max_searches: int = 12, effort: str = "medium") -> ResearchResult:
        """Let Claude search and read the web, then return its notes and the pages it saw."""
        tools = [
            {"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches},
            {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": max_searches},
        ]
        messages: list[dict] = [{"role": "user", "content": prompt}]
        sources: dict[str, dict] = {}
        texts: list[str] = []

        for _ in range(MAX_PAUSE_RESTARTS + 1):
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=64000,
                system=system,
                messages=messages,
                tools=tools,
                output_config={"effort": effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                response = stream.get_final_message()

            for block in response.content:
                if block.type == "text":
                    texts.append(block.text)
                elif block.type == "web_search_tool_result" and isinstance(block.content, list):
                    for result in block.content:
                        url = getattr(result, "url", None)
                        if url:
                            sources.setdefault(url, {"url": url, "title": getattr(result, "title", "") or ""})

            if response.stop_reason != "pause_turn":
                _check(response)
                break
            # A long server-tool turn paused; send it back so Claude can continue.
            messages = messages + [{"role": "assistant", "content": response.content}]
        else:
            raise ClaudeError("Research did not finish after several continuations.")

        return ResearchResult(text="\n".join(texts).strip(), sources=list(sources.values()))
