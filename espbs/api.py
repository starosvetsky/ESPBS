"""Loopback HTTP API and dashboard for persistent collection jobs."""

import json
import os
import subprocess
import sys
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from .archive import export_batch, file_hash, verify_archive
from .jobs import Job, worker_lock
from .storage import Batch
from .disk import status as disk_status, require_space, MIB
from .retention import receipt, confirm_copy, cleanup


def archive_info(root, job_id):
    path = Path(root) / 'exports' / (job_id + '.zip')
    batch_object = Batch(root, job_id)
    if not path.is_file():
        from .export_tasks import status
        return {'ready': False, 'task': status(batch_object)}
    batch = batch_object.info()
    with zipfile.ZipFile(path) as archive:
        if archive.getinfo('manifest.json').file_size > 65536:
            raise ValueError('Manifest too large')
        manifest = json.loads(archive.read('manifest.json'))
    return {'ready': True, 'filename': path.name, 'size': path.stat().st_size,
            'sha256': batch['archive_sha256'] or file_hash(path),
            'record_count': batch['record_count'], 'attachments': manifest.get('attachments'),
            'attachment_summary': manifest.get('attachment_summary')}


def job_info(root, job):
    from .partitions import summary
    from .archive_queue import status as queue_status
    return {**job.reconcile(), 'archive': archive_info(root, job.id), 'retention': receipt(job),
            'archive_parts': summary(job), 'archive_queue': queue_status(job)}


def jobs(root):
    directory = Path(root) / 'jobs'
    return [job_info(root, Job(root, path.stem)) for path in
            sorted(directory.glob('*.sqlite3'), key=lambda p: p.stat().st_mtime, reverse=True)]


def launch_worker(root, job_id):
    command = [sys.executable, '-m', 'espbs', '--data-dir', str(Path(root).resolve()),
               'worker', job_id]
    kwargs = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL,
              'stderr': subprocess.DEVNULL, 'close_fds': True}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs['start_new_session'] = True
    subprocess.Popen(command, **kwargs)


