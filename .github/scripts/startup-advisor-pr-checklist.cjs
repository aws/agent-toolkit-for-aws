const { spawn } = require("node:child_process");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const { text } = require("node:stream/consumers");
const { lexer } = require("marked");

const CHECK_NAME = "Startup Advisor author checklist";
const COMMENT_MARKER = "<!-- startup-advisor-author-checklist -->";
const PLUGIN_PREFIX = "plugins/aws-startup-advisor/";
const TEMPLATE_PATH = ".github/PULL_REQUEST_TEMPLATE/startup-advisor.md";
const HEADING = "## Startup Advisor review checklist";
const TYPE_HEADING = "## Type of Change";
const DESCRIPTION_HEADINGS = ["Problem", "Fix", "Scope"];

function markdownTokens(source) {
  // Marked's block rules expect spaces at line ends. Preserve indentation and item text.
  const normalized = (source || "").replace(/\r\n|\r/g, "\n").replace(/\t(?=[ \t]*$)/gm, " ");
  return lexer(normalized, { gfm: true });
}

function checklistItems(source, heading = HEADING) {
  const items = [];
  let inSection = false;
  // Only root headings and their direct task items can contain confirmations.
  for (const token of markdownTokens(source)) {
    if (token.type === "heading" && [1, 2].includes(token.depth)) {
      // Setext headings end a section; only the exact template syntax opens one.
      inSection = token.depth === 2 && token.raw.trimEnd() === heading;
      continue;
    }
    if (inSection && token.type === "list") {
      for (const entry of token.items) {
        const [line, ...continuation] = entry.raw.split(/\r\n|\r|\n/);
        const item = entry.task && line.match(/^- \[([ xX])\] (.+?)\s*$/);
        if (item) items.push({
          text: item[2],
          checked: entry.checked === true,
          continued: continuation.some((line) => !/^[ \t]*$/.test(line)),
        });
      }
    }
  }
  return items;
}

function descriptionText(tokens) {
  return tokens.map((token) => {
    if (token.type === "list") return token.items.map((item) => descriptionText(item.tokens)).join(" ");
    if (["paragraph", "text", "strong", "em", "link", "codespan"].includes(token.type)) {
      return token.tokens ? descriptionText(token.tokens) : token.text;
    }
    // Comments, code blocks, and headings are not author explanations.
    return "";
  }).join(" ");
}

