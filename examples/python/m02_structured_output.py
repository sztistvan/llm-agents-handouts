import json

from llm_client import chat

SYSTEM = (
    "Extract the task as JSON with keys: title (string), priority (low|medium|high). "
    "Reply with JSON only."
)


def extract_task(text: str, retries: int = 3) -> dict:
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]
    for _ in range(retries):
        raw = chat(messages, temperature=0).content or ""
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            data = json.loads(raw)
            if data.get("priority") not in {"low", "medium", "high"} or not data.get("title"):
                raise ValueError("missing title or invalid priority")
            return data
        except (json.JSONDecodeError, ValueError, AttributeError) as exc:
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"Invalid: {exc}. Reply with valid JSON only."},
            ]
    raise RuntimeError("Could not get valid structured output")


if __name__ == "__main__":
    print(extract_task("Please fix the login bug today, it blocks everyone."))
