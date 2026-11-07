# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Optional explicit operator workflow packaged with the Brain stack.

The ordinary publish API remains PR-only. This separate integration command
may normally merge an exact record PR only with --execute --yes and a fresh
committed managed route. No grants, installer or routing edits are performed.
"""
from . import managed
from .routing import project_root, refresh_publisher_route, require_managed_promotion_route, control_json, run

OPERATIONS = ('profile', 'publisher-route', 'status', 'validate', 'latest', 'export', 'pull', 'create', 'check-record', 'dump')

def dispatch(project_repo, operation, *, entry=None, output=None, record=None, execute=False, yes=False):
    if operation not in OPERATIONS:
        raise ValueError('Unsupported operator operation')
    if execute and not yes:
        raise ValueError('Operator execution requires --yes')
    if (entry is not None or output is not None) and operation != 'create':
        raise ValueError('Entry/output options apply only to operator create')
    if record is not None and operation not in ('dump','check-record'):
        raise ValueError('Record option applies only to operator record operations')
    if (execute or yes) and operation not in ('pull','create','dump'):
        raise ValueError('Execution options do not apply to this read-only operation')
    root = project_root(project_repo)
    state = refresh_publisher_route(root)
    if operation == 'publisher-route':
        return {'status':'route_status', 'effective':state, 'production_changed':False}
    if operation == 'profile':
        return {**managed.profile(root, control_json), 'operator_root':str(root)}
    if state.get('reader') != 'managed' or state['mode'] not in ('managed','paused'):
        raise ValueError('Packaged operator requires explicitly selected managed routing; no legacy fallback')
    if operation in ('create','dump','check-record') and state['mode'] == 'paused':
        if operation == 'dump':
            if not record: raise ValueError('Operator dump requires --record')
            return {'ok':False,'status':'pending','reason':'publisher_paused','original_draft':str(record),'published':False,'canonical_verified':False,'retained':True}
        raise ValueError('Authoring is paused; retain existing drafts unchanged')
    c = managed.profile(root, control_json)
    if operation in ('status','validate','latest','export'):
        return managed.read(c, operation)
    if operation == 'pull':
        return managed.synchronize(c) if execute else {'status':'plan','operation':'managed-sync','executed':False,'source':c['source'],'authorization':'not established by profile hints'}
    if operation == 'create':
        if not entry: raise ValueError('Operator create requires --entry')
        return managed.create(c, entry, output, execute, yes)
    if not record: raise ValueError('Operator record operation requires --record')
    if operation == 'check-record':
        return managed.check_record(c, record)
    return managed.publish(root, record, c, state, lambda initial:require_managed_promotion_route(root, initial), run, execute, yes)
