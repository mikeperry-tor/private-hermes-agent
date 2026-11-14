#!/usr/bin/env python3
"""Test the real x402 MCP server and its secrets/network boundary; no paid calls."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import smoke

sys.path.insert(0, str(Path(__file__).parents[1] / 'components/x402_treazury'))
from endpoints import ADDRESS, ENDPOINTS
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from deployment import compose_base, engine_command  # noqa: E402

smoke.COMPOSE = [*compose_base(), '-p', 'private-hermes-x402-treazury-test',
                 *smoke.compose_files(False, extra=('tests/compose.yaml',))]


def run_suite():
    failed = True
    try:
        print('Validating the production x402_treazury configuration offline...', flush=True)
        command = [*engine_command(), 'run', '--rm', '--network', 'none', 'private-hermes-x402_treazury:local']
        production = json.loads(subprocess.check_output(command + ['config', 'show'], text=True))
        assert production['base_rpc_policy']['primary_default']
        assert production['base_rpc_policy']['fallback_defaults']
        assert {name: entry['listen'] for name, entry in production['servers'].items()} == {
            name: f'{ADDRESS}:{port}' for name, port in ENDPOINTS.items()}
        assert production['wallet_bootstrap'] == {'bootstrap_group': 'general',
                                                  'deferred_groups': ['personal', 'health', 'financial']}
        assert set(production['wallets']) == {'general', 'personal', 'health', 'financial'}
        for wallet, names in {
            'general': ('toolbox', 'web', 'science', 'shopping', 'world'),
            'personal': ('social', 'property', 'travel'),
            'health': ('health',),
            'financial': ('business', 'finance', 'security'),
        }.items():
            assert all(production['servers'][name]['wallet'] == wallet for name in names)
        identity = json.loads(subprocess.check_output(command + ['build-info'], text=True))
        assert identity['source_revision'] == '7ee0f5e89b5413b8ae55e18ee939c9d26df3652d'
        assert identity['source_dirty'] is False
        gate = subprocess.run([*engine_command(), 'run', '--rm', '--network', 'none', '--entrypoint', 'python3',
                               'private-hermes-x402_treazury:local', '-c',
                               "import sys; sys.path.insert(0,'/opt'); from onboarding import serve; serve()"],
                              text=True, capture_output=True)
        assert gate.returncode != 0 and 'Serving refused' in gate.stderr
        partial = subprocess.run([*engine_command(), 'run', '--rm', '--network', 'none', '--entrypoint', 'python3',
                                  'private-hermes-x402_treazury:local', '-c',
                                  "import sys; from pathlib import Path; sys.path.insert(0,'/opt'); from onboarding import initialize; Path('/var/lib/x402/state').mkdir(); initialize()"],
                                 text=True, capture_output=True)
        assert partial.returncode != 0 and 'initialization refused' in partial.stderr
        print('PASS: native production serving gate and partial-state initialization refusal validated offline', flush=True)
        print('PASS: pinned release identity and production x402_treazury config validated without wallet/catalog I/O', flush=True)
        smoke.initialize_setup(smoke.COMPOSE)
        proof = smoke.compose('run', '--rm', '-T', '--no-deps', '--entrypoint', 'python3',
                              'x402_treazury-admin', '/opt/storage-check.py')
        print(proof.stdout.strip(), flush=True)
        # A new disposable, unfunded Zcash wallet is initialized entirely
        # offline with an explicit test birthday; never use the operator tree.
        wallet_command = ('run', '--rm', '-T', '--no-deps', '--entrypoint', '/usr/local/bin/x402_treazury',
                          'x402_treazury-admin', 'wallet')
        initialized = json.loads(smoke.compose(*wallet_command, 'init', '--birthday', '1', '--json').stdout)
        assert initialized['receive_addresses']
        identifier = initialized['state']['treasury_id']
        reopened = json.loads(smoke.compose(*wallet_command, 'status', '--json').stdout)
        assert reopened['treasury_id'] == identifier
        preview = json.loads(smoke.compose(*wallet_command, 'preview', '--json').stdout)
        assert preview['schema_version'] == 1
        assert preview['saved']['treasury_id'] == identifier
        assert set(preview['managed']) == {'general', 'personal', 'health', 'financial'}
        assert not preview['startup_conflicts']
        assert json.loads(smoke.compose(*wallet_command, 'status', '--json').stdout) == reopened
        print('PASS: native offline preview resolves packaged groups without changing saved status', flush=True)
        assert smoke.compose(*wallet_command, 'init', '--birthday', '1', check=False).returncode != 0
        smoke.compose('run', '--rm', '-T', '--no-deps', '--entrypoint', 'python3', 'x402_treazury-admin',
                      '-c', "import os,stat; from pathlib import Path; p=Path('/var/lib/x402/state/wallet.key'); assert p.stat().st_uid==10003; assert stat.S_IMODE(p.stat().st_mode)==0o600; assert p.stat().st_nlink==1")
        print('PASS: native offline test wallet initializes and reopens across containers sharing the native volume with private key permissions intact', flush=True)
        smoke.start_stack(setup=False)
        # No new readiness policy in production: just allow test listeners to
        # finish startup, reporting server failure rather than making paid probes.
        for attempt in range(30):
            ready = smoke.python('hermes', """import socket