class API(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, root):
        self.root = Path(root).resolve()
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, format, *args):
        pass

    def send_json(self, status, value):
        data = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def send_asset(self, name, content_type):
        data = (Path(__file__).with_name('web') / name).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path):
        path = Path(path)
        size = path.stat().st_size
        self.send_response(200)
        self.send_header('Content-Type', 'application/zip')
        self.send_header('Content-Disposition', f'attachment; filename="{path.name}"')
        self.send_header('Content-Length', str(size))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        with path.open('rb') as stream:
            while chunk := stream.read(64 * 1024):
                self.wfile.write(chunk)

    def body(self):
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 <= length <= 16 * 1024:
            raise ValueError('Request body is too large')
        value = json.loads(self.rfile.read(length) or b'{}')
        if not isinstance(value, dict):
            raise ValueError('Expected JSON object')
        return value

    def route(self):
        parsed = urlsplit(self.path)
        parts = [part for part in parsed.path.split('/') if part]
        query = parse_qs(parsed.query)
        if parts[:2] != ['api', 'jobs']:
            raise FileNotFoundError('Route not found')
        if len(parts) == 2:
            return parts, query, None
        return parts, query, Job(self.server.root, str(UUID(parts[2])))

    def do_GET(self):
        try:
            path = urlsplit(self.path).path
            if path in ('/inventory', '/inventory.html', '/inventory.js', '/inventory.css'):
                name = 'inventory.html' if path == '/inventory' else path[1:]
                mime = {'html': 'text/html', 'js': 'text/javascript', 'css': 'text/css'}
                return self.send_asset(name, mime[name.rsplit('.', 1)[1]] + '; charset=utf-8')
            if path == '/api/inventory/batches':
                from .inventory import batches
                rows = batches(self.server.root)
                return self.send_json(200, {'batches': rows, 'record_count': sum(x['record_count'] for x in rows)})
            if path == '/api/inventory/products':
                from .inventory import products
                query = parse_qs(urlsplit(self.path).query)
                return self.send_json(200, products(self.server.root,
                    query.get('batch', [''])[0], query.get('after', [''])[0],
                    query.get('q', [''])[0], int(query.get('limit', ['50'])[0])))
            if urlsplit(self.path).path == '/api/catalog':
                from .catalog import Catalog
                query = parse_qs(urlsplit(self.path).query)
                rows = Catalog(self.server.root).products(query.get('after', [''])[0], int(query.get('limit', ['50'])[0]))
                return self.send_json(200, {'products': rows, 'next_cursor': rows[-1]['id'] if rows else None})
            if self.path == '/api/traffic':
                from .traffic import Traffic
                return self.send_json(200, {'domains': Traffic(self.server.root).status()})
            if self.path == '/api/directory':
                from .directory import Directory
                directory = Directory(self.server.root)
                return self.send_json(200, {'manufacturers': directory.manufacturers(), 'mappings': directory.mappings()})
            if self.path == '/api/sources':
                from .sources import REGISTRY
                return self.send_json(200, {'sources': list(REGISTRY.values())})
            if self.path == '/api/storage':
                return self.send_json(200, disk_status(self.server.root))
            if self.path in ('/', '/index.html'):
                return self.send_asset('index.html', 'text/html; charset=utf-8')
            if self.path == '/app.css':
                return self.send_asset('app.css', 'text/css; charset=utf-8')
            if self.path == '/app.js':
                return self.send_asset('app.js', 'text/javascript; charset=utf-8')
            if self.path == '/catalog.js':
                return self.send_asset('catalog.js', 'text/javascript; charset=utf-8')
            if self.path == '/workbench.js':
                return self.send_asset('workbench.js', 'text/javascript; charset=utf-8')
            if self.path == '/favicon.svg':
                return self.send_asset('favicon.svg', 'image/svg+xml')
            parts, query, job = self.route()
            if len(parts) == 2:
                value = {'jobs': jobs(self.server.root)}
            elif len(parts) == 3:
                value = job_info(self.server.root, job)
            elif len(parts) == 4 and parts[3] == 'events':
                after = int(query.get('after', ['0'])[0])
                limit = int(query.get('limit', ['100'])[0])
                items = job.events(after, limit)
                value = {'events': items, 'next_cursor': items[-1]['seq'] if items else after}
            elif len(parts) == 4 and parts[3] == 'products':
                after = query.get('after', [''])[0]
                limit = int(query.get('limit', ['50'])[0])
                items = Batch(self.server.root, job.id).products(after, limit)
                cursor = items[-1]['cursor'] if items else after
                value = {'products': items, 'next_cursor': cursor,
                         'has_more': bool(items and Batch(self.server.root, job.id).products(cursor, 1))}
            elif len(parts) == 4 and parts[3] == 'archive':
                path = self.server.root / 'exports' / (job.id + '.zip')
                if not path.is_file():
                    raise FileNotFoundError('Archive is not prepared')
                batch = Batch(self.server.root, job.id)
                with worker_lock(batch.path.with_suffix('.maintenance.lock')):
                    verify_archive(path)
                    return self.send_file(path)
            else:
                raise FileNotFoundError('Route not found')
            self.send_json(200, value)
        except (ValueError, FileNotFoundError, json.JSONDecodeError) as error:
            self.send_json(404 if isinstance(error, FileNotFoundError) else 400,
                           {'error': str(error)})
        except Exception as error:
            self.send_json(500, {'error': str(error)})

    def do_POST(self):
        try:
            if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                raise ValueError('Content-Type must be application/json')
            if self.path in ('/api/probe', '/api/profiles', '/api/manufacturers', '/api/mappings'):
                from .directory import Directory, probe
                payload = self.body()
                directory = Directory(self.server.root)
                require_space(self.server.root, 256 * MIB)
                if self.path == '/api/probe':
                    value = probe(self.server.root, payload.get('url'), payload.get('selectors'))
                elif self.path == '/api/profiles':
                    value = directory.save_profile(payload.get('url'), payload.get('selectors', {}))
                elif self.path == '/api/manufacturers':
                    value = directory.save_manufacturer(payload)
                else:
                    value = directory.save_mapping(payload)
                return self.send_json(200, value)
            parts, _, job = self.route()
            if len(parts) == 2:
                payload = self.body()
                job = Job.create(self.server.root, payload.get('limit'),
                                 payload.get('source', 'eltex'), payload.get('start_url', ''),
                                 payload.get('enrichment'), payload.get('selectors'),
                                 payload.get('auto_enrich', True), payload.get('photo_policy', 'official'))
                launch_worker(self.server.root, job.id)
                return self.send_json(202, job.info())
            if len(parts) != 4 or parts[3] not in ('stop', 'resume', 'archive', 'confirm-copy', 'cleanup', 'enrich', 'archive-part', 'archive-queue-start', 'archive-queue-stop'):
                raise FileNotFoundError('Route not found')
            if parts[3] in ('archive-queue-start', 'archive-queue-stop'):
                from .archive_queue import start, stop
                self.body()
                value = start(job) if parts[3] == 'archive-queue-start' else stop(job)
                return self.send_json(202, value)
            if parts[3] == 'archive-part':
                from .partitions import create_next
                child = create_next(job, self.body().get('after', ''))
                return self.send_json(201, job_info(self.server.root, child))
            if parts[3] == 'enrich':
                child = Job.create_enrichment(job)
                launch_worker(self.server.root, child.id)
                return self.send_json(202, child.info())
            if parts[3] == 'confirm-copy':
                return self.send_json(200, confirm_copy(job, self.body()))
            if parts[3] == 'cleanup':
                return self.send_json(200, cleanup(job, self.body().get('confirmation')))
            if parts[3] == 'archive':
                payload = self.body()
                include_files = payload.get('include_files', False)
                if type(include_files) is not bool:
                    raise ValueError('include_files must be boolean')
                if receipt(job):
                    raise ValueError('Copy already confirmed; archive preparation disabled')
                if job.reconcile()['state'] != 'COMPLETED':
                    raise ValueError('Only a completed job can be archived')
                if include_files:
                    from .export_tasks import start
                    return self.send_json(202, {'ready': False, 'task': start(self.server.root, job.id)})
                from .export_tasks import status
                if status(Batch(self.server.root, job.id)).get('state') in ('QUEUED', 'RUNNING'):
                    raise ValueError('Подготовка архива с файлами уже выполняется')
                export_batch(Batch(self.server.root, job.id), self.server.root / 'exports')
                return self.send_json(201, archive_info(self.server.root, job.id))
            if parts[3] == 'stop':
                job.stop()
            else:
                state = job.reconcile()['state']
                if state not in ('STOPPED', 'FAILED', 'READY', 'PAUSED_DISK'):
                    raise ValueError('Job cannot be resumed from state ' + state)
                require_space(self.server.root, 256 * MIB)
                launch_worker(self.server.root, job.id)
            self.send_json(202, job_info(self.server.root, job))
        except (ValueError, FileNotFoundError, json.JSONDecodeError) as error:
            self.send_json(404 if isinstance(error, FileNotFoundError) else 400,
                           {'error': str(error)})
        except Exception as error:
            self.send_json(500, {'error': str(error)})


def serve(root='data', host='127.0.0.1', port=8765):
    if host not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('Remote binding requires authentication and TLS; use loopback for now')
    server = API((host, port), root)
    print(f'ESPBS dashboard: http://{host}:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

