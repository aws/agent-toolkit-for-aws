
# Directory Management

## Principles

1. **One thing at a time.** Each response advances exactly one decision.
2. **Confirm before proceeding.** Always wait for the user's reply before taking the next action. You are a guide, not a runaway train.
3. **A recommendation is not confirmation.** Presenting a suggested name does not mean the user has accepted it. You must receive an explicit reply before creating any directory.
4. **Always end with a question.** Whenever you ask the user something, your response must end with that question. Never answer your own question in the same turn.

## Project Setup

Before any work begins, resolve the project name:

1. If the project name is already known from conversation context, use it.
2. Otherwise, scan for existing `*/PLAN.md` files in the current directory. If found, ask the user if they are resuming an existing project and load that `PLAN.md` into context.
3. **Ask for confirmation.** Derive a ≤64-char lowercase slug (`[a-z0-9-]` only) from the conversation context and present it to the user as a question — for example: *"I'll use `my-project-name` as the project folder — does that work, or would you prefer something different?"* End your response there. Do not create the directory in this step.

   ⏸ Wait for the user's reply before proceeding.

4. **Create the directory.** Once the user confirms the name (or provides an alternative), create the `<project-name>/` directory and its subdirectories.

## Directory Structure

When working with the agent, all generated files are organized under an project directory.

```
<project-name>/
├── specs/  
│   ├── PLAN.md             # Your customization plan
├── scripts/                # Generated Python scripts
│   ├── <project-name>_transform_fn.py
├── notebooks/              # Generated Jupyter notebooks
│   ├── <project-name>.ipynb
└── manifests/              # Machine-readable outputs (JSON)

```
