#!/usr/bin/env python3
"""Qualify actual Hermes SSH/Python execution and the isolated Compose topology.

Separate project, dummy teep key, no inference. Uses a disposable proxy health
endpoint, a real MCP client against an SSE fixture, and explicit forbidden peers.
"""
import json
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'components/provisioning'))
from storage import initialize as initialize_storage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from provisioning import initialize_setup, initialize_research_config
from deployment import check_bind_sources, compose_files, needs_networks, engine, prepare_launch, remove_networks, compose_base, engine_command

COMPOSE = [*compose_base(), '-p', 'private-hermes-test', *compose_files(False, extra=('tests/compose.yaml',))]


@contextmanager
def storage_fixture(root=None):
    if root is None:
        root = Path(tempfile.mkdtemp(prefix='private-hermes-storage-'))
    else:
        root = Path(root)
        root.mkdir(parents=True)
    initialize_storage(root)
    marker = secrets.token_hex(16)
    (root / '.test-storage').write_text(marker)
    previous = os.environ.get('TEST_DATA_DIR')
    os.environ['TEST_DATA_DIR'] = str(root)
    retain = False
    try:
        initialize_research_config(COMPOSE, root)
        yield root
    except BaseException:
        retain = os.getenv('KEEP_FAILED_TEST_STACK') == '1'
        raise
    finally:
        try:
            if retain:
                print('Retained disposable bind data: ' + str(root), flush=True)
            else:
                try:
                    shutil.rmtree(root)
                except PermissionError:
                    # Linux hosts need ownership returned from container UIDs.
                    # A nonce and one explicit disposable bind keep this
                    # metadata operation away from operator data.
                    (root / '.test-storage').write_text(marker)
                    script = '''import os, pathlib, stat, sys
root=pathlib.Path('/persistent-data')
assert root.joinpath('.test-storage').read_text()==sys.argv[1]
uid,gid=int(sys.argv[2]),int(sys.argv[3])
for base,dirs,files in os.walk(root):
 for path in [pathlib.Path(base),*(pathlib.Path(base)/p for p in dirs+files)]:
  meta=path.lstat()
  os.chown(path,uid,gid,follow_symlinks=False)
  if not stat.S_ISLNK(meta.st_mode): path.chmod(stat.S_IMODE(meta.st_mode)|(0o700 if stat.S_ISDIR(meta.st_mode) else 0o600))
'''
                    # Rootless Podman maps the host user to container UID 0.
                    owner = ('0', '0') if engine() == 'podman' else (str(os.getuid()), str(os.getgid()))
                    # Do not reuse setup: its application-volume mounts would
                    # recreate empty named volumes after the suite's shutdown.
                    subprocess.run([*engine_command(), 'run', '--rm', '--network', 'none',
                                    '--user', '0:0', '--cap-drop', 'ALL',
                                    '--cap-add', 'CHOWN', '--cap-add', 'FOWNER',
                                    '--cap-add', 'DAC_OVERRIDE', '--read-only',
                                    '--security-opt', 'no-new-privileges:true',
                                    '--tmpfs', '/tmp:mode=1777',
                                    '--mount', f'type=bind,source={root},target=/persistent-data',
                                    '--entrypoint', '/opt/hermes/.venv/bin/python',
                                    'private-hermes-agent:local', '-c', script, marker, *owner],
                                   check=True)
                    shutil.rmtree(root)
        finally:
            if previous is None:
                os.environ.pop('TEST_DATA_DIR', None)
            else:
                os.environ['TEST_DATA_DIR'] = previous


# Podman counterparts of the Docker host and VM addresses: pasta's address for the
# host, and the gateway address of each network, where aardvark-dns answers.
GATEWAYS = ('10.203.80.1', '10.203.81.1', '10.203.82.1', '10.203.83.1', '10.203.84.1', '10.203.85.1')
PODMAN_HOST_TARGETS = ('169.254.1.2', *GATEWAYS)


