import anthropic

client = anthropic.Anthropic()


def run_agent(task: str) -> str:
    resp = client.beta.messages.create(
        model="claude-sonnet-5",
        max_tokens=2048,
        tools=[
            {"type": "computer_20251124", "name": "computer", "display_width_px": 1280, "display_height_px": 800},
            {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"},
            {"type": "bash_20250124", "name": "bash"},
        ],
        betas=["computer-use-2025-11-24"],
        messages=[{"role": "user", "content": task}],
    )
    return "".join(block.text for block in resp.content if block.type == "text")
