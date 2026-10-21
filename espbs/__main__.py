"""Run with python -m espbs. Commands print JSON suitable for a future UI/API."""

import argparse
import json
import sys
import signal
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
    export.add_argument("--include-files", action="store_true", help="Embed bounded PDF/image files and a per-reference report")
    verify = commands.add_parser("verify", help="Verify a downloaded archive without a database")
    verify.add_argument("file", type=Path)
    verify.add_argument('--receipt', type=Path, help='Save a verification report for the server')
    collect = commands.add_parser('collect', help='Collect a bounded Eltex batch')
    collect.add_argument('source', choices=['eltex', 'olnisa'])
    collect.add_argument('--limit', type=int, default=3)
    collect.add_argument('--start-url', default='')
    collect.add_argument('--enrichment', choices=['none', 'eltex'])
    commands.add_parser('runs')
    catalog = commands.add_parser('catalog', help='Read latest source records with stable IDs')
    catalog.add_argument('--after', default='')
    catalog.add_argument('--limit', type=int, default=50)
    commands.add_parser('traffic', help='Read shared domain restrictions')
    serve = commands.add_parser('serve', help='Run the local management API and dashboard')
    serve.add_argument('--host', default='127.0.0.1')
    serve.add_argument('--port', type=int, default=8765)
    worker = commands.add_parser('worker', help=argparse.SUPPRESS)
    worker.add_argument('job_id')
    archive_worker = commands.add_parser('archive-worker', help=argparse.SUPPRESS)
    archive_worker.add_argument('batch_id')
    queue_worker = commands.add_parser('archive-queue-worker', help=argparse.SUPPRESS)
    queue_worker.add_argument('job_id')
    for name in ('resume', 'stop', 'run-status', 'events'):
        command = commands.add_parser(name)
        command.add_argument('job_id')
    args = parser.parse_args()
    try:
        if args.command == 'archive-queue-worker':
            from .archive_queue import run
            requested = {'stop': False}
            previous = signal.signal(signal.SIGTERM, lambda *_: requested.update(stop=True))
            try:
                result = run(args.data_dir, args.job_id, lambda: requested['stop'])
            finally:
                signal.signal(signal.SIGTERM, previous)
        elif args.command == 'archive-worker':
            from .export_tasks import run
            result = run(args.data_dir, args.batch_id)
        elif args.command == 'catalog':
            from .catalog import Catalog
            result = Catalog(args.data_dir).products(args.after, args.limit)
        elif args.command == 'traffic':
            from .traffic import Traffic
            result = Traffic(args.data_dir).status()
        elif args.command == 'serve':
            from .api import serve
            serve(args.data_dir, args.host, args.port)
            return 0
        elif args.command in ('collect', 'resume', 'stop', 'run-status', 'events', 'runs', 'worker'):
            from .jobs import Job
            if args.command == 'runs':
                result = [Job(args.data_dir, p.stem).info() for p in
                          sorted((Path(args.data_dir) / 'jobs').glob('*.sqlite3'))]
            else:
                job = Job.create(args.data_dir, args.limit, args.source, args.start_url, args.enrichment) if args.command == 'collect' else Job(args.data_dir, args.job_id)
                if args.command in ('collect', 'resume', 'worker'):
                    previous = signal.signal(signal.SIGTERM, lambda *_: job.stop())
                    try:
                        result = job.run(callback=lambda event: print(json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True))
                    finally:
                        signal.signal(signal.SIGTERM, previous)
                elif args.command == 'events':
                    result = job.events()
                else:
                    if args.command == 'stop':
                        job.stop()
                    result = job.info()
        elif args.command == "new":
            result = Batch.create(args.data_dir).info()
        elif args.command == "list":
            result = [Batch(args.data_dir, path.stem).info()
                      for path in sorted((Path(args.data_dir) / "batches").glob("*.sqlite3"))]
        elif args.command == "verify":
            result = verify_archive(args.file)
            if args.receipt:
                with args.receipt.open('x', encoding='utf-8') as stream:
                    json.dump(result, stream, ensure_ascii=False, indent=2)
        else:
            batch = Batch(args.data_dir, args.batch_id)
            if args.command == "status":
                result = batch.info()
            elif args.command == "export":
                result = {"archive": str(export_batch(batch, args.output, args.include_files)), **batch.info()}
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
        return 1 if isinstance(result, dict) and result.get('state') == 'FAILED' else 0
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
