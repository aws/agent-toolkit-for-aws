# Computer-Use Tools Reference

All tool names are prefixed with `agentaccess___` by the server. `mcp-proxy-for-aws` handles the prefix transparently — use the base names below when reasoning about tools. (Forwarded tools use a different `forwarded___` prefix — see tool-forwarding.md.)

The `screenshot` image dimensions define the coordinate space for all mouse tools. Coordinates are pixels from the top-left.

## Mouse

| Tool | Parameters | Notes |
|---|---|---|
| `left_click` | `x`, `y`, `modifiers?` | `modifiers` e.g. `"ctrl"`, `"ctrl+shift"` for modified clicks |
| `double_click` | `x`, `y`, `modifiers?` | |
| `triple_click` | `x`, `y`, `modifiers?` | Selects a line/paragraph |
| `right_click` | `x`, `y`, `modifiers?` | Context menu |
| `middle_click` | `x`, `y`, `modifiers?` | |
| `left_click_drag` | `start_x`, `start_y`, `end_x`, `end_y` | Drag/select/draw |
| `left_mouse_down` / `left_mouse_up` | `x`, `y`, `modifiers?` | Fine-grained drag control |
| `move_pointer` | `x`, `y` | Move without clicking (hover) |
| `scroll` | `x`, `y`, `scroll_direction` (`Up`/`Down`/`Left`/`Right`), `scroll_amount`, `modifiers?` | `scroll_amount` is in ticks; 120 ticks = one wheel notch |

## Keyboard

| Tool | Parameters | Notes |
|---|---|---|
| `type_text` | `text` (up to 10,000 chars) | Types character by character |
| `key` | `keys` | Single key or combo joined by `+`, e.g. `a`, `ctrl+c`, `ctrl+shift+s`, `Return`, `Escape`, `Tab`, `alt+F4`, `super`, `super+r`, `alt+Tab` |
| `hold_key` | `keys`, `duration` (1–30s) | Hold a key/combo for a duration |

Common combos: `ctrl+c`/`ctrl+v` (copy/paste), `ctrl+a` (select all), `ctrl+z` (undo), `alt+F4` (close window), `super` (Start menu), `super+r` (Run dialog), `alt+Tab` (switch windows), `Return` (Enter), `Escape` (dismiss dialog).

## Screen

| Tool | Parameters | Notes |
|---|---|---|
| `screenshot` | `include_cursor?` (default false) | Returns a PNG. Defines the coordinate space for mouse tools. Expensive — see automation-best-practices.md. |

## Application Catalog (when enabled on the fleet)

Some fleets expose app-mode tools: `list_applications`, `launch_application`, `toggle_app_switcher`. Use these to enumerate and launch published applications instead of navigating the desktop shell. Check `tools/list` to see whether they are present.
