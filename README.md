# iterm2

A local Codex plugin for opening background iTerm2 tabs in the intended window and group. The Python helper accepts arbitrary commands and reports creation and grouping separately. It uses iTerm2's Python API; no MCP server is required.

| Skill | Purpose | Example requests |
| --- | --- | --- |
| [tabs](skills/tabs/SKILL.md) | Inspect destinations and open grouped background tabs. | “Open a new tab in this project group.”<br>“Start Codex in a separate group for this assignment.” |

Requires macOS, `uv`, and a running iTerm2 with its Python API enabled and tab-group support. Install through the repository marketplace:

```sh
codex plugin marketplace add kpurdon/iterm2
codex plugin add iterm2@kpurdon-iterm2
```

Builder can supply the assignment and retain delivery ownership while this plugin opens the terminal. See [Codex integration](skills/tabs/references/codex.md) for command construction and origin selection.
