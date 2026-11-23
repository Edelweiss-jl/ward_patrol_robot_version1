"""Real MQTT acceptance smoke. Run from the repository root."""
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from ward_patrol.runtime.core import Runtime
from ward_patrol.runtime.mqtt import SamplingLink


def main():
    output=Path('outputs/stage1_acceptance')
    output.mkdir(parents=True,exist_ok=True)
    processes=[]
    handles=[]
    core=link=None
    try:
        for name,module in [('broker','ward_patrol.runtime.broker'),('service','ward_patrol.runtime.mqtt')]:
            handle=(output/(name+'.log')).open('w',encoding='utf-8')
            handles.append(handle)
            args = ['--cache',str(output/'samples.jsonl')] if name == 'service' else []
            processes.append(subprocess.Popen([sys.executable,'-u','-m',module,*args],stdout=handle,stderr=handle))
            time.sleep(2)
            assert processes[-1].poll() is None, name+' failed to start'
        core=Runtime(output=output/'runs')
        occupied = dict(bed_status='occupied', patient=dict(age=68, diagnosis='hypertension'))
        core.bed_info['N1-1'] = occupied
        link=SamplingLink(core)
        core.submit(dict(action='create_task',bed='N1-1'))
        deadline=time.monotonic()+30
        while not core.outbox and time.monotonic()<deadline:
            core.advance()
        assert core.outbox
        request=dict(core.outbox[0])
        core.submit(dict(action='pause'))
        core.advance()
        frozen=core.elapsed
        link.flush()
        time.sleep(.5)
        for _ in range(5): core.advance()
        assert core.elapsed==frozen
        assert core.tasks[0].status=='assigned'
        core.submit(dict(action='resume'))
        for _ in range(100):
            core.advance()
            if core.tasks[0].status=='completed': break
            time.sleep(.01)
        assert core.tasks[0].status=='completed'
        result=core.samples[request['sample_id']]['result']
        link.bus.publish(link.config['topics']['arrival'],request,qos=1)
        link.bus.publish(link.config['topics']['status'],result,qos=1)
        time.sleep(.5)
        core.advance()
        assert sum(e['event']=='task_completed' for e in core.events)==1
        assert sum(e['event']=='receipt_duplicate' for e in core.events)>=2
        sequence=[e['event'] for e in core.events if e['event'] in ('task_arrived','service_started','vitals_received','task_completed')]
        assert sequence==['task_arrived','service_started','vitals_received','task_completed'], sequence
        run=str(core.directory)
        cli_output = core.directory/'cli-runs'
        cli_output.mkdir()
        (cli_output/'beds.json').write_text(json.dumps({'N1-1':occupied,'S3-2':occupied}), encoding='utf-8')
        web_workspace = core.directory/'web'
        link.bus.close()
        link=None
        core.close()
        core=None
        cli=subprocess.run([sys.executable,'-m','ward_patrol.runtime.cli','--beds','N1-1','S3-2',
                            '--output',str(cli_output),'--timeout','30'],capture_output=True,text=True,timeout=40)
        (output/'cli.log').write_text(cli.stdout+cli.stderr,encoding='utf-8')
        assert cli.returncode==0,cli.stderr
        cli_run=next(Path(line.strip()) for line in cli.stdout.splitlines() if line.strip().startswith('outputs'))
        cli_events=[json.loads(line) for line in (cli_run/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        cli_sequences={}
        for event in cli_events:
            if event['event'] in sequence:
                cli_sequences.setdefault(event['task_id'],[]).append(event['event'])
        assert len(cli_sequences)==2 and all(events==sequence for events in cli_sequences.values()),cli_sequences
        handle=(output/'web.log').open('w',encoding='utf-8')
        handles.append(handle)
        processes.append(subprocess.Popen([sys.executable,'-u','-m','ward_patrol_web.server','--port','8011',
                                           '--workspace',str(web_workspace)],stdout=handle,stderr=handle))
        time.sleep(3)
        def get(path):
            return urllib.request.urlopen('http://127.0.0.1:8011'+path,timeout=5)
        for path in ('/','/api/layout','/api/state','/api/csv/events'):
            with get(path) as response:
                assert response.status==200
                response.read()
        with get('/api/stream') as response:
            assert response.readline().startswith(b'data:')
        def post(command):
            request=urllib.request.Request('http://127.0.0.1:8011/api/cmd',data=json.dumps(command).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=5) as response:
                assert response.status==202
        def step():
            with get('/api/state') as response:
                return json.load(response)['step']
        assert step()==0
        time.sleep(.2)
        assert step()==0
        post(dict(action='resume'))
        rates=[]
        for speed in (1,2):
            post(dict(action='set_speed',speed=speed))
            time.sleep(.2)
            start=step()
            time.sleep(1)
            rates.append(step()-start)
        assert 1.6 < rates[1]/rates[0] < 2.4,rates
        post(dict(action='set_speed',speed=4))
        post(dict(action='update_bed',bed='N1-1',fields=occupied))
        post(dict(action='create_task',bed='N1-1'))
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            with get('/api/state') as response:
                state=json.load(response)
            if state.get('tasks') and state['tasks'][0]['status']=='completed':break
            time.sleep(.2)
        else:raise AssertionError('Web task incomplete')
        assert any(event['event']=='vitals_received' for event in state['events'])
        (output/'result.json').write_text(json.dumps(dict(passed=True,core_run=run,web_run=state['run_id'],sequence=sequence,steps_per_second=rates,cli_run=str(cli_run),cli_sequences=cli_sequences),indent=2),encoding='utf-8')
        print('PASS',output/'result.json')
    finally:
        if link:link.bus.close()
        if core:core.close()
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        for handle in handles:handle.close()

if __name__=='__main__':main()
