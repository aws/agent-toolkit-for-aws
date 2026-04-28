# Agent Skills for AWS

This directory contains agent skills — curated packages of instructions and reference materials that help AI coding agents complete AWS tasks effectively.

## How skills work

Each skill is a directory containing a `SKILL.md` file with a description and instructions, plus optional reference files and scripts. Skills use progressive disclosure:

1. At startup, your agent reads only the skill name and description (~50-100 tokens per skill).
2. When a task matches a skill's description, the agent loads the full instructions.
3. The agent follows the skill's procedures, loading reference files only as needed.
4. When the task is complete, the skill context is released.

This means having many skills installed doesn't slow your agent down or consume your context window.

## Using skills

There are three ways to get skills:

- **Install a plugin** — If you installed a plugin (aws-core, aws-agent-building, or aws-data-analytics), the skills bundled with that plugin are already available to your agent.

- **Install locally** — Copy skill directories from this repository to your agent's skills location, or use `npx skills add aws/agent-toolkit-for-aws`.

- **Discover at runtime** — Agents can search for and load skills on demand through the AWS MCP Server, without any local installation. Ask your agent: "Search for AWS skills related to databases."

To install skills locally, copy the skill directory to your agent's skills location:

| Agent | Global skills path | Project skills path |
|-------|-------------------|-------------------|
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| Codex | `~/.codex/skills/` | `.agents/skills/` |
| Cursor | `~/.cursor/skills/` | `.cursor/skills/` |

## Skill format

Each skill follows this structure:

```
skill-name/
├── SKILL.md              # Required: description + instructions
├── references/           # Optional: detailed guidance for subtasks
│   ├── topic-a.md
│   └── topic-b.md
└── scripts/              # Optional: code scripts for deterministic operations
    └── validate.sh
```

The `SKILL.md` file includes YAML frontmatter with a `name` and `description`, followed by the skill's instructions in markdown. Skills can also include slash commands that let you invoke them directly.
