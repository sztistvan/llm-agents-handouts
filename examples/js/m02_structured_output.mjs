import { pathToFileURL } from "node:url";
import { chat } from "./llm_client.mjs";

const SYSTEM =
  "Extract the task as JSON with keys: title (string), priority (low|medium|high). " +
  "Reply with JSON only.";

// Parse, validate, retry with the error message (see Module 2, "Structured output").
export async function extractTask(text, retries = 3) {
  const messages = [{ role: "system", content: SYSTEM }, { role: "user", content: text }];
  for (let i = 0; i < retries; i++) {
    let raw = ((await chat(messages, { temperature: 0 })).content ?? "").trim();
    raw = raw.replace(/^```(?:json)?\s*/, "").replace(/```$/, "").trim(); // models like to add code fences
    try {
      const data = JSON.parse(raw);
      if (!["low", "medium", "high"].includes(data?.priority) || !data?.title) {
        throw new Error("missing title or invalid priority");
      }
      return data;
    } catch (err) {
      messages.push(
        { role: "assistant", content: raw },
        { role: "user", content: `Invalid: ${err.message}. Reply with valid JSON only.` },
      );
    }
  }
  throw new Error("Could not get valid structured output");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  console.log(await extractTask("Please fix the login bug today, it blocks everyone."));
}
