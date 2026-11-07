"""Resolve terminal origins without trusting a shared daemon's environment."""

import os


def resolve_origin(session_id=None, desktop=False, *, codex=False, env=None):
    if session_id:
        return session_id, None
    if desktop:
        return None, None
    env = os.environ if env is None else env
    thread_id = env.get("CODEX_THREAD_ID") or env.get("CODEX_SESSION_ID")
    if codex:
        if not thread_id:
            raise RuntimeError("Codex origin lookup needs CODEX_THREAD_ID or CODEX_SESSION_ID; use a verified --origin-session")
        from codex_origin import codex_origin_name
        try:
            return None, codex_origin_name(thread_id)
        except Exception as error:
            raise RuntimeError(f"Codex origin lookup failed: {error}; use a verified --origin-session, "
                               "or --desktop only without an originating terminal") from error
    if thread_id:
        raise RuntimeError("a Codex daemon may have a stale terminal ID; use --codex-origin or a verified destination")
    identity = env.get("ITERM_SESSION_ID")
    if not identity:
        raise RuntimeError("no originating terminal; select --desktop or an explicit destination")
    return identity, None


async def match_origin(app, name):
    matches = []
    for window in app.terminal_windows:
        for tab in window.tabs:
            for session in tab.sessions:
                title = await session.async_get_variable("terminalWindowName")
                # Match the native thread title, ignoring its project suffix.
                if isinstance(title, str) and (title == name or title.rpartition(" | ")[0] == name):
                    matches.append(session.session_id)
    if len(matches) != 1:
        raise RuntimeError(f"expected one iTerm session for {name!r}, found {len(matches)}; "
                           "use --origin-session, or --desktop without an originating terminal")
    return matches[0]
