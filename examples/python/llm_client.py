"""Thin LLM client for any OpenAI-compatible backend (LM Studio or Azure OpenAI).

Configuration via environment variables (or a .env file in the project root, see .env.example):
  LLM_PROVIDER      azure (default) | openrouter | lmstudio | any name you add a block for
  <PROVIDER>_BASE_URL, <PROVIDER>_API_KEY, <PROVIDER>_MODEL
                    the three settings of the chosen provider, e.g. LMSTUDIO_MODEL
  LLM_TIMEOUT       request timeout in seconds (default 300; local models can be slow)

Switch provider for one run without editing .env:
  PowerShell:  $env:LLM_PROVIDER = "lmstudio"; python m01_minimal_agent.py
               (then Remove-Item Env:LLM_PROVIDER to go back to the .env provider)
  bash/zsh:    LLM_PROVIDER=lmstudio python m01_minimal_agent.py

Use a non-reasoning, tool-capable model. Reasoning ("thinking") models may spend the
whole token budget thinking and return an empty answer; chat() raises a clear error then.
"""
import json
import os
from pathlib import Path

from openai import OpenAI


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from the project's .env without overriding real env vars."""
    path = Path(__file__).resolve().parents[2] / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def get_provider() -> str:
    return os.environ.get("LLM_PROVIDER", "azure").strip().lower()


def _setting(provider: str, name: str) -> str:
    """This provider's setting, e.g. name='MODEL' -> OPENROUTER_MODEL."""
    var = f"{provider.upper()}_{name}"
    value = os.environ.get(var)
    if not value:
        raise RuntimeError(f"Missing {var} (LLM_PROVIDER={provider}). Add it to .env, see .env.example.")
    return value


def get_config() -> dict:
    provider = get_provider()
    return {
        "provider": provider,
        "base_url": _setting(provider, "BASE_URL"),
        "api_key": _setting(provider, "API_KEY"),
        "model": _setting(provider, "MODEL"),
    }


def get_client() -> tuple[OpenAI, str]:
    cfg = get_config()
    timeout = float(os.environ.get("LLM_TIMEOUT", "300"))
    client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"], timeout=timeout)
    return client, cfg["model"]


def chat(messages: list[dict], **kwargs):
    """Send a chat completion request and return the first choice's message."""
    client, model = get_client()
    response = client.chat.completions.create(model=model, messages=messages, **kwargs)
    choice = response.choices[0]
    if choice.finish_reason == "length" and not choice.message.content and not choice.message.tool_calls:
        raise RuntimeError(
            "Empty reply: the token limit was hit before any answer. "
            "Reasoning models do this; load a non-reasoning model or raise max_tokens."
        )
    return choice.message


EMBED_BATCH = 64  # texts per embeddings request


def embed_model() -> str | None:
    """The embedding model of the current provider (<PROVIDER>_EMBED_MODEL), or None if not set."""
    return os.environ.get(f"{get_provider().upper()}_EMBED_MODEL") or None


def has_embeddings() -> bool:
    return embed_model() is not None


def embed(texts: list[str], kind: str = "document") -> list[list[float]]:
    """Turn texts into embedding vectors with the provider's embedding model.

    kind: 'document' (text to be searched) or 'query' (the search question). Some models need a
    different prefix for each (e.g. nomic-embed: 'search_document: ' / 'search_query: '); they are added
    automatically for nomic models and can be set for any model with <PROVIDER>_EMBED_DOC_PREFIX and
    <PROVIDER>_EMBED_QUERY_PREFIX. Always check the model card.
    """
    provider = get_provider()
    model = embed_model()
    if model is None:
        raise RuntimeError(
            f"Missing {provider.upper()}_EMBED_MODEL (LLM_PROVIDER={provider}). Add it to .env, see .env.example. "
            "Without an embedding model only keyword search (BM25) is available.")
    prefix = os.environ.get(f"{provider.upper()}_EMBED_{'QUERY' if kind == 'query' else 'DOC'}_PREFIX")
    if prefix is None:
        prefix = ("search_query: " if kind == "query" else "search_document: ") if "nomic" in model.lower() else ""
    client, _ = get_client()
    vectors: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = [prefix + t for t in texts[i:i + EMBED_BATCH]]
        response = client.embeddings.create(model=model, input=batch)
        vectors += [d.embedding for d in sorted(response.data, key=lambda d: d.index)]
    return vectors


def trace_mode(default: str = "off") -> str:
    """Read LLM_TRACE: 'compact' (also 1/true/on), 'raw' (full JSON) or 'off'. `default` applies when unset."""
    value = os.environ.get("LLM_TRACE", default).strip().lower()
    if value == "raw":
        return "raw"
    return "compact" if value in {"1", "true", "on", "yes", "compact"} else "off"


def _short(text, limit: int = 100) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def show(msg, step: int, mode: str) -> None:
    """Print one message of the agent loop, to see tool calls and the final answer.

    mode 'compact': one line per message; mode 'raw': the message as JSON; 'off': nothing.
    `msg` is a model reply (SDK object) or a tool-result dict.
    """
    if mode == "off":
        return
    data = msg.model_dump(exclude_none=True) if hasattr(msg, "model_dump") else dict(msg)
    data = {k: v for k, v in data.items() if v not in ([], {}, "")}  # drop empty noise (annotations, "")
    if mode == "raw":
        print(f"--- step {step}: {data.get('role')} message")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    role = data.get("role")
    if role == "assistant" and data.get("tool_calls"):
        for call in data["tool_calls"]:
            fn = call["function"]
            print(f"[step {step}] assistant -> TOOL CALL {fn['name']}({fn['arguments']})  id={call['id']}")
    elif role == "assistant":
        print(f"[step {step}] assistant -> FINAL ANSWER (no tool_calls): {_short(data.get('content', ''))}")
    elif role == "tool":
        print(f"[step {step}] tool      <- {_short(data.get('content', ''))}  (tool_call_id={data.get('tool_call_id')})")


if __name__ == "__main__":
    reply = chat([{"role": "user", "content": "Say hello in five words."}])
    print(reply.content)
