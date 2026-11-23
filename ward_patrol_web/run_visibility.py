"""Remove deleted patrols from public run data without changing the running simulation."""


def _payload_id(event, key):
    payload = event.get('payload')
    value = payload.get(key) if isinstance(payload, dict) else None
    return value if isinstance(value, str) else None


def _event_task_deleted(event, patrol_ids, visit_ids):
    return (event.get('patrol_id') in patrol_ids or event.get('task_id') in visit_ids
            or _payload_id(event, 'task_id') in visit_ids)


def _sample_deleted(sample, visit_ids):
    return any(isinstance(part, dict) and part.get('task_id') in visit_ids
               for part in (sample.get('request'), sample.get('result')))


def _visible_plan(plan, visit_ids):
    remaining = {identity: visit for identity, visit in plan.items() if identity not in visit_ids}
    groups = {}
    for identity in sorted(remaining, key=lambda key: remaining[key].get('sequence', 0)):
        visit = remaining[identity]
        group = visit.get('group_id')
        if group in visit_ids:
            leader, count = groups.get(group, (identity, 0))
            groups[group] = leader, count + 1
            remaining[identity] = dict(visit, group_id=leader, group_position=count + 1)
    return remaining


def visible_run_data(snapshots, events, patrol_ids):
    if not patrol_ids:
        return snapshots, events

    # Visits accumulate in a run. The creation events also cover visits added after its last saved frame.
    specs = snapshots[-1].get('task_specs', {}) if snapshots else {}
    visit_ids = {identity for identity, spec in specs.items() if spec.get('patrol_id') in patrol_ids}
    for event in events:
        if event.get('patrol_id') in patrol_ids:
            visit_ids.update(event.get('visit_task_ids', []))
            if event.get('task_id'):
                visit_ids.add(event['task_id'])
    if not visit_ids:
        return snapshots, events

    samples = snapshots[-1].get('samples', {}) if snapshots else {}
    sample_ids = {identity for identity, sample in samples.items() if _sample_deleted(sample, visit_ids)}
    for event in events:
        if _event_task_deleted(event, patrol_ids, visit_ids):
            identity = event.get('sample_id') or _payload_id(event, 'sample_id')
            if identity:
                sample_ids.add(identity)

    def visible_event(event):
        return (not _event_task_deleted(event, patrol_ids, visit_ids)
                and event.get('sample_id') not in sample_ids
                and _payload_id(event, 'sample_id') not in sample_ids)

    remaining_events = [event for event in events if visible_event(event)]
    frames = []
    for snapshot in snapshots:
        frame = dict(snapshot)
        if 'tasks' in frame:
            frame['tasks'] = [task for task in frame['tasks'] if task['task_id'] not in visit_ids]
        for key in ('task_specs', 'wait_reasons', 'attempts'):
            if key in frame:
                frame[key] = {identity: value for identity, value in frame[key].items() if identity not in visit_ids}
        if 'dispatch_plan' in frame:
            frame['dispatch_plan'] = _visible_plan(frame['dispatch_plan'], visit_ids)
            if 'planning' in frame:
                frame['planning'] = dict(frame['planning'], planned=len(frame['dispatch_plan']))
        if 'robot_queues' in frame:
            frame['robot_queues'] = {identity: [visit for visit in queue if visit not in visit_ids]
                                     for identity, queue in frame['robot_queues'].items()}
        if 'robots' in frame:
            frame['robots'] = [dict(robot, task_id=None, path=[], status='idle')
                               if robot.get('task_id') in visit_ids else robot for robot in frame['robots']]
        if 'samples' in frame:
            frame['samples'] = {identity: sample for identity, sample in frame['samples'].items()
                                if identity not in sample_ids and not _sample_deleted(sample, visit_ids)}
        if 'events' in frame:
            frame['events'] = (remaining_events if frame['events'] is events else
                               [event for event in frame['events'] if visible_event(event)])
        frames.append(frame)
    return frames, remaining_events
