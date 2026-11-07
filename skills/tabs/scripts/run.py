"""Consume a private launch payload and replace this process with its command."""

import json
import os
from pathlib import Path
import sys


def main(payload_path):
    path = Path(payload_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    finally:
        path.unlink(missing_ok=True)
    os.chdir(payload["cwd"])
    os.execvp(payload["argv"][0], payload["argv"])


if __name__ == "__main__":
    main(sys.argv[1])