def compose(*args, check=True, **kwargs):
    check_bind_sources(COMPOSE, list(args))
    if needs_networks(COMPOSE, list(args)):
        prepare_launch(COMPOSE)
    # Include stopped profiled namespace users before removing their owners.
    # Report cleanup failures without replacing an original test exception.
    teardown = args[:1] == ('down',)
    command = [*COMPOSE, *(['--profile', '*'] if teardown else [])]
    result = subprocess.run(command + list(args), check=False if teardown else check,
                            text=True, capture_output=True, **kwargs)
    if teardown:
        if result.returncode:
            print('Disposable project cleanup failed:', result.stdout, result.stderr, flush=True)
            if sys.exc_info()[0] is None:
                result.check_returncode()
        else:
            remove_networks(COMPOSE)
    return result


def execute(service, *args, user=None, check=True):
    options = ['exec', '-T']
    if user is None and service == 'hermes':
        user = '10000:10000'
    if user:
        options += ['--user', user]
    return compose(*options, service, *args, check=check)


def curl(service, url, check=True, *, connect_timeout=3, max_time=35):
    return execute(service, 'curl', '--noproxy', '*', '-fsS', '--connect-timeout', str(connect_timeout),
                   '--max-time', str(max_time), url,
                   user='10000:10000' if service == 'executor' else None, check=check)


def public_ip(service):
    # Public Tor controls need DNS/circuit/TLS establishment, unlike forbidden
    # probes. resolv.conf already allows 5s x 2 DNS attempts before TLS setup.
    return json.loads(curl(service, 'https://check.torproject.org/api/ip',
                           connect_timeout=30, max_time=90).stdout)


def python(service, code, check=True):
    interpreter = '/opt/hermes/.venv/bin/python' if service == 'hermes' else 'python3'
    return execute(service, interpreter, '-c', code, user='10000:10000' if service == 'executor' else None, check=check)


def namespace_owner_check(uid, gid):
    return f"""from pathlib import Path
status=dict(line.split(':',1) for line in Path('/proc/1/status').read_text().splitlines() if ':' in line)
assert [int(value) for value in status['Uid'].split()]==[{uid}]*4, status
assert [int(value) for value in status['Gid'].split()]==[{gid}]*4, status
assert not status['Groups'].split(), status
assert all(int(status[key].strip(),16)==0 for key in ('CapEff','CapPrm','CapInh','CapAmb','CapBnd')), status
assert status['NoNewPrivs'].strip()=='1', status
"""


def eventually(operation, attempts=4):
    for attempt in range(attempts):
        try:
            return operation()
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            if attempt == attempts - 1:
                raise
            time.sleep(2)


def start_stack(setup=True):
    if setup:
        initialize_setup(COMPOSE)
    identifier = compose('ps', '-a', '-q', 'setup').stdout.strip()
    started = subprocess.check_output([*engine_command(), 'inspect', identifier, '--format', '{{.State.StartedAt}}'], text=True)
    # The unfunded test fixture intentionally connects its MCP inventory before
    # startup. Production only connects after authenticated endpoint readiness.
    compose('run', '--rm', '-T', '--no-deps', 'mcp-config', 'connect')
    compose('up', '-d', '--no-build', '--wait', '--no-deps', '--wait-timeout', '600',
            'tor', 'agent-net', 'executor-net', 'executor', 'teep', 'fixture', 'x402_treazury', 'hermes')
    assert subprocess.check_output([*engine_command(), 'inspect', identifier, '--format', '{{.State.StartedAt}}'], text=True) == started