function missingDescriptions(source, template) {
  const sections = new Map(DESCRIPTION_HEADINGS.map((heading) => [heading, []]));
  const prompts = [...template.matchAll(/<!--([\s\S]*?)-->/g)]
    .map((match) => match[1].replace(/\s+/g, " ").trim().toLowerCase());
  let current;
  for (const token of markdownTokens(source)) {
    if (token.type === "heading" && token.depth <= 2) {
      current = DESCRIPTION_HEADINGS.find((heading) => token.raw.trimEnd() === `## ${heading}`);
    } else if (current) {
      sections.get(current).push(token);
    }
  }
  return DESCRIPTION_HEADINGS.filter((heading) => {
    const content = descriptionText(sections.get(heading))
      .replace(/&(?:#\d+|#x[\da-f]+|[a-z]\w*);/gi, "").replace(/\s+/g, " ").trim();
    return !/[\p{L}\p{N}]/u.test(content) || /^(?:TODO|TBD)[.!:]?$/i.test(content) ||
      prompts.includes(content.toLowerCase());
  });
}

function evaluate(pr, files, template) {
  const confirmations = checklistItems(template);
  const expected = confirmations.map((item) => item.text);
  if (expected.length !== 4 || new Set(expected).size !== expected.length || confirmations.some((item) => item.continued)) {
    throw new Error("The trusted template must contain four distinct single-line confirmations.");
  }
  const options = checklistItems(template, TYPE_HEADING);
  const changeTypes = options.map((item) => item.text);
  if (!changeTypes.length || new Set(changeTypes).size !== changeTypes.length || options.some((item) => item.continued)) {
    throw new Error("The trusted template must contain distinct single-line change type options.");
  }
  if (files.length !== pr.changed_files || new Set(files.map((file) => file.filename)).size !== files.length) {
    throw new Error("Incomplete PR file inventory; checklist requirements are unknown.");
  }
  const inScope = files.some((file) =>
    [file.filename, file.previous_filename].some((name) => name?.startsWith(PLUGIN_PREFIX)));
  const items = checklistItems(pr.body);
  const missing = expected.filter((text) => {
    const matches = items.filter((item) => item.text === text);
    return matches.length !== 1 || !matches[0].checked || matches[0].continued;
  });
  const changeTypeSelected = checklistItems(pr.body, TYPE_HEADING)
    .some((item) => item.checked && !item.continued && changeTypes.includes(item.text));
  const missingSections = missingDescriptions(pr.body, template);
  return {
    number: pr.number,
    head: pr.head.sha,
    inScope,
    missing,
    missingDescriptions: missingSections,
    changeTypeSelected,
    checklistComplete: missingSections.length === 0 && changeTypeSelected && missing.length === 0,
  };
}

function unchanged(before, after) {
  return before.head.sha === after.head.sha && before.base.sha === after.base.sha &&
    before.state === after.state && before.draft === after.draft &&
    before.body === after.body && before.changed_files === after.changed_files;
}

async function githubApi(method, endpoint, body) {
  const args = ["api", "--method", method, endpoint];
  if (body !== undefined) args.push("--input", "-");
  const input = body === undefined ? undefined : JSON.stringify(body);
  const child = spawn("gh", args, { stdio: ["pipe", "pipe", "pipe"] });
  // Stream both pipes instead of imposing execFileSync's 1 MiB capture limit.
  const completion = new Promise((resolve, reject) => {
    child.once("error", reject);
    child.stdin.on("error", reject);
    child.once("close", (code, signal) => resolve({ code, signal }));
  });
  const output = Promise.all([text(child.stdout), text(child.stderr), completion]);
  child.stdin.end(input);
  const [stdout, stderr, { code, signal }] = await output;
  if (code !== 0) throw new Error(`gh api failed (${signal || code}): ${stderr.trim()}`);
  return JSON.parse(stdout);
}

async function pages(api, endpoint) {
  const results = [];
  for (let page = 1; ; page++) {
    const rows = await api("GET", `${endpoint}?per_page=100&page=${page}`);
    results.push(...rows);
    if (rows.length < 100) return results;
  }
}

async function inspect(api, repository, number, template, expectedHead) {
  const endpoint = `repos/${repository}/pulls/${number}`;
  const pr = await api("GET", endpoint);
  if (expectedHead && pr.head.sha !== expectedHead) throw new Error("PR head changed before checklist inspection.");
  const files = await pages(api, `${endpoint}/files`);
  const current = await api("GET", endpoint);
  if (!unchanged(pr, current)) throw new Error("PR changed during checklist inspection; retry with fresh data.");
  return { pr: current, result: evaluate(current, files, template) };
}

function reminder(repository, result) {
  const templateUrl = `https://github.com/${repository}/blob/main/${TEMPLATE_PATH}`;
  if (!result.inScope) {
    return `${COMMENT_MARKER}\nThis PR does not change Startup Advisor. Its author checklist is not required.`;
  }
  if (result.checklistComplete) {
    return `${COMMENT_MARKER}\nProblem, Fix, and Scope are filled in. A change type is selected and all four Startup Advisor author confirmations are complete.\n\n` +
      "The author checklist check now passes. CI and reviewers still need to verify the change.";
  }
  const requiredUpdates = [
    ...result.missingDescriptions.map((heading) => `Add a short explanation under \`${heading}\`.`),
    ...(!result.changeTypeSelected ? ["Select at least one option under `Type of Change`."] : []),
    ...result.missing,
  ];
  return `${COMMENT_MARKER}\nThis PR changes Startup Advisor and is awaiting author confirmation.\n\n` +
    `Use [the Startup Advisor PR template](${templateUrl}) to update the following items in the PR description:\n\n` +
    requiredUpdates.map((text) => `- ${text}`).join("\n") +
    "\n\nFill in Problem, Fix, and Scope using paragraphs or lists; comments and TODO/TBD placeholders do not count. " +
    "Select one or more change types. Keep all four author confirmations exactly once, with their original wording, and check every confirmation. " +
    "Paste the headings and checkbox lines without indentation, and keep each checkbox on one line. " +
    "Put notes in a separate unindented paragraph after a blank line. The check will run again when you update the description.";
}

async function notify(api, repository, number, template, expectedHead) {
  if (!/^[a-f0-9]{40}$/.test(expectedHead || "")) throw new Error("Notification requires the event's head SHA.");
  const check = await api("POST", `repos/${repository}/check-runs`, {
    name: CHECK_NAME,
    head_sha: expectedHead,
    status: "in_progress",
    external_id: `startup-advisor-checklist-${number}`,
  });
  try {
    const { pr, result } = await inspect(api, repository, number, template, expectedHead);
    if (pr.state !== "open") {
      await api("PATCH", `repos/${repository}/check-runs/${check.id}`, {
        status: "completed",
        conclusion: "neutral",
        output: { title: "PR closed", summary: "This PR is closed; no author checklist is required." },
      });
      return result;
    }
    const comments = await pages(api, `repos/${repository}/issues/${number}/comments`);
    const existing = comments.find((comment) =>
      comment.user?.login === "github-actions[bot]" &&
      comment.user?.type === "Bot" && comment.body?.startsWith(COMMENT_MARKER));
    const current = await api("GET", `repos/${repository}/pulls/${number}`);
    if (!unchanged(pr, current)) throw new Error("PR changed before the reminder; retry with fresh data.");
    const body = reminder(repository, result);
    if (existing && existing.body !== body) {
      await api("PATCH", `repos/${repository}/issues/comments/${existing.id}`, { body });
    } else if (!existing && result.inScope && !result.checklistComplete) {
      await api("POST", `repos/${repository}/issues/${number}/comments`, { body });
    }
    const finalPr = await api("GET", `repos/${repository}/pulls/${number}`);
    if (!unchanged(pr, finalPr)) throw new Error("PR changed before the check completed; retry with fresh data.");
    await api("PATCH", `repos/${repository}/check-runs/${check.id}`, {
      status: "completed",
      conclusion: !result.inScope ? "neutral" : result.checklistComplete ? "success" : "failure",
      output: {
        title: !result.inScope ? "Startup Advisor checklist not required" :
          result.checklistComplete ? "PR checklist complete" : "PR checklist incomplete",
        summary: body,
      },
    });
    return result;
  } catch (error) {
    await api("PATCH", `repos/${repository}/check-runs/${check.id}`, {
      status: "completed",
      conclusion: "failure",
      output: { title: "Checklist could not be verified", summary: error.message },
    });
    throw error;
  }
}

async function main() {
  const [repository, number, expectedHead, ...extra] = process.argv.slice(2);
  if (!/^[\w.-]+\/[\w.-]+$/.test(repository || "") || !/^[1-9]\d*$/.test(number || "") ||
      !/^[a-f0-9]{40}$/.test(expectedHead || "") || extra.length) {
    throw new Error("Usage: node startup-advisor-pr-checklist.cjs <owner/repo> <pr-number> <event-head>");
  }
  const template = readFileSync(resolve(__dirname, "../PULL_REQUEST_TEMPLATE/startup-advisor.md"), "utf8");
  const result = await notify(githubApi, repository, Number(number), template, expectedHead);
  console.log(JSON.stringify(result));
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}

module.exports = { CHECK_NAME, COMMENT_MARKER, checklistItems, evaluate, inspect, notify };
