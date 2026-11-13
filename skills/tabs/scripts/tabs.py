#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["iterm2==2.30", "websockets==15.0.1"]
# ///
"""Inspect iTerm2 destinations, open grouped background tabs, or close an explicit tab."""

import argparse
import json
from pathlib import Path
import sys
import tempfile
import uuid

from origin import resolve_origin
from terminal import close_tab, launch_iterm, list_destinations, ungroup_tab


def launch_command(payload_path):
    # iTerm interprets backslash escapes even inside single quotes.
    args = ["/bin/zsh", "-lic", 'exec "$@"', "iterm2",
            sys.executable, str(Path(__file__).with_name("run.py")), str(payload_path)]
    return " ".join('"' + arg.replace("\\", "\\\\").replace('"', '\\"') + '"' for arg in args)


def dispatch(argv, cwd, *, launcher=launch_iterm, **destination):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="iterm2-launch-",
                                     suffix=".json", delete=False) as payload:
        json.dump({"argv": argv, "cwd": str(cwd)}, payload)
    path = Path(payload.name)
    try:
        result = launcher(launch_command(path), **destination)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    if result["launch"] == "uncertain":
        result["payload_file"] = str(path)
    return result


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("list", help="read window, group, tab, and session IDs and names")
    closing = commands.add_parser("close", help="close one explicit tab, including all its split panes")
    closing.add_argument("--tab-id", required=True, help="verified tab ID from list or an open result")
    closing.add_argument("--force", action="store_true", help="bypass iTerm's close confirmation")
    closing.add_argument("--dry-run", action="store_true", help="validate input without connecting to iTerm")
    ungrouping = commands.add_parser("ungroup", help="dissolve a singleton group, keeping its tab open")
    ungrouping.add_argument("--tab-id", required=True, help="verified tab ID to preserve")
    ungrouping.add_argument("--group-id", required=True, help="recorded group ID containing only this tab")
    ungrouping.add_argument("--dry-run", action="store_true", help="validate input without connecting to iTerm")
    opening = commands.add_parser("open", help="open one new background tab")
    opening.add_argument("--cwd", type=Path, default=Path.cwd())
    opening.add_argument("--title", help="initial terminal title; does not name an agent's conversation")
    opening.add_argument("--append-file", type=Path, help="append this UTF-8 text as one final command argument")
    opening.add_argument("--request-id", help="correlation ID only; does not deduplicate launches")
    grouping = opening.add_mutually_exclusive_group()
    grouping.add_argument("--group", help="initial group name; existing origin group wins")
    grouping.add_argument("--new-group", help="new receiver group, leaving the origin's group unchanged")
    origin = opening.add_mutually_exclusive_group()
    origin.add_argument("--origin-session", help="verified originating iTerm session ID")
    origin.add_argument("--group-id", help="existing group ID; never creates a replacement")
    origin.add_argument("--window-id", help="existing window ID")
    origin.add_argument("--desktop", action="store_true", help="no originating terminal; use the current window")
    origin.add_argument("--codex-origin", action="store_true", help="opt into local Codex thread-title origin lookup")
    opening.add_argument("--dry-run", action="store_true", help="validate input without connecting to iTerm")
    opening.add_argument("command", nargs=argparse.REMAINDER, help="command and arguments after --; defaults to login zsh")
    args = parser.parse_args(argv)
    if args.operation in ("close", "ungroup"):
        if not args.tab_id.strip() or any(ord(c) < 32 or ord(c) == 127 for c in args.tab_id):
            parser.error("tab ID must be nonempty and contain no control characters")
        if args.operation == "ungroup" and (not args.group_id.strip() or
                any(ord(c) < 32 or ord(c) == 127 for c in args.group_id)):
            parser.error("group ID must be nonempty and contain no control characters")
        if not args.dry_run and sys.platform != "darwin":
            parser.error("iTerm2 requires macOS")
        return args
    if args.operation == "list":
        if sys.platform != "darwin":
            parser.error("iTerm2 requires macOS")
        return args
    if args.group_id is not None and (args.group is not None or args.new_group is not None):
        parser.error("--group-id cannot be combined with --group or --new-group")
    for name in ("title", "request_id", "group", "new_group", "origin_session", "group_id", "window_id"):
        value = getattr(args, name)
        if value is not None and (not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            parser.error(f"{name.replace('_', ' ')} must be nonempty and contain no control characters")
    args.command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if args.append_file is not None and not args.command:
        parser.error("--append-file requires an explicit command after --")
    if not args.command:
        args.command = ["/bin/zsh", "-l"]
    if not args.command[0].strip():
        parser.error("command executable must be nonempty")
    if args.append_file is not None:
        args.command.append(args.append_file.expanduser().read_text(encoding="utf-8"))
    if any("\0" in arg for arg in args.command):
        parser.error("command arguments cannot contain NUL characters")
    args.cwd = args.cwd.expanduser().resolve(strict=True)
    if not args.cwd.is_dir():
        parser.error(f"not a directory: {args.cwd}")
    args.request_id = args.request_id or str(uuid.uuid4())
    if not args.dry_run and sys.platform != "darwin":
        parser.error("iTerm2 requires macOS")
    return args


def main(argv=None):
    try:
        args = parse_args(argv)
        if args.operation == "list":
            print(json.dumps(list_destinations()))
            return 0
        if args.operation == "ungroup":
            result = ({"ungroup": "dry-run", "tab_id": args.tab_id, "group_id": args.group_id,
                       "destination": "unverified"}
                      if args.dry_run else ungroup_tab(args.tab_id, args.group_id))
            print(json.dumps(result))
            if "warning" in result:
                print(f"iterm2: {result['ungroup']}: {result['warning']}", file=sys.stderr)
            return 3 if result["ungroup"] == "uncertain" else 0
        if args.operation == "close":
            result = ({"close": "dry-run", "tab_id": args.tab_id, "destination": "unverified"}
                      if args.dry_run else close_tab(args.tab_id, force=args.force))
            print(json.dumps(result))
            if "warning" in result:
                print(f"iterm2: {result['close']}: {result['warning']}", file=sys.stderr)
            return 3 if result["close"] == "uncertain" else 0
        if args.dry_run:
            result = {"launch": "dry-run", "destination": "unverified"}
        else:
            origin_id, origin_name = ((None, None) if args.group_id or args.window_id else
                                      resolve_origin(args.origin_session, args.desktop, codex=args.codex_origin))
            result = dispatch(args.command, args.cwd,
                              group_name=args.new_group or args.group, group_id=args.group_id,
                              window_id=args.window_id, origin_id=origin_id, origin_name=origin_name,
                              new_group=args.new_group is not None, title=args.title)
        result.update(request_id=args.request_id, cwd=str(args.cwd))
        if args.title is not None:
            result["requested_title"] = args.title
        print(json.dumps(result))
        if "warning" in result:
            print(f"iterm2: {result['launch']}: {result['warning']}", file=sys.stderr)
        return 3 if result["launch"] == "uncertain" else 0
    except Exception as error:
        print(f"iterm2: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
