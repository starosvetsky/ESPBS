"""Run with python -m espbs. Commands print JSON suitable for a future UI/API."""

import argparse
import json
import sys
from pathlib import Path

from .archive import export_batch, verify_archive
from .storage import Batch


def main():
    parser = argparse.ArgumentParser(description="ESPBS collection batches and XML archives")
    parser.add_argument("--data-dir", default="data", help="Persistent server data directory")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("new", help="Create an empty collection batch")
    commands.add_parser("list", help="List persisted batches")
    status = commands.add_parser("status")
    status.add_argument("batch_id")
    ingest = commands.add_parser("ingest", help="Import JSONL records, committing each record")
    ingest.add_argument("batch_id")
    ingest.add_argument("file", type=Path)
    export = commands.add_parser("export", help="Seal a batch and build a verified ZIP")
    export.add_argument("batch_id")
    export.add_argument("--output", default="exports")
    verify = commands.add_parser("verify", help="Verify a downloaded archive without a database")
    verify.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "new":
            result = Batch.create(args.data_dir).info()
        elif args.command == "list":
            result = [Batch(args.data_dir, path.stem).info()
                      for path in sorted((Path(args.data_dir) / "batches").glob("*.sqlite3"))]
        elif args.command == "verify":
            result = verify_archive(args.file)
        else:
            batch = Batch(args.data_dir, args.batch_id)
            if args.command == "status":
                result = batch.info()
            elif args.command == "export":
                result = {"archive": str(export_batch(batch, args.output)), **batch.info()}
            else:
                counts = {"inserted": 0, "updated": 0, "unchanged": 0}
                with args.file.open("rb") as stream:
                    line_number = 0
                    while line := stream.readline(4 * 1024 * 1024 + 1):
                        line_number += 1
                        try:
                            if len(line) > 4 * 1024 * 1024:
                                raise ValueError("JSONL record exceeds 4 MiB")
                            if line.strip():
                                counts[batch.add(json.loads(line))] += 1
                        except Exception as error:
                            raise ValueError(f"Line {line_number}: {error}; earlier records remain saved") from error
                result = {**batch.info(), "import": counts}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