def run_suite():
    failed = True
    try:
        print('Starting isolated test stack...', flush=True)
        start_stack()
        for service, uid, gid in (('tor', 101, 102), ('agent-net', 65534, 65534),
                                  ('executor-net', 65534, 65534)):
            python(service, namespace_owner_check(uid, gid))
        print('PASS: steady-state namespace owners are unprivileged with empty capability sets', flush=True)
        for service in ('hermes', 'executor'):
            response = eventually(lambda: public_ip(service))
            assert response['IsTor'] is True
        assert public_ip('teep')['IsTor'] is False
        assert json.loads(curl('hermes', 'http://10.203.83.3:8337/health').stdout)['status'] == 'ok'
        published = compose('port', 'teep', '8337').stdout.strip()
        assert published.startswith('127.0.0.1:'), published
        host_port = int(published.rsplit(':', 1)[1])
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://{published}/health', timeout=5) as response:
            assert json.load(response)['status'] == 'ok'
        # Publishing must not create a new host/VM route for either isolated
        # namespace, or make the executor able to use inference indirectly.
        for service in ('hermes', 'executor'):
            python(service, f"""import socket
for host in ('172.17.0.1','192.168.65.1','192.168.65.2','192.168.65.254',*{PODMAN_HOST_TARGETS!r}):
 try: socket.create_connection((host,{host_port}),timeout=.3).close()
 except OSError: pass
 else: raise AssertionError(('Published inference reached through host',host))
""")
        print('PASS: host loopback reaches teep; isolated agent/executor cannot reach its published host port', flush=True)
        print('PASS: agent and executor use Tor; single-service teep uses direct egress', flush=True)

        # Prove the forbidden peer exists and listens: failure cannot be mistaken
        # for protection merely because the target service is absent.
        assert curl('fixture', 'http://127.0.0.1:111').stdout == 'ok'
        assert curl('fixture', 'http://127.0.0.1:8001').stdout == 'ok'
        python('fixture', "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(2); s.sendto(b'probe',('127.0.0.1',111)); assert s.recv(1024)==b'rpcbind-open'")
        for service in ('hermes', 'executor'):
            for host in ('10.203.80.10', '172.17.0.1', '192.168.65.1', '192.168.65.2', '192.168.65.254', '169.254.169.254',
                         *PODMAN_HOST_TARGETS):
                assert curl(service, f'http://{host}:111', check=False).returncode != 0, (service, host)
            python(service, """import socket
for host in ('10.203.80.10', '172.17.0.1', '192.168.65.254', '169.254.1.2'):
 s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(.3)
 try:
  s.connect((host,111)); s.send(b'blocked'); s.recv(1024)
 except (TimeoutError, OSError): pass
 else: raise AssertionError('UDP reached prohibited peer')
 finally: s.close()
""")
            assert curl(service, 'http://[fd00::1]:111', check=False).returncode != 0
        for service in ('agent-net', 'executor-net'):
            rules = execute(service, 'iptables', '-L', 'OUTPUT', '-nvx').stdout
            assert any('DROP' in line and int(line.split()[0]) > 0 for line in rules.splitlines() if line.split() and line.split()[0].isdigit())
        assert curl('executor', 'http://10.203.83.3:8337/health', check=False).returncode != 0
        assert curl('executor', 'http://10.203.82.2:8642', check=False).returncode != 0
        print('PASS: host/VM, rpcbind TCP/UDP, IPv6, executor-to-agent and executor-to-teep blocked', flush=True)

        # The pinned known-host entry and readonly key are consumed by Hermes's
        # actual SSH backend, not a substitute SSH client or a local shell.
        terminal = python('hermes', """import json
from tools.terminal_tool import terminal_tool
result=json.loads(terminal_tool('id -u; printenv AGENT_ONLY_SENTINEL || echo absent', task_id='qualification'))
print(json.dumps(result))
assert '10000' in str(result) and 'absent' in str(result), result
assert 'must-not-reach-executor' not in str(result)
""")
        print(terminal.stdout.strip(), flush=True)
        result = python('hermes', """import json
from tools.code_execution_tool import execute_code
r=json.loads(execute_code("import os; print('REMOTE_EXECUTION', os.getuid()); print(os.path.exists('/run/agent-ssh/id_ed25519'))", task_id='qualification'))
print(json.dumps(r))
assert 'REMOTE_EXECUTION 10000' in str(r), r
assert 'False' in str(r), r
""")
        print(result.stdout.strip(), flush=True)
        python('executor', """from pathlib import Path
status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert all(int(status[key].strip(),16)==0 for key in ('CapEff','CapPrm','CapInh','CapAmb')), status
assert status['NoNewPrivs'].strip()=='1' and status['Seccomp'].strip()=='2', status
""")
        for service in ('hermes', 'executor'):
            python(service, """import socket
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(.5)
for server in ('127.0.0.11', *GATEWAYS):
 try:
  s.sendto(bytes.fromhex('123401000001000000000000076578616d706c6503636f6d0000010001'),(server,53))
  s.recv(4096)
 except (OSError, TimeoutError): pass
 else: raise AssertionError(('Engine DNS bypass', server))
""".replace('GATEWAYS', repr(GATEWAYS)))
        print('PASS: actual Hermes terminal and execute_code run remotely without agent keys; code has no capabilities with NNP/seccomp active; embedded DNS blocked', flush=True)

        # Actual MCP SDK initialize/list/call over streamed HTTP/SSE.
        python('hermes', """import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
async def main():
 async with streamable_http_client('http://10.203.84.10:8000/mcp') as (read,write,*_):
  async with ClientSession(read,write) as session:
   await session.initialize()
   tools=await session.list_tools()
   assert tools.tools[0].name=='echo'
   response=await session.call_tool('echo', {'text':'streaming-ok'})
   assert response.content[0].text=='streaming-ok'
asyncio.run(main())
""")
        assert curl('hermes', 'http://10.203.84.10:8001', check=False).returncode != 0
        assert curl('executor', 'http://10.203.84.10:8000', check=False).returncode != 0
        print('PASS: selected MCP streaming port works; unselected port and executor MCP access blocked', flush=True)

        if os.environ.get('COMPUTER_USE_ENABLED', 'false') == 'true':
            import computer_use_smoke
            computer_use_smoke.check()
            computer_use_smoke.switching_checks()

        # Host-controlled fixture launch only: model code never receives sudo.
        uid_probe = "import os,sys; os.setgroups([]); os.setgid(101); os.setuid(101); os.execvp('curl',['curl','--noproxy','*','-fsS','--connect-timeout',sys.argv[1],'--max-time',sys.argv[2],'https://check.torproject.org/api/ip'])"
        uid_result = eventually(lambda: execute('executor', 'python3', '-c', uid_probe, '30', '90', user='0:0'))
        assert json.loads(uid_result.stdout)['IsTor'] is True
        print('PASS: executor UID 101 still uses Tor', flush=True)

        compose('stop', 'tor')
        for service in ('hermes', 'executor'):
            assert curl(service, 'https://check.torproject.org/api/ip', check=False).returncode != 0
        curl('hermes', 'http://10.203.83.3:8337/health')
        curl('hermes', 'http://10.203.84.10:8000/health')
        assert execute('executor', 'python3', '-c', uid_probe, '3', '35', user='0:0', check=False).returncode != 0
        print('PASS: Tor outage blocks public egress while local teep/MCP stay available', flush=True)
        if os.environ.get('COMPUTER_USE_ENABLED', 'false') == 'true':
            execute('hermes', '/opt/hermes/.venv/bin/python', '-c', '''import json
from tools.browser_use_cli import browser_exec
r=json.loads(browser_exec('print("outage-remote")\\nimport urllib.request; urllib.request.urlopen("https://check.torproject.org/api/ip",timeout=5)',session='tor-outage'))
assert r.get('success') is False and 'outage-remote' in r.get('output',''),r
''', user='10000:10000')
        compose('up', '-d', '--wait', '--no-deps', '--wait-timeout', '600', 'tor')
        assert eventually(lambda: public_ip('executor'))['IsTor'] is True
        print('PASS: Tor restart restores executor public egress through Tor', flush=True)
        if os.environ.get('COMPUTER_USE_ENABLED', 'false') == 'true':
            # public_ip above proves Tor recovery for this namespace. Confirm
            # the browser worker recovers there without another public TLS GET.
            expected_netns = python('executor', "import os; print(os.readlink('/proc/self/ns/net'))").stdout.strip()
            recovered = ("import os; assert os.readlink('/proc/self/ns/net')==" + repr(expected_netns) +
                         "; print('executor-recovered')")
            execute('hermes', '/opt/hermes/.venv/bin/python', '-c', f"""import json
from tools.browser_use_cli import browser_exec
r=json.loads(browser_exec({recovered!r},session='tor-outage'))
assert r.get('success') and r.get('output','').strip()=='executor-recovered',r
""", user='10000:10000')
            print('PASS: browser harness observes Tor outage and recovers in the Tor-qualified executor namespace without direct fallback', flush=True)
        failed = False
    except subprocess.CalledProcessError as error:
        print(error.stdout, error.stderr, flush=True)
        print(compose('logs', '--tail', '20', 'tor', 'agent-net', 'executor-net', 'executor', check=False).stdout)
        raise
    finally:
        if failed and os.getenv('KEEP_FAILED_TEST_STACK') == '1':
            print('Failed test stack retained for diagnosis: private-hermes-test', flush=True)
        else:
            compose('down', '--volumes', '--remove-orphans', check=False)


def main():
    with storage_fixture():
        run_suite()


if __name__ == '__main__':
    main()
