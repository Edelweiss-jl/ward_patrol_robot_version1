"""HTTP/SSE adapter. Simulation state belongs to Runtime on its worker thread."""
import argparse
import csv
from dataclasses import asdict
import io
import json
from pathlib import Path
import threading
import time
from queue import Queue, Empty
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from ward_patrol.runtime.core import Runtime, DT
from ward_patrol.runtime.editable import EditableRuntime
from ward_patrol_web.workspace import TaskBedConflict, VacantTaskBeds, Workspace
from ward_patrol_web.census import OccupancyConflict, service_beds
from ward_patrol.maps.geometry import legacy_map
from ward_patrol.runtime.mqtt import SamplingLink


class SimRunner(threading.Thread):
    def __init__(self, mqtt=True, gui=False, workspace=None):
        super().__init__(daemon=True)
        self.mqtt = mqtt
        self.gui = gui
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.state = {}
        self.error = None
        self.incoming = Queue()
        self.workspace = workspace

    def bind_census(self, core, document):
        if self.workspace:
            core.bed_census = self.workspace.census
            core.bed_locations = service_beds(document)

    def run(self):
        core = link = None
        try:
            output = self.workspace.root/'runs' if self.workspace else 'outputs/runs'
            core = Runtime(output=output, gui=self.gui, local_sampling=not self.mqtt)
            self.bind_census(core, legacy_map('corridor'))
            core.started = False
            self.core = core
            ward = core.ward
            self.layout = dict(hx=ward.hx, hy=ward.hy, boxes=[asdict(b) for b in ward.boxes], stops=ward.stops)
            link = SamplingLink(core) if self.mqtt else None
            self.ready.set()
            deadline = time.monotonic()
            while not self.stop_event.is_set():
                while True:
                    try:
                        command = self.incoming.get_nowait()
                    except Empty:
                        break
                    if command.get('action') == 'replace_run':
                        if link:
                            link.bus.close()
                            link = None
                        if core is not None:
                            core.close()
                        core = EditableRuntime(**command['setup'], output=output, gui=self.gui, local_sampling=not self.mqtt)
                        self.bind_census(core, core.document)
                        core.started = False
                        self.core = core
                        link = SamplingLink(core) if self.mqtt else None
                    elif core is not None:
                        core.submit(command)
                        if command.get('action') == 'end_run':
                            break
                if core is None:
                    self.stop_event.wait(DT)
                    deadline = time.monotonic()
                    continue
                if self.gui:
                    import pybullet as bullet
                    keys = bullet.getKeyboardEvents()
                    if keys.get(32,0) & bullet.KEY_WAS_TRIGGERED:
                        core.submit(dict(action='resume' if core.paused or not core.started else 'pause'))
                core.advance()
                if link and not core.ended:
                    link.flush()
                snapshot = core.snapshot()
                if core.ended:
                    if link:
                        link.bus.close()
                        link = None
                    core.close()
                    core = self.core = None
                with self.lock:
                    self.state = snapshot
                    self.state['mqtt'] = bool(link and link.bus.client.is_connected())
                if core is None:
                    continue
                if self.workspace and core.started and not core.paused and core.step % 30 == 0:
                    self.workspace.submit_queued_editor_tasks(self.state, core.submit)
                deadline += DT / core.speed
                delay = deadline-time.monotonic()
                if delay > 0:
                    self.stop_event.wait(delay)
                elif delay < -.5:
                    deadline = time.monotonic()
        except Exception as exc:
            self.error = str(exc)
            self.ready.set()
        finally:
            if link:
                link.bus.close()
            if core:
                core.close()

    def submit(self, command):
        command = dict(command)
        command.setdefault('command_id', uuid.uuid4().hex)
        self.incoming.put(command)
        return command['command_id']

    def snapshot(self):
        with self.lock:
            return dict(self.state, error=self.error)


