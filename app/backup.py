"""Export or restore the private durable change log."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from app.change_log import ChangeLog


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Back up or restore Cat Colony Watch live changes and photos."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--export", type=Path, metavar="FILE")
    group.add_argument("--restore", type=Path, metavar="FILE")
    parser.add_argument(
        "--confirm-replace",
        action="store_true",
        help="required for restore; replaces the complete current live change log",
    )
    args = parser.parse_args()
    load_dotenv()
    log = ChangeLog(local_path=os.getenv("CCW_LOCAL_CHANGE_LOG", "data/local_changes.json"))
    if args.export:
        bundle = log.export_bundle()
        args.export.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(args.export, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump(bundle, output, separators=(",", ":"))
            output.write("\n")
        print(f"Exported {len(bundle['changes'])} changes to {args.export}")
        return
    if not args.confirm_replace:
        parser.error("--restore requires --confirm-replace")
    bundle = json.loads(args.restore.read_text())
    log.restore_bundle(bundle, replace=True)
    print(f"Restored {len(bundle['changes'])} changes from {args.restore}")


if __name__ == "__main__":
    main()
