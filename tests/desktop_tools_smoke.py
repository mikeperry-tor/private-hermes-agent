#!/usr/bin/env python3
"""Unsupported-tool exclusion in the packaged image; no network or private mounts.

Build first: python3 scripts/stack.py compose build hermes
Run: python3 tests/desktop_tools_smoke.py
"""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace


DISABLED = {
    'browser_exec', 'browser_cdp', 'browser_dialog', 'browser_vault',
    'computer_use', 'read_window_below',
}


PREVIEWS = {'desktop_preview', 'drive_preview', 'annotate_preview'}


def decoded(raw):
    return json.loads(raw) if isinstance(raw, str) else raw


def check():
    import os
    home = Path(os.environ['HERMES_HOME'])
    home.mkdir(parents=True, exist_ok=True)
    config = {'agent': {'disabled_toolsets': []},
              'tools': {'tool_search': {'enabled': 'off'}},
              'toolsets': ['hermes-cli', 'desktop_ui', 'browser', 'computer_use']}
    saved = home / 'config.yaml'
    saved.write_text(json.dumps(config))
    original_config = saved.read_bytes()

    from hermes_bootstrap import PRIVATE_HERMES_EXTERNAL_CONTENT, PRIVATE_HERMES_COMPUTER_USE
    native = PRIVATE_HERMES_EXTERNAL_CONTENT == 'browser_native'
    # Profile dotenv/settings must not change the captured deployment ceiling.
    os.environ['WEBAPP_EXTERNAL_CONTENT'] = 'off' if native else 'browser_native'
    os.environ['COMPUTER_USE_ENABLED'] = 'false' if PRIVATE_HERMES_COMPUTER_USE else 'true'
    blocked = (DISABLED - ({'computer_use', 'browser_exec'} if PRIVATE_HERMES_COMPUTER_USE else set())) | (set() if native else PREVIEWS)

    import model_tools
    from agent.agent_runtime_helpers import invoke_tool
    from agent.inline_tool_executors import INLINE_TOOL_EXECUTORS
    from agent.tool_executor import _ToolCallRef, _resolve_sequential_dispatch
    from tools import desktop_ui, tool_search
    from tools.registry import registry

    from tools.bot_desktop import placement, runtime
    # This fixture has no SSH executor: enabling the preference cannot use the
    # gateway's installed browser/driver as evidence of remote availability.
    from tools.computer_use.tool import check_computer_use_requirements
    assert not check_computer_use_requirements()
    assert placement.resolve().where == placement.REFUSED
    assert runtime.status().install_command is None
    assert runtime.status().blocker
    from tools.browser_use_cli import browser_exec_available, browser_exec
    assert not browser_exec_available()
    proof = Path('/tmp/browser-policy-canary')
    assert decoded(browser_exec(f'from pathlib import Path; Path({str(proof)!r}).touch()')).get('error')
    assert not proof.exists(), 'browser model Python ran in the gateway'
    if PRIVATE_HERMES_COMPUTER_USE:
        assert registry.get_entry('computer_use') is not None
        assert registry.get_entry('browser_exec') is not None

    from tools.computer_use.cua_backend import CuaDriverBackend
    for permission_mode in ('bounded', 'unrestricted'):
        try:
            CuaDriverBackend(permission_mode=permission_mode)
        except ValueError as error:
            assert 'standard driver permissions only' in str(error)
        else:
            raise AssertionError('local embedded driver mode accepted')
    from tools.computer_use.cua_backend_session import _CuaDriverSession
    try:
        _CuaDriverSession._call_tool_via_cli(None, 'get_window_state', {}, 1)
    except RuntimeError as error:
        assert 'gateway-local CLI fallback is disabled' in str(error)
    else:
        raise AssertionError('local driver fallback accepted')

    assert not blocked.intersection(registry.get_all_tool_names())
    assert not blocked.intersection(INLINE_TOOL_EXECUTORS)
    definitions = model_tools.get_tool_definitions(
        enabled_toolsets=config['toolsets'], quiet_mode=True,
        skip_tool_search_assembly=True)
    names = {d['function']['name'] for d in definitions}
    assert not blocked.intersection(names), names
    assert {'read_terminal', 'close_terminal', 'focus_pane'} <= names, names
    assert PREVIEWS.intersection(names) == (PREVIEWS if native else set()), names
    assert all(registry.get_entry(n) for n in ('terminal', 'web_search', 'web_extract'))
    for name in blocked:
        search = decoded(tool_search.dispatch_tool_search(
            {'queries': [name]}, current_tool_defs=definitions))
        assert not blocked.intersection(search['tools']), search
        described = decoded(tool_search.dispatch_tool_describe(
            {'names': [name]}, current_tool_defs=definitions))
        assert name not in described.get('tools', {}), described

    from tools.connectors.contract import TargetState
    from tools.connectors.mcp import _registered_tool_names
    from tools.connectors.operation import ConnectionOperation, Target
    fixture_tool = 'mcp__fixture__lookup'
    try:
        # Setup and catalog activation read the registered MCP tool names.
        for name in [fixture_tool, *sorted(blocked)]:
            registry.register(name=name, toolset='mcp-fixture',
                              schema={'name': name, 'description': 'Fixture'}, handler=lambda **kw: '{}')
        tools = _registered_tool_names('fixture', wait_seconds=0)
        assert tools == [fixture_tool], tools
        for kind, action in (('mcp', 'connect'), ('plugin', 'install')):
            operation = ConnectionOperation([
                Target('fixture', kind, action, state=TargetState.connected, extra={'tools': tools}),
            ])
            assert operation.result()['targets'][0]['tools'] == [fixture_tool]
    finally:
        registry.deregister(fixture_tool)

    def forbidden(*args, **kwargs):
        raise AssertionError('unsupported handler or GUI callback invoked')

    events, preview_calls = [], []
    desktop_ui.set_emitter((lambda sid, event, payload: events.append(event)) if native else forbidden)

    def preview_callback(*args, **kwargs):
        preview_calls.append((args, kwargs))
        return json.dumps({'success': True, 'text': 'fixture preview'})
    agent = SimpleNamespace(
        session_id='fixture', valid_tool_names=names | blocked, quiet_mode=False,
        enabled_toolsets=config['toolsets'], disabled_toolsets=[],
        _memory_manager=None, _context_engine_tool_names=set(),
        read_preview_callback=preview_callback if native else forbidden,
        drive_preview_callback=preview_callback if native else forbidden,
        read_window_below_callback=forbidden,
        read_terminal_callback=lambda **kw: json.dumps({'text': 'fixture terminal'}),
    )
    for name in sorted(blocked):
        # Saved profiles and late scoped/plugin overrides cannot register the name.
        for scope in (None, str(home / 'profiles' / 'other')):
            registry.register(name=name, toolset='desktop_ui', schema={'name': name},
                              handler=forbidden, scope=scope, override=True)
            assert registry.get_entry(name, scope=scope) is None
        for action in ('open', 'read', 'close') if name == 'desktop_preview' else ('capture',):
            args = {'action': action, 'url': 'https://example.test/',
                    'code': "raise AssertionError('model code executed')"}
            direct = decoded(registry.dispatch(name, args))
            assert 'disabled in this deployment' in direct.get('error', ''), direct
            ref = _ToolCallRef(name, args, 'fixture', 'fixture-call', [])
            sequential = decoded(_resolve_sequential_dispatch(agent, ref, []).execute(args))
            concurrent = decoded(invoke_tool(
                agent, name, args, 'fixture', pre_tool_block_checked=True,
                skip_tool_request_middleware=True, skip_tool_execution_middleware=True))
            assert sequential.get('error'), sequential
            assert concurrent.get('error'), concurrent
            bridged = decoded(model_tools.handle_function_call(
                'tool_call', {'calls': [{'name': name, 'arguments': args}]},
                enabled_toolsets=config['toolsets'], disabled_toolsets=[]))
            assert name not in bridged.get('tools', {}), bridged
            assert 'error' in json.dumps(bridged).lower(), bridged

    # In browser_native all preview entry points must work, independently of
    # the executor browser-tool exclusions. Native UI callbacks need no desktop image.
    if native:
        for name, actions in {'desktop_preview': ('open', 'read', 'close'),
                              'drive_preview': ('elements',),
                              'annotate_preview': ('hold',)}.items():
            for action in actions:
                args = {'action': action, 'url': 'https://example.test/'}
                ref = _ToolCallRef(name, args, 'fixture', 'fixture-call', [])
                for raw in (_resolve_sequential_dispatch(agent, ref, []).execute(args),
                            invoke_tool(agent, name, args, 'fixture', pre_tool_block_checked=True,
                                        skip_tool_request_middleware=True, skip_tool_execution_middleware=True)):
                    result = decoded(raw)
                    assert not result.get('error'), result
                    assert result.get('success') or result.get('text') == 'fixture preview', result
        assert events == ['preview.open'] * 2 + ['preview.close'] * 2, events
        assert len(preview_calls) == 6, preview_calls
    else:
        assert not events and not preview_calls

    # The same native paths still reach an available GUI callback.
    ref = _ToolCallRef('read_terminal', {}, 'fixture', 'fixture-call', [])
    assert decoded(_resolve_sequential_dispatch(agent, ref, []).execute({}))['text'] == 'fixture terminal'
    assert decoded(invoke_tool(agent, 'read_terminal', {}, 'fixture',
                              pre_tool_block_checked=True, skip_tool_request_middleware=True,
                              skip_tool_execution_middleware=True))['text'] == 'fixture terminal'
    assert saved.read_bytes() == original_config, 'operator config was modified'
    print(f"PASS: desktop/browser policy and native dispatch mode={PRIVATE_HERMES_EXTERNAL_CONTENT!r} computer_use={PRIVATE_HERMES_COMPUTER_USE}")


def main():
    if '--inside' in sys.argv:
        check()
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    from deployment import engine_command

    fixture = Path(__file__).resolve()
    for mode, enabled in [(m, e) for m in ('tor_proxied', 'ask', 'off', 'browser_native', '', 'invalid') for e in ('false', 'true')]:
        subprocess.run([
            *engine_command(), 'run', '--rm', '--network', 'none', '--cap-drop', 'ALL',
            '-e', f'WEBAPP_EXTERNAL_CONTENT={mode}', '-e', 'HERMES_HOME=/tmp/desktop-tools-test',
            '-e', f'COMPUTER_USE_ENABLED={enabled}',
            '--mount', f'type=bind,source={fixture},target=/tmp/desktop_tools_smoke.py,readonly',
            '--entrypoint', '/opt/hermes/.venv/bin/python',
            'private-hermes-agent:local', '/tmp/desktop_tools_smoke.py', '--inside',
        ], check=True)


if __name__ == '__main__':
    main()