class Handler(BaseHTTPRequestHandler):
    def reply(self, data, content_type='application/json; charset=utf-8', status=200):
        body = json.dumps(data,ensure_ascii=False).encode() if isinstance(data,(dict,list)) else data
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        path = self.path.partition('?')[0]
        if path in ('/api/editor/tasks', '/api/maps', '/api/maps/manage', '/api/archives/tasks',
                    '/api/state', '/api/replay', '/api/bed-census', '/api/bed-census/history') or path.startswith('/api/csv/'):
            self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            url = urlparse(self.path)
            if url.path == '/api/bed-census/history':
                query = parse_qs(url.query)
                self.reply(self.server.workspace.census.history(
                    query.get('key', [''])[0], query.get('revision', [''])[0]))
                return
            if url.path == '/api/bed-census':
                query = parse_qs(url.query)
                workspace = self.server.workspace
                document = workspace.census_map(query.get('map_id', [''])[0], int(query.get('version', ['0'])[0]))
                self.reply(workspace.census.list(document, summary=query.get('summary') == ['1']))
                return
            if url.path == '/api/run-elevators':
                run_id = parse_qs(url.query).get('run_id', [''])[0]
                if len(run_id)!=32 or any(char not in '0123456789abcdef' for char in run_id):
                    raise ValueError('运行编号无效')
                path = self.server.workspace.root/'runs'/run_id/'elevators.jsonl'
                self.reply(path.read_bytes(), 'application/x-ndjson; charset=utf-8')
                return
            if url.path == '/api/editor/tasks':
                query = parse_qs(url.query)
                map_id = query.get('map_id', [''])[0]
                version = int(query.get('map_version', ['0'])[0]) or None
                self.reply(self.server.workspace.editor_tasks(map_id, self.server.runner, version))
                return
            data = self.server.workspace.get(self.path)
            if data is not None:
                self.reply(data)
                return
        except OccupancyConflict as exc:
            self.reply({'error': str(exc)}, status=409)
            return
        except (ValueError, KeyError, OSError) as exc:
            self.reply({'error': str(exc)}, status=400)
            return
        pages = {'/':'editor.html','/editor':'editor.html','/monitor':'index.html','/beds':'beds.html'}
        if url.path in pages or url.path in ('/editor.js', '/furnishing.js', '/elevators.js', '/console.css', '/workbench.js', '/workbench.css', '/vitals.js', '/beds.js', '/beds.css', '/bed-map.js'):
            name = pages.get(url.path,url.path[1:])
            mime = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css'}[Path(name).suffix] + '; charset=utf-8'
            self.reply(Path(__file__).with_name('static').joinpath(name).read_bytes(), mime)
        elif self.path == '/api/layout':
            self.reply(self.server.runner.layout)
        elif self.path in ('/api/state','/api/beds'):
            state = self.server.runner.snapshot()
            self.reply(self.server.workspace.visible_snapshot(state) if self.path.endswith('state') else state.get('beds',{}))
        elif self.path == '/api/stream':
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.send_header('Cache-Control','no-cache')
            self.end_headers()
            try:
                while not self.server.runner.stop_event.is_set():
                    state = self.server.workspace.visible_snapshot(self.server.runner.snapshot())
                    data=json.dumps(state,ensure_ascii=False)
                    self.wfile.write(('data: '+data+'\n\n').encode())
                    self.wfile.flush()
                    time.sleep(.1)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
        elif self.path.startswith('/api/csv/'):
            state = self.server.workspace.visible_snapshot(self.server.runner.snapshot())
            kind = self.path.rsplit('/',1)[-1]
            rows = state.get('tasks',[]) if kind=='summary' else state.get('events',[])
            if kind=='arrivals':
                rows=[row for row in rows if row['event']=='task_arrived']
            elif kind=='vitals':
                rows=[row for row in rows if row['event']=='vitals_received']
            fields=list(dict.fromkeys(key for row in rows for key in row)) or ['event_id','step','event']
            stream=io.StringIO()
            writer=csv.DictWriter(stream,fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            self.reply(stream.getvalue().encode('utf-8-sig'),'text/csv; charset=utf-8')
        else:
            self.reply({'error':'not found'},status=404)

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length > 16000000:
                raise ValueError('请求大小超过 16 MB')
            command = json.loads(self.rfile.read(length))
            if not isinstance(command, dict):
                raise ValueError('请求应为 JSON 对象')
            if self.path == '/api/bed-census':
                workspace = self.server.workspace
                document = workspace.census_map(command.get('map_id'), command.get('version'))
                self.reply(workspace.census.change(document, command))
                return
            if self.path == '/api/editor/tasks':
                action = command.get('action')
                if action == 'save':
                    self.reply(self.server.workspace.save_editor_task(command['record'], self.server.runner))
                elif action == 'delete':
                    self.reply(self.server.workspace.delete_editor_task(command, self.server.runner))
                elif action == 'permanent_delete':
                    self.reply(self.server.workspace.delete_editor_task(command, self.server.runner, permanent=True))
                elif action == 'publish':
                    result = self.server.workspace.publish_editor_tasks(command, self.server.runner)
                    self.reply(result, status=202)
                else:
                    raise ValueError('未知任务操作')
                return
            if self.path == '/api/run':
                setup = self.server.workspace.setup(command)
                identity = self.server.runner.submit(dict(action='replace_run', setup=setup))
                self.reply({'command_id': identity}, status=202)
                return
            data = self.server.workspace.post(self.path, command)
            if data is not None:
                self.reply(data)
                return
            if self.path not in ('/api/cmd','/api/beds'):
                self.reply({'error':'not found'},status=404)
                return
            if self.path=='/api/beds':
                command=dict(action='update_bed',bed=command['bed'],fields=command['fields'])
            if self.server.runner.snapshot().get('ended'):
                raise ValueError('本次巡查已结束，请重新准备巡查')
            command_id=self.server.runner.submit(command)
            self.reply({'command_id':command_id},status=202)
        except (TaskBedConflict, VacantTaskBeds) as exc:
            self.reply({'error': str(exc), 'conflicts': exc.conflicts}, status=409)
        except OccupancyConflict as exc:
            self.reply({'error': str(exc)}, status=409)
        except (ValueError,KeyError,TypeError) as exc:
            self.reply({'error':str(exc)},status=400)
        except OSError:
            self.reply({'error':'无法写入工作区，请检查存储状态后重试'},status=500)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--no-mqtt',action='store_true',help='在运行进程内模拟体征采样')
    parser.add_argument('--gui',action='store_true')
    parser.add_argument('--workspace',default='outputs',help='地图配置、任务和运行记录的目录')
    args=parser.parse_args()
    workspace=Workspace(args.workspace)
    runner=SimRunner(not args.no_mqtt,args.gui,workspace=workspace)
    runner.start()
    runner.ready.wait(15)
    if runner.error or not runner.ready.is_set():
        raise RuntimeError(runner.error or 'simulation startup timed out')
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server.daemon_threads=True
    server.runner=runner
    server.workspace=workspace
    print(f'http://127.0.0.1:{args.port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runner.stop_event.set()
        server.server_close()
        runner.join(5)

if __name__=='__main__':
    main()
