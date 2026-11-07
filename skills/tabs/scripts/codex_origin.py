"""Optional Codex local-daemon adapter; isolated from iTerm terminal mechanics."""

import json
import os
from pathlib import Path
import time


def codex_origin_name(thread_id):
    from websockets.sync.client import unix_connect

    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    with unix_connect(str(home / "app-server-control/app-server-control.sock"),
                      open_timeout=5, close_timeout=1, ping_interval=None) as socket:
        sequence = 0

        def call(method, params):
            nonlocal sequence
            sequence += 1
            socket.send(json.dumps({"id": sequence, "method": method, "params": params}))
            deadline = time.monotonic() + 5
            while True:
                response = json.loads(socket.recv(timeout=max(0.01, deadline - time.monotonic())))
                if response.get("id") == sequence:
                    if "error" in response:
                        raise RuntimeError(f"cannot identify originating Codex conversation: {response['error']}")
                    return response["result"]
                if time.monotonic() >= deadline:
                    raise TimeoutError("originating Codex conversation lookup timed out")

        call("initialize", {"clientInfo": {"name": "handoff", "version": "1"}})
        socket.send(json.dumps({"method": "initialized"}))
        visited = set()
        while thread_id not in visited:
            visited.add(thread_id)
            thread = call("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]
            if not thread.get("parentThreadId"):
                if not thread.get("name"):
                    raise RuntimeError("originating Codex conversation has no title; use --origin-session")
                return thread["name"]
            thread_id = thread["parentThreadId"]
        raise RuntimeError("originating Codex conversation has cyclic parents")
