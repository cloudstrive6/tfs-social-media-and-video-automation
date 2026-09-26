"""The one place agents talk to Claude. Two interchangeable backends (config/channel.yaml -> llm.backend):

- `claude_code` (default): runs the Claude Code CLI headlessly (`claude -p`), authenticated with the Claude
  Max subscription through CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`). Structured outputs via
  --json-schema, research via Claude Code's WebSearch/WebFetch tools.
- `api`: the Anthropic Python SDK with a Console API key (ANTHROPIC_API_KEY) — prompt caching, adaptive
  thinking, server-side web search and refusal fallbacks.

If the subscription hits its usage limit and ANTHROPIC_API_KEY is set, the call falls back to `api`.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from .config import channel, env, load_prompt, style_bible

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# On a policy decline (e.g. a false positive on a corruption story) the API re-runs the
# request on Anthropic's recommended fallback model inside the same call.
FALLBACK = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=4)
    return _client


def _agent_cfg(agent: str) -> tuple[str, str]:
    llm = channel()["llm"]
    cfg = llm["agents"].get(agent, {})
    return cfg.get("model", llm["default_model"]), cfg.get("effort", "high")


def _system(agent: str) -> list[dict]:
    text = style_bible() + "\n\n---\n\n" + load_prompt(agent)
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _check(msg, agent: str) -> None:
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"{agent}: request declined ({getattr(msg.stop_details, 'category', None)})")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError(f"{agent}: output hit max_tokens")
    u = msg.usage
    log.info("%s: in=%s cached=%s out=%s", agent, u.input_tokens, u.cache_read_input_tokens, u.output_tokens)


class UsageLimitError(RuntimeError):
    """The Claude subscription's usage window is exhausted; retry later."""


def _backend() -> str:
    return channel()["llm"].get("backend", "claude_code")


def structured(agent: str, user: str, schema: type[T]) -> T:
    """One call that returns a validated `schema` instance."""
    if _backend() == "claude_code":
        try:
            return _cc_structured(agent, user, schema)
        except UsageLimitError:
            if not env("ANTHROPIC_API_KEY"):
                raise
            log.warning("%s: subscription limit reached, falling back to the API key", agent)
    return _api_structured(agent, user, schema)


def structured_with_images(agent: str, user: str, images: list, schema: type[T]) -> T:
    """Like `structured`, but the model also looks at the given image files (frames, slides, model sheets)."""
    if _backend() == "claude_code":
        try:
            return _cc_vision(agent, user, images, schema)
        except UsageLimitError:
            if not env("ANTHROPIC_API_KEY"):
                raise
            log.warning("%s: subscription limit reached, falling back to the API key", agent)
    return _api_vision(agent, user, images, schema)


def research(agent: str, user: str, max_searches: int = 20) -> str:
    """Free-text answer grounded in live web search (used by the Researcher)."""
    if _backend() == "claude_code":
        try:
            return _cc_research(agent, user, max_searches)
        except UsageLimitError:
            if not env("ANTHROPIC_API_KEY"):
                raise
            log.warning("%s: subscription limit reached, falling back to the API key", agent)
    return _api_research(agent, user, max_searches)


# ------------------------------------------------------------------ backend: Claude Code CLI (Max plan)
def _claude(agent: str, user: str, extra: list[str], timeout_s: int = 3600) -> dict:
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("Claude Code CLI not found on PATH (the run workflow installs it: needs_claude)")
    model, effort = _agent_cfg(agent)
    system = style_bible() + "\n\n---\n\n" + load_prompt(agent)
    with tempfile.TemporaryDirectory(prefix="tfs-claude-") as work:   # clean cwd: no stray CLAUDE.md/settings
        prompt_file = os.path.join(work, "system.md")
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(system)
        cmd = [exe, "-p", "--output-format", "json", "--model", model, "--effort", effort,
               "--system-prompt-file", prompt_file, "--permission-mode", "dontAsk",
               *extra]
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True, encoding="utf-8",
                              cwd=work, timeout=timeout_s)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"{agent}: claude exited {proc.returncode}: {(proc.stderr or proc.stdout)[-1500:]}")
    if out.get("is_error"):
        message = str(out.get("result", ""))
        if "limit" in message.lower():
            raise UsageLimitError(f"{agent}: {message[:300]}")
        raise RuntimeError(f"{agent}: {message[:1500]}")
    log.info("%s (claude code): turns=%s est_cost=$%s", agent, out.get("num_turns"), out.get("total_cost_usd"))
    return out


