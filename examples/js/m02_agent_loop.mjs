// Module 2 lesson: the reusable agent loop (runAgent lives in agent.mjs) with two demo tools.
import { pathToFileURL } from "node:url";
import { runAgent } from "./agent.mjs";

const tools = [
  { name: "add", description: "Add two numbers.", run: ({ a, b }) => a + b,
    parameters: { type: "object", properties: { a: { type: "number" }, b: { type: "number" } }, required: ["a", "b"] } },
  { name: "word_count", description: "Count words in a text.", run: ({ text }) => text.split(/\s+/).filter(Boolean).length,
    parameters: { type: "object", properties: { text: { type: "string" } }, required: ["text"] } },
];

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  console.log(await runAgent("How many words are in 'the quick brown fox'? Then add 10 to that count.", tools));
}
