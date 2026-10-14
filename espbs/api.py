"""Loopback HTTP API and dashboard for persistent collection jobs."""

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from .archive import export_batch, file_hash, verify_archive
from .jobs import Job
from .storage import Batch


def archive_info(root, job_id):
    path = Path(root) / 'exports' / (job_id + '.zip')
    if not path.is_file():
        return {'ready': False}
    batch = Batch(root, job_id).info()
    return {'ready': True, 'filename': path.name, 'size': path.stat().st_size,
            'sha256': batch['archive_sha256'] or file_hash(path),
            'record_count': batch['record_count']}


def job_info(root, job):
    return {**job.reconcile(), 'archive': archive_info(root, job.id)}


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
        if length > 16 * 1024:
            raise ValueError('Request body is too large')
        return json.loads(self.rfile.read(length) or b'{}')

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
            if self.path in ('/', '/index.html'):
                return self.send_asset('index.html', 'text/html; charset=utf-8')
            if self.path == '/app.css':
                return self.send_asset('app.css', 'text/css; charset=utf-8')
            if self.path == '/app.js':
                return self.send_asset('app.js', 'text/javascript; charset=utf-8')
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
                value = {'products': items, 'next_cursor': items[-1]['cursor'] if items else after}
            elif len(parts) == 4 and parts[3] == 'archive':
                path = self.server.root / 'exports' / (job.id + '.zip')
                if not path.is_file():
                    raise FileNotFoundError('Archive is not prepared')
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
            parts, _, job = self.route()
            if len(parts) == 2:
                payload = self.body()
                if payload.get('source', 'eltex') != 'eltex':
                    raise ValueError('Only the eltex source is supported')
                job = Job.create(self.server.root, int(payload.get('limit', 3)))
                launch_worker(self.server.root, job.id)
                return self.send_json(202, job.info())
            if len(parts) != 4 or parts[3] not in ('stop', 'resume', 'archive'):
                raise FileNotFoundError('Route not found')
            if parts[3] == 'archive':
                if job.reconcile()['state'] != 'COMPLETED':
                    raise ValueError('Only a completed job can be archived')
                export_batch(Batch(self.server.root, job.id), self.server.root / 'exports')
                return self.send_json(201, archive_info(self.server.root, job.id))
            if parts[3] == 'stop':
                job.stop()
            else:
                state = job.reconcile()['state']
                if state not in ('STOPPED', 'FAILED', 'READY'):
                    raise ValueError('Job cannot be resumed from state ' + state)
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
