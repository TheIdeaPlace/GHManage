"""Write _relay_config.py, the bug-report relay's address and GHManage's key,
for a release build. Help ▸ Report a Bug sends reports with them (bugreport.py).

Run by the release workflow with APPKIT_RELAY_URL (a repository variable) and
APPKIT_RELAY_KEY (a repository secret) in the environment. A release without
them would ship a Report a Bug that can only fall back to GitHub's page, so
either one missing fails the build. The file is gitignored: no key is ever
committed, and a build from source has none.

    python scripts/write_relay_config.py [output path]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def render(url: str, key: str) -> str:
    return (
        "# Written by scripts/write_relay_config.py for a release build. Not committed.\n"
        f"RELAY_URL = {url!r}\n"
        f"RELAY_KEY = {key!r}\n"
    )


def main(argv: list[str]) -> int:
    url = os.environ.get("APPKIT_RELAY_URL", "").strip()
    key = os.environ.get("APPKIT_RELAY_KEY", "").strip()
    missing = [name for name, value in (("APPKIT_RELAY_URL", url), ("APPKIT_RELAY_KEY", key))
               if not value]
    if missing:
        print(f"ERROR: {' and '.join(missing)} not set; a release needs both for "
              "Report a Bug to send reports.", file=sys.stderr)
        return 1
    if not url.startswith("https://"):
        print("ERROR: APPKIT_RELAY_URL must be an https:// address.", file=sys.stderr)
        return 1
    out = Path(argv[1]) if len(argv) > 1 else ROOT / "_relay_config.py"
    out.write_text(render(url, key), encoding="utf-8")
    print(f"Wrote {out.name} for {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
