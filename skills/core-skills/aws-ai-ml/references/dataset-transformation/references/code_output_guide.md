# Code Output Guide

## Mode Selection

Ask the user once before generating code: **"Would you like me to generate a Jupyter notebook or a Python script?"**

If the output format has already been decided in the conversation context, keep consistent — do not re-ask.

## Shared Rules (Both Modes)

- Use EXACTLY the imports shown in each code template — do not add extras
- Replace `[PLACEHOLDER]` values with user-specific configuration
- Include `set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)` in the setup cell/section

## Reading Code Templates

Templates use `# Cell N: Label` markers to delimit sections. `# NOTEBOOK_ONLY` skips a line in script mode; `# NOTEBOOK_ONLY_SECTION` on a `# Cell N:` line skips the entire section.

## Notebook Mode

Write a `.ipynb` file in `<project-dir>/notebooks/`.

**Naming and appending:**

- Notebook path: `<project-dir>/notebooks/<project-name>.ipynb`
- If the notebook already exists → ask: _"Would you like me to append cells to the existing notebook, or create a new one?"_
- If it doesn't exist → create it
- When appending, use the template's `# Cell 0 [markdown]:` cell as the section divider before the new cells

**Formatting:**

- Use your file write tool to create the complete notebook JSON, OR use notebook MCP tools (`create_notebook`, `add_cell`) if available
- Do NOT use bash commands, shell scripts, or `echo`/`cat` piping
- 2-space JSON indentation
- Each source line is a separate string ending with `\n` (except the last)
- Escape quotes: `\"`
- No trailing commas

**Structure:**

- Wrap cells in `{"cells": [...], "metadata": {...}, "nbformat": 4, "nbformat_minor": 4}`
- Code cells: `cell_type`, `execution_count: null`, `metadata: {}`, `outputs: []`, `source: [...]`
- Markdown cells: `cell_type: "markdown"`, no `execution_count` or `outputs`
- `# Cell 0 [markdown]:` becomes a markdown cell; all others become code cells

**Execution:**

- If notebook execution tools are available (e.g., `run_cell` MCP), offer to run cells for the user. If not available, tell the user to run cells themselves.
- Do NOT use bash commands or inline scripts to execute notebook cells.

## Script Mode

Write a numbered `.py` file in `<project-dir>/scripts/`.

**Naming:**

- Format: `NN_<descriptive_name>.py` (e.g., `01_sft_finetuning.py`) — use the next available number in `<project-dir>/scripts/`

**Formatting:**

- Plain Python file, standard text
- Use `# %%` cell markers to preserve logical sections (IDE-compatible)
- Include a docstring at the top describing what the script does
- `# Cell 0 [markdown]:` → a comment block or docstring

**Dependencies:**

- Install any required pip packages directly (e.g., `pip install 'sagemaker>=3.7.1,<4.0'`) before writing or running the script. Do not embed install commands in the script itself.

**Execution:**

- Run the script using standard Python execution (`python3 <script>.py`).