def _cc_structured(agent: str, user: str, schema: type[T]) -> T:
    out = _claude(agent, user, ["--tools", "", "--json-schema", json.dumps(schema.model_json_schema())])
    data = out.get("structured_output")
    if data is None:
        raise RuntimeError(f"{agent}: no structured_output in Claude Code result")
    return schema.model_validate(data)


def _cc_vision(agent: str, user: str, images: list, schema: type[T]) -> T:
    listing = "\n".join(f"- {Path(p).resolve()}" for p in images)
    dirs = sorted({str(Path(p).resolve().parent) for p in images})
    out = _claude(agent, user + "\n\nOpen and look at EVERY one of these images with the Read tool before "
                  "answering:\n" + listing,
                  ["--tools", "Read", "--allowedTools", "Read", "--json-schema",
                   json.dumps(schema.model_json_schema()), "--add-dir", *dirs])
    data = out.get("structured_output")
    if data is None:
        raise RuntimeError(f"{agent}: no structured_output in Claude Code result")
    return schema.model_validate(data)


def _cc_research(agent: str, user: str, max_searches: int) -> str:
    out = _claude(agent, user + f"\n\n(Use up to {max_searches} web searches; fetch primary sources when useful.)",
                  ["--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch,WebFetch"])
    return str(out.get("result", ""))


# ------------------------------------------------------------------ backend: Anthropic API (Console key)
def _api_structured(agent: str, user: str, schema: type[T], max_tokens: int = 64000) -> T:
    model, effort = _agent_cfg(agent)
    with client().beta.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=_system(agent),
        messages=[{"role": "user", "content": user}],
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        output_format=schema,
        **FALLBACK,
    ) as stream:
        msg = stream.get_final_message()
    _check(msg, agent)
    return msg.parsed_output


def _api_vision(agent: str, user: str, images: list, schema: type[T], max_tokens: int = 32000) -> T:
    import base64
    import mimetypes

    content: list[dict] = []
    for p in images:
        media = mimetypes.guess_type(str(p))[0] or "image/png"
        content += [{"type": "text", "text": f"Image: {Path(p).name}"},
                    {"type": "image", "source": {"type": "base64", "media_type": media,
                                                 "data": base64.b64encode(Path(p).read_bytes()).decode()}}]
    content.append({"type": "text", "text": user})
    model, effort = _agent_cfg(agent)
    with client().beta.messages.stream(
        model=model, max_tokens=max_tokens, system=_system(agent), messages=[{"role": "user", "content": content}],
        thinking={"type": "adaptive"}, output_config={"effort": effort}, output_format=schema, **FALLBACK,
    ) as stream:
        msg = stream.get_final_message()
    _check(msg, agent)
    return msg.parsed_output


def _api_research(agent: str, user: str, max_searches: int = 20, max_tokens: int = 64000) -> str:
    model, effort = _agent_cfg(agent)
    tools = [{
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": max_searches,
        "user_location": {"type": "approximate", "country": "PH", "timezone": "Asia/Manila"},
    }]
    messages: list[dict] = [{"role": "user", "content": user}]
    for _ in range(6):  # resume long server-tool turns that come back as pause_turn
        with client().beta.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=_system(agent),
            messages=messages,
            tools=tools,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            **FALLBACK,
        ) as stream:
            msg = stream.get_final_message()
        if msg.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": msg.content})
    _check(msg, agent)
    return "".join(b.text for b in msg.content if b.type == "text")
