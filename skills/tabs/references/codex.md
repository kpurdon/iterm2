# Codex integration

The caller supplies the complete assignment, including any skill invocation and verified skill location. The terminal plugin does not discover Builder skills or own the receiving agent's work.

For an authorized new Codex session, use the installed helper with a private brief:

```sh
uv run --quiet --script /path/to/skills/tabs/scripts/tabs.py open \
  --cwd /path/to/worktree --group-id VERIFIED_GROUP_ID \
  --title 'Requested title' --append-file /path/to/private-brief.txt \
  -- codex --
```

The command runs through login zsh, using the user's PATH and Codex defaults. Put explicitly requested Codex flags between `codex` and its final `--`; do not assume parent runtime overrides are inherited. A terminal title does not set the native Codex thread title; include any requested native title in the receiving brief.

Prefer `--group-id` or `--origin-session`. When neither is available and the caller is running in a local Codex terminal, `--codex-origin` opts into the isolated [origin adapter](../scripts/codex_origin.py). It reads the local Codex control socket, follows parent threads to the originating conversation, and requires one matching terminal title. This adapter depends on Codex's local runtime interface and may need updates as Codex changes. It refuses missing or ambiguous matches; use a verified destination instead. A shared daemon's `ITERM_SESSION_ID` may belong to another terminal and is not a fallback.

For a desktop-originated request without a terminal, use `--desktop` or a recorded destination. Completion reporting stays with the caller's workflow; terminal creation and grouping are the only outcomes this plugin confirms.
