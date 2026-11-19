"""Runnable versions of the Module 3 workflow patterns (no framework)."""
import json
from concurrent.futures import ThreadPoolExecutor

from llm_client import chat


def ask(prompt: str, system: str = "You are a concise assistant.", **kw) -> str:
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    return (chat(msgs, temperature=kw.pop("temperature", 0.2), **kw).content or "").strip()


def ask_json(prompt: str, retries: int = 3) -> dict:
    msgs = [{"role": "system", "content": "Reply with valid JSON only."},
            {"role": "user", "content": prompt}]
    for _ in range(retries):
        raw = (chat(msgs, temperature=0).content or "").strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            msgs += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": f"Invalid JSON ({exc}). Reply with valid JSON only."}]
    raise RuntimeError("No valid JSON")


def chain(topic: str) -> str:
    outline = ask(f"Write a 3-bullet outline for a short article about {topic}.")
    if len([ln for ln in outline.splitlines() if ln.strip()]) < 3:  # gate: expect 3 non-empty lines
        raise ValueError("Outline too short")
    return ask(f"Write a 100-word article from this outline:\n{outline}")


def route(text: str) -> str:
    handlers = {
        "billing": "You are a billing support agent.",
        "technical": "You are a technical support agent.",
        "other": "You are a general support agent.",
    }
    label = ask(f"Classify as billing, technical or other. One word only.\n{text}", temperature=0).lower()
    label = next((k for k in handlers if k in label), "other")  # safe default
    return ask(text, system=handlers[label])


def vote(question: str, n: int = 3) -> str:
    with ThreadPoolExecutor(max_workers=n) as pool:
        answers = list(pool.map(lambda _: ask(question + " Answer in one word.", temperature=0.8), range(n)))
    normalized = [a.lower().strip(" .!\n") for a in answers]  # "Canberra." == "canberra"
    return max(set(normalized), key=normalized.count)


def orchestrate(goal: str) -> str:
    subtasks = ask_json(f'List 2-4 subtasks for: {goal}. Format: {{"subtasks": ["..."]}}')["subtasks"]
    results = [ask(f"Complete this subtask briefly: {t}") for t in subtasks]
    return ask("Combine into one answer:\n" + "\n".join(results))


def evaluate_optimize(task: str, max_rounds: int = 3) -> str:
    draft = ask(task)
    for _ in range(max_rounds):
        verdict = ask_json(
            f'Task: {task}\nDraft: {draft}\nIs the draft correct and complete? '
            'Format: {"ok": true|false, "feedback": "..."}'
        )
        if verdict.get("ok"):
            break
        draft = ask(f"{task}\nImprove using this feedback: {verdict.get('feedback')}\nPrevious draft: {draft}")
    return draft


def reflect(task: str) -> str:
    """Reflection: the SAME agent answers, critiques its own answer once, then revises.
    Compared with evaluate_optimize: no separate judge, no ok/not-ok verdict, no loop."""
    answer = ask(task)
    critique = ask(f"Task: {task}\nAnswer: {answer}\nWhat is wrong or missing in this answer? Be specific and brief.")
    return ask(f"{task}\nPrevious answer: {answer}\nFix these issues:\n{critique}")


if __name__ == "__main__":
    print(chain("local LLMs"))
    print(route("My invoice shows the wrong amount."))
    print(vote("What is the capital of Australia?"))
    print(orchestrate("Plan a one-day team workshop on LLM agents"))
    print(evaluate_optimize("Write one sentence explaining what an LLM agent is."))
    print(reflect("Explain in two sentences why the sky is blue."))
