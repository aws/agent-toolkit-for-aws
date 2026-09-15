import { cp, mkdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const packageRoot = fileURLToPath(new URL("../", import.meta.url));
const skillRoot = path.resolve(packageRoot, "../..");
const outputRoot = path.join(packageRoot, "skills", "agents-pay");
const includedEntries = [
  "SKILL.md",
  "requirements.txt",
  "references",
  "scripts",
];

function includeSource(source) {
  const relativePath = path.relative(skillRoot, source);
  const parts = relativePath.split(path.sep);
  return !parts.includes("__pycache__") && !relativePath.endsWith(".pyc");
}

await rm(outputRoot, { recursive: true, force: true });
await mkdir(outputRoot, { recursive: true });

for (const entry of includedEntries) {
  await cp(path.join(skillRoot, entry), path.join(outputRoot, entry), {
    filter: includeSource,
    recursive: true,
  });
}
