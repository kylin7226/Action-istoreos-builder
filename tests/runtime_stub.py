import json
import os
from pathlib import Path
import shutil
import sys

root = Path(os.environ['TEST_ROOT'])
command, *args = sys.argv[1:]
statefile = root / 'state.json'
state = json.loads(statefile.read_text())


def save():
    statefile.write_text(json.dumps(state))


if command == 'json':
    data = json.loads(sys.stdin.read() or '{"value":{},"stack":[]}')
    action, *values = args
    obj = data['value']
    for key in data['stack']:
        obj = obj[key]
    if action == 'dump':
        print(json.dumps(data['value']))
        sys.exit()
    if action == 'close':
        data['stack'].pop()
    else:
        key, *value = values
        val = value[0] if value else ''
        if action == 'string': pass
        elif action == 'int': val = int(val)
        elif action == 'boolean': val = bool(int(val))
        elif action == 'null': val = None
        elif action == 'object': val = {}
        elif action == 'array': val = []
        if isinstance(obj, list):
            key = len(obj)
            obj.append(val)
        else:
            obj[key] = val
        if action in ('array', 'object'): data['stack'].append(key)
    print(json.dumps(data))
elif command == 'uci':
    args = [a for a in args if a != '-q']
    action = args[0]
    if action == 'get': print(state['port'])
    elif action == 'set': state['staged_port'] = args[1].split('=', 1)[1]; save()
    elif action == 'commit':
        if os.environ.get('FAIL_COMMIT'): sys.exit(1)
        state['port'] = state.pop('staged_port', state['port']); save()
    elif action == 'revert': state.pop('staged_port', None); save()
elif command == 'ubus':
    action = args[2]
    payload = json.loads(args[3])
    if action == 'list':
        worker = payload['name'] == 'samwaf-upgrade'
        name, instance = ('samwaf-upgrade', 'worker') if worker else ('samwaf', 'samwaf')
        active = state.get('worker', False) if worker else state['running']
        print(json.dumps({name: {'instances': {instance: {'running': active, 'pid': 123 if active else 0}}}}))
    elif action == 'set':
        if os.environ.get('FAIL_LAUNCH'): sys.exit(1)
        state['worker'] = True; state['launch'] = payload; save()
    elif action == 'delete': state['worker'] = False; save()
elif command == 'jsonfilter':
    data = json.load(sys.stdin)
    worker = 'samwaf-upgrade' in args[-1]
    name, instance = ('samwaf-upgrade', 'worker') if worker else ('samwaf', 'samwaf')
    key = args[-1].rsplit('.', 1)[-1]
    value = data[name]['instances'][instance][key]
    print(str(value).lower() if isinstance(value, bool) else value)
elif command == 'init':
    action = args[0]
    if action in ('start', 'restart'):
        new = b'NEW_BINARY' in (root / 'usr/bin/samwaf').read_bytes()
        if new and os.environ.get('FAIL_NEW_START'):
            (root / 'opt/samwaf/data/database').write_text('migrated')
            sys.exit(1)
        state['running'] = True
    elif action == 'stop': state['running'] = False
    elif action == 'enable': state['enabled'] = True
    elif action == 'disable': state['enabled'] = False
    elif action == 'enabled': sys.exit(0 if state['enabled'] else 1)
    save()
elif command == 'curl':
    output = args[args.index('-o') + 1]
    if output == '/dev/null':
        bad_port = os.environ.get('BAD_PORT')
        sys.exit(0 if state['running'] and state['port'] != bad_port else 22)
    if os.environ.get('FAIL_DOWNLOAD'): sys.exit(22)
    source = root / ('download.tar.gz' if args[-1].endswith('.tar.gz') else 'checksums')
    shutil.copyfile(source, output)
elif command == 'hexdump':
    data = sys.stdin.buffer.read()
    print(data.hex() if '%02x' in args[-1] else ' '.join(map(str, data)), end='')
elif command == 'sleep':
    pass
else:
    raise SystemExit(f'Unexpected mock command: {command}')
