"""Thin LLM client for any OpenAI-compatible backend (LM Studio or Azure OpenAI).

Configuration via environment variables:
  LLM_PROVIDER  lmstudio (default) | azure
  LLM_BASE_URL  default: http://localhost:1234/v1 (lmstudio); required for azure,
                e.g. https://<resource>.openai.azure.com/openai/v1
  LLM_API_KEY   default: "lm-studio" for lmstudio; required for azure
  LLM_MODEL     model name (lmstudio) or deployment name (azure)
"""
import os

from openai import OpenAI


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Environment variable {name} is required for this provider")
    return value


def get_config() -> dict:
    provider = os.environ.get("LLM_PROVIDER", "lmstudio").lower()
    if provider == "lmstudio":
        return {
            "base_url": os.environ.get("LLM_BASE_URL", "http://localhost:1234/v1"),
            "api_key": os.environ.get("LLM_API_KEY", "lm-studio"),
            "model": os.environ.get("LLM_MODEL", "local-model"),
        }
    if provider == "azure":
        return {
            "base_url": _require("LLM_BASE_URL"),
            "api_key": _require("LLM_API_KEY"),
            "model": _require("LLM_MODEL"),
        }
    raise ValueError(f"Unknown LLM_PROVIDER: {provider}")


def get_client() -> tuple[OpenAI, str]:
    cfg = get_config()
    return OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"]), cfg["model"]


def chat(messages: list[dict], **kwargs):
    """Send a chat completion request and return the first choice's message."""
    client, model = get_client()
    response = client.chat.completions.create(model=model, messages=messages, **kwargs)
    return response.choices[0].message


if __name__ == "__main__":
    reply = chat([{"role": "user", "content": "Say hello in five words."}])
    print(reply.content)
