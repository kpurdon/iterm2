---
name: tabs
description: Inspect iTerm2 destinations and open background tabs in the intended window and group.
---

# tabs

Use the bundled [helper](scripts/tabs.py) with `uv run --quiet --script`; consult its help for arguments. It requires macOS, `uv`, a running iTerm2 with its Python API enabled, and API support for tab groups. Report missing prerequisites; a readiness check does not authorize a launch.

Use `list` to inspect destination IDs and names without reading terminal output. Prefer a recorded group ID or verified origin session. Reuse the origin's group; use `--group` to name its initial group. Group IDs survive renames. With no origin, group-name lookup can create duplicates after a rename, so use a verified ID for subsequent launches.

Use `open --new-group NAME` when a separate group is requested; it leaves the origin in its existing group. `--window-id` targets a verified window. Use `--desktop` only when there is no originating terminal. First-window creation may take focus.

Supply the caller's working directory, optional title, and command arguments after `--`. Use `--append-file` for private text that must become one final command argument; the source file remains caller-owned. The helper does not add assignments or infer an agent's configuration. For Codex launches and its optional origin adapter, read [Codex integration](references/codex.md).

Return the creation and grouping results with their IDs. A terminal launch does not prove program startup or delivery. If creation is uncertain, preserve the returned payload file and reconcile the destination before retrying. If creation succeeded but grouping failed, repair only the grouping or report it; never open another tab to fix grouping. Request IDs correlate results and do not prevent duplicate launches.
