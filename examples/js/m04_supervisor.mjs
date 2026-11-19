// Supervisor pattern: specialist agents exposed as tools to a supervisor agent.
import { pathToFileURL } from "node:url";
import { runAgent } from "./agent.mjs";

const TASK_SCHEMA = {
  type: "object",
  properties: { task: { type: "string", description: "What the specialist should do." } },
  required: ["task"],
};
const NUM = {
  type: "object",
  properties: { a: { type: "number" }, b: { type: "number" } },
  required: ["a", "b"],
};
const mathTools = [
  { name: "add", description: "Add two numbers.", parameters: NUM, run: ({ a, b }) => a + b },
  { name: "multiply", description: "Multiply two numbers.", parameters: NUM, run: ({ a, b }) => a * b },
];

// A worker is an agent loop wrapped as a tool: the supervisor calls it like any other tool.
const makeWorkerTool = (name, description, system, tools) => ({
  name, description, parameters: TASK_SCHEMA,
  run: ({ task }) => runAgent(task, tools, { system, maxSteps: 5 }),
});

const calculator = makeWorkerTool(
  "calculator", "Specialist for arithmetic. Give it a calculation to perform.",
  "You are a calculator. Always use the tools for arithmetic and reply with the number only.", mathTools);
const writer = makeWorkerTool(
  "writer", "Specialist for writing short, friendly text from facts you provide.",
  "You write short, friendly text. Use only the facts you are given.", []);

const SUPERVISOR =
  "You are a supervisor. Delegate work to your specialists and never calculate or write " +
  "the final text yourself. First get numbers from the calculator, then ask the writer " +
  "to phrase the result. Return the writer's text as the final answer.";

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  console.log(await runAgent(
    "A team has 4 people and each gets 3 coffees. Announce the total coffees.",
    [calculator, writer], { system: SUPERVISOR, maxSteps: 8 }));
}
