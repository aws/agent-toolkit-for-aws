const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const { mkdtempSync, readFileSync, rmSync, writeFileSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { resolve } = require("node:path");
const test = require("node:test");
const { COMMENT_MARKER, checklistItems, evaluate, inspect, notify: runNotify } = require("./startup-advisor-pr-checklist.cjs");

const template = readFileSync(resolve(__dirname, "../PULL_REQUEST_TEMPLATE/startup-advisor.md"), "utf8");
const descriptions = {
  Problem: "Authors can submit Startup Advisor changes without explaining them.",
  Fix: "Require a short explanation before the author checklist passes.",
  Scope: "The Startup Advisor PR template and checklist bot.",
};
const descriptionSection = Object.entries(descriptions).map(([heading, content]) => `## ${heading}\n\n${content}\n\n`).join("");
const [typeSection, confirmationSection] = template.slice(template.indexOf("## Type of Change"))
  .split("## Startup Advisor review checklist");
const complete = descriptionSection + typeSection.replace("- [ ] Bug fix", "- [x] Bug fix") +
  "## Startup Advisor review checklist" + confirmationSection.replaceAll("- [ ]", "- [x]");
const pluginFile = { filename: "plugins/aws-startup-advisor/README.md" };
const repository = "example/toolkit";
const pullEndpoint = `repos/${repository}/pulls/42`;
const notify = (...args) => runNotify(...args, "a".repeat(40));

function pull(overrides = {}) {
  return {
    number: 42, head: { sha: "a".repeat(40) }, base: { sha: "b".repeat(40) },
    state: "open", draft: false, body: complete, changed_files: 1, ...overrides,
  };
}

function fixture({ pr = pull(), files = [pluginFile], comments = [], mutate } = {}) {
  const writes = [];
  let reads = 0;
  const api = async (method, endpoint, body) => {
    if (method !== "GET") {
      writes.push({ method, endpoint, body });
      if (endpoint.endsWith("/check-runs") && method === "POST") return { id: 11 };
      if (endpoint.endsWith("/comments") && method === "POST") {
        comments.push({ id: 12, body: body.body, user: { login: "github-actions[bot]", type: "Bot" } });
      } else if (endpoint.includes("/issues/comments/") && method === "PATCH") {
        comments.find((comment) => endpoint.endsWith(`/${comment.id}`)).body = body.body;
      }
      return {};
    }
    if (endpoint === pullEndpoint) {
      reads++;
      if (mutate) mutate(pr, reads);
      return structuredClone(pr);
    }
    const page = Number(new URL(`https://api.github.com/${endpoint}`).searchParams.get("page"));
    if (endpoint.startsWith(`${pullEndpoint}/files?`)) return files.slice((page - 1) * 100, page * 100);
    if (endpoint.includes("/comments?")) return comments.slice((page - 1) * 100, page * 100);
    throw new Error(`Unexpected API request: ${method} ${endpoint}`);
  };
  return { api, pr, files, comments, writes };
}

function runCli(t, { pr = pull(), files = [pluginFile], comments = [], failureEndpoint } = {}) {
  const directory = mkdtempSync(resolve(tmpdir(), "startup-advisor-cli-"));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const input = resolve(directory, "fixture.json");
  const log = resolve(directory, "requests.jsonl");
  writeFileSync(input, JSON.stringify({ pr, files, comments, failureEndpoint }));
  writeFileSync(log, "");
  writeFileSync(resolve(directory, "gh"), `#!${process.execPath}
const fs = require("node:fs");
const fixture = JSON.parse(fs.readFileSync(process.env.FAKE_GH_FIXTURE, "utf8"));
const args = process.argv.slice(2);
if (args[0] !== "api" || args[1] !== "--method") throw new Error("Unexpected gh invocation");
const method = args[2], endpoint = args[3];
const body = args.includes("--input") ? JSON.parse(fs.readFileSync(0, "utf8")) : undefined;
fs.appendFileSync(process.env.FAKE_GH_LOG, JSON.stringify({ method, endpoint, body }) + "\\n");
if (fixture.failureEndpoint && endpoint.includes(fixture.failureEndpoint)) {
  fs.writeFileSync(1, "[]");
  fs.writeFileSync(2, "Simulated API failure");
  process.exit(2);
}
let response;
if (method === "POST" && endpoint.endsWith("/check-runs")) response = { id: 11 };
else if (method !== "GET") response = {};
else if (endpoint.endsWith("/pulls/42")) response = fixture.pr;
else {
  const page = Number(new URL("https://example.invalid/" + endpoint).searchParams.get("page"));
  const rows = endpoint.includes("/files?") ? fixture.files : fixture.comments;
  response = rows.slice((page - 1) * 100, page * 100);
}
fs.writeFileSync(1, JSON.stringify(response));
`, { mode: 0o755 });
  const child = spawnSync(process.execPath, [
    resolve(__dirname, "startup-advisor-pr-checklist.cjs"), repository, "42", "a".repeat(40),
  ], {
    encoding: "utf8",
    timeout: 15000,
    env: { PATH: directory, FAKE_GH_FIXTURE: input, FAKE_GH_LOG: log },
  });
  assert.ifError(child.error);
  const calls = readFileSync(log, "utf8").trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
  return { ...child, calls };
}

test("requires text under Problem, Fix, and Scope even when every checkbox is complete", () => {
  assert.deepEqual(evaluate(pull(), [pluginFile], template).missingDescriptions, []);
  for (const [heading, content] of Object.entries(descriptions)) {
    for (const replacement of [
      "", " \t\n", "<!-- Write an explanation here. -->", "- <!-- Write an explanation here. -->",
      "```text\nAn example is not an explanation.\n```", "<pre>Example only.</pre>",
      "### A heading without body text", "---", "...", "&nbsp;", "TODO", "TBD",
      "## Another section\n\nThis text belongs to a different section.",
    ]) {
      const body = complete.replace(content, replacement);
      const result = evaluate(pull({ body }), [pluginFile], template);
      assert.deepEqual(result.missingDescriptions, [heading], body);
      assert.equal(result.changeTypeSelected, true);
      assert.deepEqual(result.missing, []);
      assert.equal(result.checklistComplete, false, body);
    }
    const body = complete.replace(`## ${heading}`, `## Missing ${heading}`);
    assert.deepEqual(evaluate(pull({ body }), [pluginFile], template).missingDescriptions, [heading]);
  }
  const unfilled = template.replace("- [ ] Bug fix", "- [x] Bug fix").replaceAll("- [ ] I have", "- [x] I have");
  assert.deepEqual(evaluate(pull({ body: unfilled }), [pluginFile], template).missingDescriptions,
    ["Problem", "Fix", "Scope"]);
  for (const prompt of template.matchAll(/<!-- (.+) -->/g)) {
    const body = complete.replace(descriptions.Problem, prompt[1]);
    assert.deepEqual(evaluate(pull({ body }), [pluginFile], template).missingDescriptions, ["Problem"]);
  }
});

test("description text supports paragraphs, lists, links, and inline formatting without a minimum length", () => {
  for (const content of [
    "Fix.", "- Fix handling of null values.\n- Update the regression test.",
    "[Issue details](https://example.com/issue)", "**Fix** the `null` case.",
    "<!-- Author note. -->\n\nHandle null values.", "Handle <!-- hidden note --> null values.",
  ]) {
    const body = complete.replace(descriptions.Fix, content);
    assert.equal(evaluate(pull({ body }), [pluginFile], template).checklistComplete, true, body);
  }
});

test("description headings in quoted, fenced, indented, or commented examples do not count", () => {
  const checklist = complete.slice(complete.indexOf("## Type of Change"));
  for (const example of [
    "```\n" + descriptionSection + "```\n",
    "<!--\n" + descriptionSection + "-->\n",
    descriptionSection.split("\n").map((line) => "> " + line).join("\n"),
    descriptionSection.split("\n").map((line) => "    " + line).join("\n"),
  ]) {
    const result = evaluate(pull({ body: example + "\n\n" + checklist }), [pluginFile], template);
    assert.deepEqual(result.missingDescriptions, ["Problem", "Fix", "Scope"]);
    assert.equal(result.checklistComplete, false);
  }
});

test("missing description text updates one targeted reminder and clears after the author fills it in", async () => {
  const f = fixture();
  for (const [body, conclusion] of [
    [complete.replace(descriptions.Scope, "<!-- Describe affected files. -->"), "failure"],
    [complete, "success"],
    [complete.replace(descriptions.Scope, ""), "failure"],
  ]) {
    f.pr.body = body;
    await notify(f.api, repository, 42, template);
    assert.equal(f.writes.at(-1).body.conclusion, conclusion);
    assert.equal(f.comments.length, 1);
    if (conclusion === "failure") {
      assert.match(f.comments[0].body, /Add a short explanation under `Scope`/);
      assert.ok(!f.comments[0].body.includes("under `Problem`"));
      assert.ok(!f.comments[0].body.includes("- I have reviewed"));
    } else {
      assert.match(f.comments[0].body, /Problem, Fix, and Scope are filled in/);
    }
  }
  assert.equal(f.writes.filter((write) => write.method === "POST" && write.endpoint.endsWith("/comments")).length, 1);
});

test("requires the four confirmations in the dedicated section", () => {
  assert.equal(evaluate(pull(), [pluginFile], template).checklistComplete, true);
  for (const body of [null, "", template, complete.replace("## Startup Advisor review checklist", "## Other")]) {
    assert.equal(evaluate(pull({ body }), [pluginFile], template).checklistComplete, false);
  }
  for (const item of checklistItems(template)) {
    const checkedLine = `- [x] ${item.text}`;
    for (const body of [
      complete.replace(checkedLine, ""),
      complete.replace(checkedLine, checkedLine.replace("[x]", "[ ]")),
      complete.replace(checkedLine, `${checkedLine}\n${checkedLine}`),
      complete.replace(checkedLine, `${checkedLine} (changed text)`),
    ]) {
      assert.equal(evaluate(pull({ body }), [pluginFile], template).checklistComplete, false);
    }
  }
});

test("one or multiple change types pass without selecting every type", () => {
  for (const body of [complete, complete.replace("- [ ] Documentation update", "- [x] Documentation update")]) {
    const result = evaluate(pull({ body }), [pluginFile], template);
    assert.equal(result.changeTypeSelected, true);
    assert.equal(result.checklistComplete, true);
    assert.ok(body.includes("- [ ] New skill"));
  }
  const body = complete.replace("- [x] Bug fix", "- [ ] Bug fix");
  const result = evaluate(pull({ body }), [pluginFile], template);
  assert.equal(result.changeTypeSelected, false);
  assert.equal(result.checklistComplete, false);
  assert.deepEqual(result.missing, []);
});

test("a change type must be a recognized option in its own visible section", () => {
  const confirmations = complete.slice(complete.indexOf("## Startup Advisor review checklist"));
  const selectedTypes = complete.slice(0, complete.indexOf("## Startup Advisor review checklist"));
  for (const body of [
    confirmations,
    complete.replace("## Type of Change", "## Other section"),
    complete.replace("- [x] Bug fix", "- [x] Unknown type"),
    `\`\`\`markdown\n${selectedTypes}\n\`\`\`\n${confirmations}`,
    `<!--\n${selectedTypes}\n-->\n${confirmations}`,
    selectedTypes.split("\n").map((line) => `> ${line}`).join("\n") + "\n" + confirmations,
  ]) {
    const result = evaluate(pull({ body }), [pluginFile], template);
    assert.equal(result.changeTypeSelected, false);
    assert.equal(result.checklistComplete, false);
  }
});

test("selecting every change type does not satisfy unchecked author confirmations", () => {
  const body = typeSection.replaceAll("- [ ]", "- [x]") +
    "## Startup Advisor review checklist" + confirmationSection;
  const result = evaluate(pull({ body }), [pluginFile], template);
  assert.equal(result.changeTypeSelected, true);
  assert.equal(result.checklistComplete, false);
  assert.equal(result.missing.length, 4);
});

test("accepts uppercase checks and CRLF, but excludes quoted, fenced, and commented examples", () => {
  assert.equal(evaluate(pull({ body: complete.replaceAll("[x]", "[X]").replaceAll("\n", "\r\n") }),
    [pluginFile], template).checklistComplete, true);
  for (const body of [
    `\`\`\`markdown\n${complete}\n\`\`\``,
    `~~~markdown\n${complete}\n~~~`,
    `<!--\n${complete}\n-->`,
    `<!--\n${complete}`,
    complete.split("\n").map((line) => `> ${line}`).join("\n"),
  ]) {
    assert.equal(evaluate(pull({ body }), [pluginFile], template).checklistComplete, false);
  }
});

test("horizontal whitespace normalization does not change indentation or confirmation wording", () => {
  const body = complete.replace("I have tested my changes", "I\thave tested my changes");
  assert.equal(evaluate(pull({ body }), [pluginFile], template).checklistComplete, false);
  const indented = complete.split("\n").map((line) => "\t" + line).join("\n");
  assert.equal(evaluate(pull({ body: indented }), [pluginFile], template).checklistComplete, false);
});

test("GFM tables keep example headings and checkboxes out of the required sections", async () => {
  const table = "| Example |\n| --- |\n" +
    complete.split("\n").filter(Boolean).map((line) => `| ${line} |`).join("\n");
  for (const [body, expected] of [[table, false], [table + "\n\n" + complete, true]]) {
    const f = fixture({ pr: pull({ body }) });
    assert.equal(evaluate(f.pr, f.files, template).checklistComplete, expected);
    await notify(f.api, repository, 42, template);
    assert.equal(f.writes.at(-1).body.conclusion, expected ? "success" : "failure");
  }
  for (const heading of ["## Type of Change", "## Startup Advisor review checklist"]) {
    const body = complete.replace(heading, `${heading}\n\n| Example |\n| --- |\n| ## Example only |\n`);
    assert.equal(evaluate(pull({ body }), [pluginFile], template).checklistComplete, true);
  }
});

test("literal fenced and HTML examples cannot produce successful confirmations", async () => {
  for (const body of [
    "```markdown\nExample copied from documentation:\n```markdown\n" + complete + "\n```",
    "<pre>\n" + complete + "\n</pre>",
    "  <PRE class=\"example\">\n" + complete + "\n  </PRE>",
    "<script>\n" + complete + "\n</script>",
    "<style>\n" + complete + "\n</style>",
    "<textarea>\n" + complete + "\n</textarea>",
    "<div>\n" + complete + "\n</div>",
    "<span>\n" + complete + "\n</span>",
    "<span data-label=\"example>notes\">\n" + complete + "\n</span>",
    "<?example\n" + complete + "\n?>",
    "<!EXAMPLE\n" + complete + "\n>",
    "<![CDATA[\n" + complete + "\n]]>",
    complete.replace("## Type of Change", "<!-- Note -->## Type of Change"),
    complete.replace("## Type of Change", "    ## Type of Change"),
    "```markdown\n```<!--not a closing fence-->\n" + complete + "\n```",
    "~~~markdown\n~~~markdown\n" + complete + "\n~~~",
    "````markdown\n```\n" + complete + "\n````",
    "```\n~~~\n" + complete + "\n```",
  ]) {
    const f = fixture({ pr: pull({ body }) });
    assert.equal(evaluate(f.pr, f.files, template).checklistComplete, false, body);
    assert.equal((await notify(f.api, repository, 42, template)).checklistComplete, false, body);
    assert.equal(f.writes.at(-1).body.conclusion, "failure");
  }
});

test("real confirmations after closed examples remain valid and count exactly once", () => {
  for (const prefix of [
    "```markdown\n" + complete + "\n   ```` \t\n",
    "~~~markdown\n" + complete + "\n~~~\t\n",
    "<pre>\n" + complete + "\n</pre>\n",
    "<!--\n" + complete + "\n-->\n",
    "```\n<!-- this is literal code\n```\n",
    "<pre>\n``` this is literal code\n</pre>\n",
    "<pre>Example</pre>\n",
    "An inline tag follows.\n<span>\n",
  ]) {
    const body = prefix + complete;
    assert.equal(evaluate(pull({ body }), [pluginFile], template).checklistComplete, true, body);
  }
});

test("list-contained literal examples are excluded without hiding a real checklist after them", async () => {
  const examples = [];
  for (const marker of ["-", "+", "*", "1.", "12.", "1)"]) {
    const indent = " ".repeat(marker.length + 1);
    const nested = complete.split("\n").map((line) => indent + line).join("\n");
    examples.push(`${marker} \`\`\`markdown\n${nested}\n${indent}\`\`\``);
    examples.push(`${marker} <pre>\n${nested}\n${indent}</pre>`);
  }
  examples.push("- Outer list\n  - ```markdown\n" +
    complete.split("\n").map((line) => "    " + line).join("\n") + "\n    ```");
  examples.push("-\t```markdown\n" +
    complete.split("\n").map((line) => "\t" + line).join("\n") + "\n\t```");
  for (const example of examples) {
    for (const [body, expected] of [
      [example, false], [example + "\n" + complete, true], [example + "\n\n" + complete, true],
    ]) {
      const f = fixture({ pr: pull({ body }) });
      assert.equal(evaluate(f.pr, f.files, template).checklistComplete, expected, body);
      assert.equal((await notify(f.api, repository, 42, template)).checklistComplete, expected, body);
      assert.equal(f.writes.at(-1).body.conclusion, expected ? "success" : "failure");
    }
  }
});

test("accepted checklist headings and task items must be unindented", () => {
  for (const spaces of [1, 2, 3]) {
    const body = complete.split("\n").map((line) => " ".repeat(spaces) + line).join("\n");
    assert.equal(evaluate(pull({ body }), [pluginFile], template).checklistComplete, false);
  }
});

test("same-line and multiline changes invalidate the entire required confirmation", async () => {
  for (const item of checklistItems(template)) {
    const checkedLine = `- [x] ${item.text}`;
    for (const extension of [
      " This is only an example; I have not tested anything.",
      "\n  This is only an example; I have not tested anything.",
      "\nThis is only an example; I have not tested anything.",
      "\n\n  This is only an example; I have not tested anything.",
      "\n  - This is only an example; I have not tested anything.",
      "\n  ```\n  This is only an example; I have not tested anything.\n  ```",
    ]) {
      const body = complete.replace(checkedLine, checkedLine + extension);
      const f = fixture({ pr: pull({ body }) });
      const result = evaluate(f.pr, f.files, template);
      assert.equal(result.changeTypeSelected, true);
      assert.equal(result.checklistComplete, false, body);
      assert.ok(result.missing.includes(item.text), body);
      assert.equal((await notify(f.api, repository, 42, template)).checklistComplete, false, body);
      assert.equal(f.writes.at(-1).body.conclusion, "failure");
    }
  }
});

test("continuation text also invalidates a change-type selection", () => {
  const body = complete.replace("- [x] Bug fix", "- [x] Bug fix\n  This is not a bug fix.");
  const result = evaluate(pull({ body }), [pluginFile], template);
  assert.equal(result.changeTypeSelected, false);
  assert.equal(result.checklistComplete, false);
});

test("unrelated content outside a confirmation item does not invalidate it", async () => {
  const last = checklistItems(template).at(-1);
  const checkedLine = `- [x] ${last.text}`;
  for (const suffix of [
    "\n\nA separate paragraph.",
    "\n## Additional context\nA separate section.",
    "\n> A separate blockquote.",
    "\n- An unrelated sibling item.",
    "\n\n```\nA separate code example.\n```",
    "\n\n<pre>A separate code example.</pre>",
  ]) {
    const body = complete.replace(checkedLine, checkedLine + suffix);
    const f = fixture({ pr: pull({ body }) });
    assert.equal(evaluate(f.pr, f.files, template).checklistComplete, true, body);
    assert.equal((await notify(f.api, repository, 42, template)).checklistComplete, true, body);
    assert.equal(f.writes.at(-1).body.conclusion, "success");
  }
  const firstLine = `- [x] ${checklistItems(template)[0].text}`;
  const body = complete.replace(firstLine, firstLine + "\n\nA separate paragraph between confirmations.\n");
  assert.equal(evaluate(pull({ body }), [pluginFile], template).checklistComplete, true);
});

test("Setext H1/H2 boundaries exclude items from both required sections like ATX boundaries", async () => {
  for (const heading of ["## Type of Change", "## Startup Advisor review checklist"]) {
    for (const boundary of [
      "# Example only", "## Example only",
      "Example only\n=", "Example only\n============",
      "Example only\n-", "Example only\n--", "Example only\n------------",
      "Example only\n   === \t", "Example only\n   --- \t",
      "- ```markdown\n  A literal example.\n  ```\nExample only\n---",
      "- ```markdown\n  A literal example.\n  ```\nExample only\n===",
    ]) {
      const body = complete.replace(heading, `${heading}\n\n${boundary}`);
      const f = fixture({ pr: pull({ body }) });
      const result = evaluate(f.pr, f.files, template);
      assert.equal(result.checklistComplete, false, body);
      if (heading === "## Type of Change") {
        assert.equal(result.changeTypeSelected, false);
        assert.deepEqual(result.missing, []);
      } else {
        assert.equal(result.changeTypeSelected, true);
        assert.equal(result.missing.length, 4);
      }
      await notify(f.api, repository, 42, template);
      assert.equal(f.writes.at(-1).body.conclusion, "failure", body);
    }
  }
});

test("a later exact required heading reopens a section after Setext or ATX boundaries", async () => {
  for (const heading of ["## Type of Change", "## Startup Advisor review checklist"]) {
    const fields = heading === "## Type of Change" ? "- [x] Bug fix" :
      checklistItems(template).map((item) => `- [x] ${item.text}`).join("\n");
    for (const boundary of ["Example only\n====", "Example only\n----", "# Example only", "## Example only"]) {
      const misplaced = complete.replace(heading, `${heading}\n\n${boundary}`);
      const body = `${misplaced}\n\n${heading}\n\n${fields}\n`;
      const f = fixture({ pr: pull({ body }) });
      assert.equal(evaluate(f.pr, f.files, template).checklistComplete, true, body);
      await notify(f.api, repository, 42, template);
      assert.equal(f.writes.at(-1).body.conclusion, "success", body);
    }
  }
});

test("Setext syntax cannot replace the exact required template headings", () => {
  for (const heading of ["## Type of Change", "## Startup Advisor review checklist"]) {
    for (const underline of ["===", "---"]) {
      const body = complete.replace(heading, `${heading.slice(3)}\n${underline}`);
      assert.equal(evaluate(pull({ body }), [pluginFile], template).checklistComplete, false, body);
    }
  }
});

test("thematic breaks and literal Setext examples do not close required sections", () => {
  for (const heading of ["## Type of Change", "## Startup Advisor review checklist"]) {
    for (const note of [
      "---", "A separate note.\n\n---", "A separate note.\n- - -", "> A separate note.\n---",
      "A separate note.\n    ---",
      "```markdown\nExample only\n---\n```",
      "<pre>\nExample only\n===\n</pre>",
      "- ```markdown\n  Example only\n  ---\n  ```",
    ]) {
      const body = complete.replace(heading, `${heading}\n\n${note}\n`);
      assert.equal(evaluate(pull({ body }), [pluginFile], template).checklistComplete, true, body);
    }
  }
});

test("a blockquote with lazy continuation followed by an HR keeps the required section open", async () => {
  for (const heading of ["## Type of Change", "## Startup Advisor review checklist"]) {
    for (const note of ["> A quoted note\ncontinued quote\n---", "> A quoted note\ncontinued quote\nand another continuation\n---"]) {
      const body = complete.replace(heading, `${heading}\n\n${note}\n`);
      const f = fixture({ pr: pull({ body }) });
      assert.equal(evaluate(f.pr, f.files, template).checklistComplete, true, body);
      await notify(f.api, repository, 42, template);
      assert.equal(f.writes.at(-1).body.conclusion, "success", body);
    }
  }
});

test("the default template fails, but adding our descriptions and completed checklist to it passes", () => {
  const defaultTemplate = readFileSync(resolve(__dirname, "../pull_request_template.md"), "utf8")
    .replaceAll("- [ ]", "- [x]");
  assert.equal(evaluate(pull({ body: defaultTemplate }), [pluginFile], template).checklistComplete, false);
  const section = complete.slice(complete.indexOf("## Startup Advisor review checklist")).split("\n\n*By submitting")[0];
  const body = `${descriptionSection}${defaultTemplate}\n\n${section}\n\n## Additional context\nCustom author content.\n`;
  assert.equal(evaluate(pull({ body }), [pluginFile], template).checklistComplete, true);
});

test("includes deletions, mixed PRs, and renames into or out of the plugin", () => {
  for (const files of [
    [{ ...pluginFile, status: "removed" }],
    [{ filename: "README.md" }, pluginFile],
    [{ filename: "docs/moved.md", previous_filename: pluginFile.filename }],
    [{ ...pluginFile, previous_filename: "docs/moved.md" }],
  ]) {
    assert.equal(evaluate(pull({ changed_files: files.length }), files, template).inScope, true);
  }
  for (const filename of ["README.md", "plugins/another/README.md", "plugins/aws-startup-advisor-copy/README.md"]) {
    assert.equal(evaluate(pull(), [{ filename }], template).inScope, false);
  }
});

test("incomplete inventories and broken trusted templates fail closed", () => {
  assert.throws(() => evaluate(pull({ changed_files: 2 }), [pluginFile], template), /Incomplete/);
  assert.throws(() => evaluate(pull({ changed_files: 2 }), [pluginFile, pluginFile], template), /Incomplete/);
  assert.throws(() => evaluate(pull(), [pluginFile], ""), /four distinct/);
  assert.throws(() => evaluate(pull(), [pluginFile], template.replace("## Type of Change", "## Other")), /change type/);
});

test("checklist inspection paginates and checks the expected head", async () => {
  const files = Array.from({ length: 100 }, (_, i) => ({ filename: `docs/${i}.md` })).concat(pluginFile);
  const f = fixture({ pr: pull({ changed_files: files.length }), files });
  const { result } = await inspect(f.api, repository, 42, template, "a".repeat(40));
  assert.equal(result.inScope, true);
  assert.equal(result.checklistComplete, true);
  assert.deepEqual(f.writes, []);
  await assert.rejects(inspect(f.api, repository, 42, template, "c".repeat(40)), /head changed/);
});

test("API errors and edits during inventory inspection cannot produce a checklist result", async () => {
  await assert.rejects(inspect(async () => { throw new Error("API unavailable"); },
    repository, 42, template), /API unavailable/);
  for (const change of [
    (pr) => { pr.body = template; },
    (pr) => { pr.head.sha = "c".repeat(40); },
    (pr) => { pr.base.sha = "c".repeat(40); },
    (pr) => { pr.draft = true; },
    (pr) => { pr.state = "closed"; },
  ]) {
    const f = fixture({ mutate: (pr, reads) => { if (reads === 2) change(pr); } });
    await assert.rejects(inspect(f.api, repository, 42, template), /changed during/);
    assert.deepEqual(f.writes, []);
  }
});

test("unrelated and closed PRs get a neutral check and no reminder", async () => {
  const unrelated = fixture({ files: [{ filename: "README.md" }] });
  await notify(unrelated.api, repository, 42, template);
  assert.deepEqual(unrelated.comments, []);
  assert.equal(unrelated.writes.at(-1).body.conclusion, "neutral");
  const closed = fixture({ pr: pull({ state: "closed", body: template }) });
  await notify(closed.api, repository, 42, template);
  assert.deepEqual(closed.comments, []);
  assert.equal(closed.writes.at(-1).body.conclusion, "neutral");
});

test("a failed inventory or stale event completes a failing check instead of leaving an old success", async () => {
  for (const pr of [pull({ changed_files: 2 }), pull({ head: { sha: "c".repeat(40) } })]) {
    const f = fixture({ pr });
    await assert.rejects(notify(f.api, repository, 42, template));
    assert.equal(f.writes[0].body.status, "in_progress");
    assert.equal(f.writes[0].body.head_sha, "a".repeat(40));
    assert.equal(f.writes.at(-1).body.conclusion, "failure");
    assert.deepEqual(f.comments, []);
  }
});
test("removing the plugin from a PR clears its previous reminder and blocking check", async () => {
  const f = fixture({ pr: pull({ body: template }) });
  await notify(f.api, repository, 42, template);
  f.files[0] = { filename: "README.md" };
  const result = await notify(f.api, repository, 42, template);
  assert.equal(result.inScope, false);
  assert.equal(f.writes.at(-1).body.conclusion, "neutral");
  assert.equal(f.comments.length, 1);
  assert.match(f.comments[0].body, /checklist is not required/);
});
test("unchecked -> checked -> unchecked updates one reminder and the check outcome", async () => {
  const f = fixture({ pr: pull({ body: template }) });
  const outcomes = [];
  for (const body of [template, template, complete, template]) {
    f.pr.body = body;
    const result = await notify(f.api, repository, 42, template);
    outcomes.push(result.checklistComplete);
  }
  assert.deepEqual(outcomes, [false, false, true, false]);
  assert.equal(f.comments.length, 1);
  assert.equal(f.writes.filter((write) => write.method === "POST" && write.endpoint.endsWith("/comments")).length, 1);
  assert.equal(f.writes.filter((write) => write.method === "PATCH" && write.endpoint.includes("/issues/comments/")).length, 2);
  assert.deepEqual(f.writes.filter((write) => write.body.conclusion).map((write) => write.body.conclusion),
    ["failure", "failure", "success", "failure"]);
  assert.match(f.comments[0].body, /awaiting author confirmation/);
});

test("a completed checklist does not publish an unsolicited success comment", async () => {
  const f = fixture();
  await notify(f.api, repository, 42, template);
  assert.deepEqual(f.comments, []);
  assert.equal(f.writes.at(-1).body.conclusion, "success");
});

test("a missing change type gets a targeted reminder that clears after selection", async () => {
  const f = fixture({ pr: pull({ body: complete.replace("- [x] Bug fix", "- [ ] Bug fix") }) });
  await notify(f.api, repository, 42, template);
  assert.equal(f.writes.at(-1).body.conclusion, "failure");
  assert.match(f.comments[0].body, /Select at least one option under `Type of Change`/);
  assert.ok(!f.comments[0].body.includes("- I have reviewed"));
  f.pr.body = complete;
  await notify(f.api, repository, 42, template);
  assert.equal(f.writes.at(-1).body.conclusion, "success");
  assert.equal(f.comments.length, 1);
  assert.match(f.comments[0].body, /A change type is selected/);
  f.pr.body = complete.replace("- [x] Bug fix", "- [ ] Bug fix");
  await notify(f.api, repository, 42, template);
  assert.equal(f.writes.at(-1).body.conclusion, "failure");
  assert.equal(f.comments.length, 1);
});

test("only updates our GitHub Actions reminder, including on later comment pages", async () => {
  const comments = Array.from({ length: 100 }, (_, i) =>
    ({ id: i + 100, body: "Unrelated", user: { login: "person", type: "User" } }));
  comments[0].body = `${COMMENT_MARKER}\nCopied marker`;
  comments.push({ id: 999, body: `${COMMENT_MARKER}\nOld reminder`, user: { login: "github-actions[bot]", type: "Bot" } });
  const f = fixture({ comments, pr: pull({ body: template }) });
  await notify(f.api, repository, 42, template);
  const edits = f.writes.filter((write) => write.endpoint.includes("/issues/comments/"));
  assert.equal(edits.length, 1);
  assert.ok(edits[0].endpoint.endsWith("/999"));
});

test("a mid-run edit fails the check instead of publishing a stale success", async () => {
  for (const editOnRead of [3, 4]) {
    const f = fixture({ mutate: (pr, reads) => { if (reads === editOnRead) pr.body = template; } });
    await assert.rejects(notify(f.api, repository, 42, template), /PR changed/);
    assert.equal(f.writes.at(-1).body.conclusion, "failure");
    assert.ok(f.writes.every((write) => write.body.conclusion !== "success"));
  }
});

test("the checklist check behaves the same for Draft and ready PRs", async () => {
  const f = fixture({ pr: pull({ draft: true, body: template }) });
  await notify(f.api, repository, 42, template);
  f.pr.body = complete;
  const result = await notify(f.api, repository, 42, template);
  assert.equal(result.checklistComplete, true);
  assert.equal(f.writes.at(-1).body.conclusion, "success");
  const completedReminder = f.comments[0].body;
  f.pr.draft = false;
  assert.equal((await notify(f.api, repository, 42, template)).checklistComplete, true);
  assert.equal(f.comments[0].body, completedReminder);
});

test("the real CLI reads a comment page above 1 MiB and updates a reminder on the next page", (t) => {
  const comments = Array.from({ length: 100 }, (_, i) => ({
    id: i + 100, body: "Detailed review notes. ".repeat(600), user: { login: "reviewer", type: "User" },
  }));
  assert.ok(Buffer.byteLength(JSON.stringify(comments)) > 1024 * 1024);
  comments.push({ id: 999, body: `${COMMENT_MARKER}\nOld reminder`, user: { login: "github-actions[bot]", type: "Bot" } });
  const child = runCli(t, { comments });
  assert.equal(child.status, 0, child.stderr);
  assert.equal(JSON.parse(child.stdout).checklistComplete, true);
  assert.ok(child.calls.some((call) => call.endpoint.endsWith("/comments?per_page=100&page=2")));
  assert.ok(child.calls.some((call) => call.method === "PATCH" && call.endpoint.endsWith("/issues/comments/999")));
  assert.equal(child.calls.at(-1).body.conclusion, "success");
});

test("the real CLI reads a file page above 1 MiB and finds the plugin on the next page", (t) => {
  const files = Array.from({ length: 100 }, (_, i) => ({
    filename: `docs/${i}.md`, patch: "+file content\n".repeat(1100),
  }));
  assert.ok(Buffer.byteLength(JSON.stringify(files)) > 1024 * 1024);
  files.push({ filename: "docs/moved.md", previous_filename: pluginFile.filename });
  const child = runCli(t, { pr: pull({ changed_files: files.length }), files });
  assert.equal(child.status, 0, child.stderr);
  assert.equal(JSON.parse(child.stdout).inScope, true);
  assert.ok(child.calls.some((call) => call.endpoint.endsWith("/files?per_page=100&page=2")));
  assert.equal(child.calls.at(-1).body.conclusion, "success");
});

test("the real CLI still fails closed on API errors and incomplete inventories", (t) => {
  for (const options of [{ failureEndpoint: "/comments?" }, { pr: pull({ changed_files: 2 }) }]) {
    const child = runCli(t, options);
    assert.equal(child.status, 1);
    assert.equal(child.calls.at(-1).body.conclusion, "failure");
    assert.ok(child.calls.every((call) => call.body?.conclusion !== "success"));
  }
});
