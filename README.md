# iterm2

A local Codex plugin for opening background iTerm2 tabs in the intended window and group, and closing explicitly selected tabs. The Python helper accepts arbitrary commands and reports creation and grouping separately. It uses iTerm2's Python API; no MCP server is required.

| Skill | Purpose | Example requests |
| --- | --- | --- |
| [tabs](skills/tabs/SKILL.md) | Inspect destinations, open grouped background tabs, and close tabs by ID. | “Open a new tab in this project group.”<br>“Close the tab opened for this assignment.” |

Requires macOS, `uv`, and a running iTerm2 with its Python API enabled and tab-group support. Install through the repository marketplace:

```sh
codex plugin marketplace add kpurdon/iterm2
codex plugin add iterm2@kpurdon-iterm2
```

Builder can supply the assignment and retain delivery ownership while this plugin opens the terminal. See [Codex integration](skills/tabs/references/codex.md) for command construction and origin selection.

To close a tab, inspect its ID with `list`, then pass that ID explicitly:

```sh
uv run --quiet --script skills/tabs/scripts/tabs.py list
uv run --quiet --script skills/tabs/scripts/tabs.py close --tab-id TAB_ID
```

Closure includes every split pane and can terminate running programs. Add `--force` to bypass iTerm's confirmation, or `--dry-run` to validate arguments without connecting. The helper reports `close: confirmed` only after verifying the tab is gone; an uncertain result exits with status 3 and should be reconciled with `list` before retrying. Closing alone does not require tab-group support.
