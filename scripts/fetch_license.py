"""Vendor the verbatim AGPL-3.0 text into LICENSE.

The repository ships LICENSE with the project's own copyright notice and an
explanation, but the full licence text has to be the canonical one, word for
word. This fetches it and splices it in, keeping the notice at the top.

    python scripts/fetch_license.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LICENSE = REPO_ROOT / "LICENSE"
SOURCE = "https://www.gnu.org/licenses/agpl-3.0.txt"

MARKER = "FULL LICENCE TEXT"
# A line the real text always contains, used to check we fetched a licence and
# not a captive-portal page or a proxy error.
SENTINEL = "GNU AFFERO GENERAL PUBLIC LICENSE"


def main() -> int:
    print(f"==> Fetching {SOURCE}", flush=True)
    try:
        with urllib.request.urlopen(SOURCE, timeout=30) as response:
            text = response.read().decode("utf-8")
    except Exception as failure:
        print(f"error: could not fetch the licence text: {failure}", file=sys.stderr)
        return 1

    if SENTINEL not in text:
        print("error: what came back does not look like the AGPL", file=sys.stderr)
        return 1

    existing = LICENSE.read_text(encoding="utf-8")
    head, separator, _ = existing.partition(MARKER)
    if not separator:
        print(
            f"error: LICENSE has no '{MARKER}' marker; it may already be complete.",
            file=sys.stderr,
        )
        return 1

    LICENSE.write_text(f"{head}{MARKER}\n\n{text}", encoding="utf-8")
    print(f"==> Wrote the full licence into {LICENSE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