for port in range(3010,3022):
 with socket.create_connection(('127.0.0.1',port),timeout=1): pass
""", check=False)
            if ready.returncode == 0:
                break
            if attempt == 29:
                raise RuntimeError('Research test listeners failed to start')
            time.sleep(1)

        # Native Hermes configuration and its dynamic bearer placeholders.
        smoke.python('hermes', """from hermes_cli.config import load_config, load_env
c=load_config(); env=load_env()
assert env.get('X402_TREAZURY_MCP_TOKEN')
for name,port in zip(('toolbox','web','science','shopping','world','social','property','travel','health','business','finance','security'),range(3010,3022)):
 entry=c['mcp_servers']['x402_treazury_'+name]
 assert entry['url']==f'http://127.0.0.1:{port}/mcp'
assert c['terminal']['backend']=='ssh'
""")
        smoke.python('hermes', """import asyncio, json
from hermes_cli.config import load_env
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client, create_mcp_http_client
async def main():
 token=load_env()['X402_TREAZURY_MCP_TOKEN']
 for port in range(3010,3022):
  async with create_mcp_http_client(headers={'Authorization':'Bearer '+token}) as client:
   async with streamable_http_client(f'http://127.0.0.1:{port}/mcp',http_client=client) as (read,write):
    async with ClientSession(read,write) as session:
     await session.initialize()
     tools=await session.list_tools()
     assert tools.tools
     if port==3010:
      assert len(tools.tools)==1
      tool=tools.tools[0]
      response=await session.call_tool(tool.name,{})
      payload=''.join(getattr(c,'text','') for c in response.content)
      assert not response.is_error, payload
      assert '\"IsTor\":true' in ''.join(payload.split()), payload
asyncio.run(main())
""")
        print('PASS: authenticated initialize/list on all 12 real MCP listeners; free Rust API call exits through Tor', flush=True)

        smoke.python('hermes', """import urllib.request, urllib.error
for port in range(3010,3022):
 try: urllib.request.urlopen(f'http://127.0.0.1:{port}/mcp')
 except urllib.error.HTTPError as e: assert e.code==401
 else: raise AssertionError('Unauthenticated MCP request accepted')
""")
        smoke.python('executor', """import os, pathlib, socket
assert not os.getenv('X402_TREAZURY_MCP_TOKEN')
for path in ('/opt/data/.env','/run/x402_treazury-auth/token','/var/lib/x402/state','/home/runner/.hermes/.env'):
 assert not pathlib.Path(path).exists(), path
for host in ('127.0.0.1','10.203.80.2','10.203.82.2'):
 for port in (3010,3021):
  try: s=socket.create_connection((host,port),timeout=.5)
  except OSError: pass
  else: s.close(); raise AssertionError('Executor reached an x402_treazury MCP listener')
""")
        smoke.python('hermes', """import json
from tools.code_execution_tool import execute_code
r=json.loads(execute_code('''import os, pathlib, hermes_tools
assert not os.getenv("X402_TREAZURY_MCP_TOKEN")
assert not pathlib.Path("/opt/data/.env").exists()
r=hermes_tools._call("mcp_x402_treazury_toolbox_raw_call",{})
assert "not available" in str(r), r
print("MCP_RPC_DENIED")''',task_id='x402_treazury-isolation'))
assert 'MCP_RPC_DENIED' in str(r), r
""")
        smoke.python('hermes', """import pathlib, socket
