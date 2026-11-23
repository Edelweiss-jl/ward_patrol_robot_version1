"""Measure cold dispatch and complete look-ahead allocation without MQTT or GUI."""
import argparse
import json
from tempfile import TemporaryDirectory
import time

from ward_patrol.maps.geometry import DEFAULT_MODELS, blank_map
from ward_patrol.maps.templates import hospital_templates
from ward_patrol.runtime.editable import EditableRuntime


def scenario(visits, robots, layout):
    document = next(hospital_templates())
    if layout=='distinct':
        document = blank_map('独立床位性能场景')
        floor = document['floors'][0]
        floor['objects'] = [dict(id='wall',kind='wall',x=0,y=0,width=20,height=.2),
                            dict(id='door',kind='door',wall_id='wall',x=0,y=0,width=3,height=.2)]
        for i,x in enumerate((-4,-2,2,4)):
            floor['objects'].append(dict(id=f'P{i}',kind='parking',x=x,y=-3,width=.2,height=.2))
        for i in range(visits):
            floor['objects'].append(dict(id=f'S{i}',kind='service',x=-4+8*(i%16)/15,
                y=2+3*(i//16)/max(1,(visits-1)//16),width=.1,height=.1))
    document['version'] = 1
    floor = document['floors'][0]
    parking = [o for o in floor['objects'] if o['kind']=='parking'][:robots]
    beds = [o['id'] for o in floor['objects'] if o['kind']=='service']
    fleet = [dict(id=f'R{i+1}',model_id='small',floor_id=floor['id'],
                  pose=[spot['x'],spot['y'],0],parking_id=spot['id']) for i,spot in enumerate(parking)]
    return document,fleet,beds


def benchmark(visits, robots=4, layout='repeated'):
    document,fleet,beds = scenario(visits,robots,layout)
    with TemporaryDirectory() as output:
        core = EditableRuntime(document,DEFAULT_MODELS,fleet,output=output)
        try:
            started = time.perf_counter()
            for index in range(visits):
                core.add_task(beds[index%len(beds)],service='dwell',duration=1)
            submission = (time.perf_counter()-started)*1000
            started = time.perf_counter()
            core.dispatch()
            dispatch = (time.perf_counter()-started)*1000
            started = time.perf_counter()
            slices,largest = 0,0.
            while True:
                core.advance_planning()
                slices += 1
                largest = max(largest,core.planning_metrics['last_slice_ms'])
                if core.planning_metrics['status']=='ready':
                    break
            planning = (time.perf_counter()-started)*1000
            snapshot = core.planning_snapshot()
            return dict(layout=layout,visits=visits,distinct_beds=len(beds),robots=robots,
                submission_ms=round(submission,3),first_dispatch_ms=round(dispatch,3),
                remaining_plan_ms=round(planning,3),largest_slice_ms=largest,slices=slices,
                assigned=sum(t.status=='assigned' for t in core.tasks),
                planned=len(snapshot['dispatch_plan']),
                planned_elevator_rides=sum(item['elevator_rides'] for item in snapshot['dispatch_plan'].values()),
                planned_distance_m=round(sum(item['estimated_distance'] for item in snapshot['dispatch_plan'].values()),3),
                improvements=core.planning_metrics['improvements'],
                improvement_ms=core.planning_metrics['improvement_ms'],
                queues={key:len(value) for key,value in snapshot['robot_queues'].items()})
        finally:
            core.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--visits',type=int,default=200)
    parser.add_argument('--robots',type=int,choices=(1,2,4),default=4)
    parser.add_argument('--layout',choices=('repeated','distinct'),default='repeated')
    args = parser.parse_args()
    if not 1<=args.visits<=1000:
        parser.error('--visits must be between 1 and 1000')
    print(json.dumps(benchmark(args.visits,args.robots,args.layout),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
