#!/usr/bin/env python3
"""Read RSS/Atom sources from sources.txt and print feed items as JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from roozvan.feeds import collect_items


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert RSS/Atom feed items to a JSON array.")
    parser.add_argument("--sources", default="sources.txt", help="File containing RSS/Atom URLs or paths, one per line.")
    parser.add_argument("--timeout", type=int, default=20, help="Network timeout in seconds.")
    args = parser.parse_args()

    items = collect_items(Path(args.sources), args.timeout)
    print(json.dumps(items, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