assert not pathlib.Path('/run/x402_treazury-auth/token').exists()
assert not pathlib.Path('/var/lib/x402/state').exists()
try: socket.socket(socket.AF_UNIX).connect('/run/tor-x402_treazury/socks')
except OSError: pass
else: raise AssertionError('Agent gained the x402_treazury Tor socket mount')
""")
        # Verify no SSH channel can turn the connection into an MCP tunnel.
        policy = smoke.execute('executor', '/usr/sbin/sshd', '-T').stdout
        assert 'allowtcpforwarding no' in policy
        assert 'permittunnel no' in policy
        print('PASS: unauthenticated access and code RPC denied; executor lacks secrets, wallet mounts and MCP network access', flush=True)
        # Warm a free public OpenAPI document over real Tor, in a cache-only
        # fixture directory: no treasury keys, managed funding, or paid relay.
        smoke.python('x402_treazury', r"""import json, pathlib, subprocess
root=pathlib.Path('/var/lib/x402/catalog-fixture'); root.mkdir(exist_ok=True)
config=pathlib.Path('/tmp/x402_treazury-test.toml').read_text()
config=config.replace('spec="/tmp/tor-check.json"','spec="https://raw.githubusercontent.com/OpenAPITools/openapi-generator/master/modules/openapi-generator/src/test/resources/3_0/petstore.json"\ncatalog_cache_ttl_seconds=3600\ninclude_operations=["GET /pet/{petId}"]')
config+='\n[treasury]\nstate_dir="/var/lib/x402/catalog-fixture"\n'
path=pathlib.Path('/tmp/catalog-warm.toml'); path.write_text(config)
summary=json.loads(subprocess.check_output(['x402_treazury','catalog','warm','--config',str(path)],text=True))
assert summary['direct'] is False and len(summary['sources'])==1, summary
assert summary['sources'][0]['catalog_cache']=='fresh',summary
assert any((root/'http-cache').iterdir())
""")
        print('PASS: native catalog warming fetched and persisted a free OpenAPI document over Tor without wallet funding', flush=True)
        smoke.compose('stop', 'tor')
        smoke.python('x402_treazury', """import socket
try: socket.socket(socket.AF_UNIX).connect('/run/tor-x402_treazury/socks')
except OSError: pass
else: raise AssertionError('Stopped Tor still accepted a SOCKS connection')
""")
        smoke.python('x402_treazury', """import json,subprocess
forced=subprocess.run(['x402_treazury','catalog','warm','--config','/tmp/catalog-warm.toml'],capture_output=True,text=True)
assert forced.returncode != 0, 'Explicit warm unexpectedly reused a cached catalog'
inventory=json.loads(subprocess.check_output(['x402_treazury','catalog','tools','--config','/tmp/catalog-warm.toml'],text=True))
assert len(inventory)==12, inventory
assert all(len(server['tools'])==1 for server in inventory), inventory
""")
        print('PASS: explicit warm requires fresh acquisition while ordinary inspection reuses the persisted catalog with Tor stopped', flush=True)
        assert smoke.curl('hermes', 'https://check.torproject.org/api/ip', check=False).returncode != 0
        assert json.loads(smoke.curl('hermes', 'http://10.203.83.3:8337/health').stdout)['status']=='ok'
        failed = False
        print('PASS: Tor outage has no direct fallback; local inference remains available', flush=True)
    except Exception as error:
        if isinstance(error, subprocess.CalledProcessError):
            print(error.stdout, error.stderr, flush=True)
        print(smoke.compose('logs','--tail','25','x402_treazury','setup','tor',check=False).stdout, flush=True)
        raise
    finally:
        if failed and os.getenv('KEEP_FAILED_TEST_STACK') == '1':
            print('Retained test project: private-hermes-x402-treazury-test', flush=True)
        else:
            smoke.compose('down','--volumes','--remove-orphans',check=False)


def main():
    with smoke.storage_fixture():
        run_suite()


if __name__ == '__main__':
    main()
