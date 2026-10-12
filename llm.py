"""Small, dependency-free LLM helper.

If ANTHROPIC_API_KEY or OPENAI_API_KEY is set (in the environment or a .env
file), `complete()` sends the prompt to that provider. Otherwise it returns
None and the calling code falls back to its built-in rule-based logic, so every
project in this series runs offline out of the box.

Set LLM_OFFLINE=1 to force offline mode (used by the tests).
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path


def _load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def provider() -> str | None:
    """Return 'anthropic', 'openai' or None (offline)."""
    if os.getenv("LLM_OFFLINE") == "1":
        return None
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return None


def available() -> bool:
    return provider() is not None


def _post(url: str, headers: dict, body: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def complete(prompt: str, system: str = "You are a precise, helpful assistant.",
             max_tokens: int = 700, temperature: float = 0.2) -> str | None:
    """Send a prompt to the configured LLM. Returns text, or None when offline
    or when the call fails (callers should then use their fallback)."""
    p = provider()
    if p is None:
        return None
    try:
        if p == "anthropic":
            data = _post(
                "https://api.anthropic.com/v1/messages",
                {
                    "content-type": "application/json",
                    "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                    "anthropic-version": "2023-06-01",
                },
                {
                    "model": os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5"),
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            return "".join(b.get("text", "") for b in data.get("content", []))
        data = _post(
            "https://api.openai.com/v1/chat/completions",
            {
                "content-type": "application/json",
                "authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            },
            {
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        return data["choices"][0]["message"]["content"]
    except (urllib.error.URLError, KeyError, ValueError, TimeoutError) as exc:
        print(f"[llm] call failed ({exc}); using offline fallback")
        return None


def complete_json(prompt: str, **kwargs) -> dict | list | None:
    """Like complete(), but parses the first JSON object/array in the reply."""
    text = complete(prompt + "\n\nReply with valid JSON only.", **kwargs)
    if not text:
        return None
    match = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
