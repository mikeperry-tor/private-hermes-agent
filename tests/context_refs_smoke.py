#!/usr/bin/env python3
"""Native URL no-fetch and preserved context expansion in the built Hermes image.

Build first: python3 scripts/stack.py compose build hermes
Run: python3 tests/context_refs_smoke.py
"""
import asyncio
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace


def check():
    from agent.context_references import (
        ContextReferenceProvider, parse_context_references,
        preprocess_context_references, preprocess_context_references_async,
        register_context_reference_provider,
    )
    from gateway.session_context_refs import managed_turn_text
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from tools import web_tools

    fetches = []

    async def forbidden_fetch(*args, **kwargs):
        fetches.append((args, kwargs))
        raise AssertionError('context references must not fetch URLs')

    # Cover both supplied and default fetchers. Native expansion catches fetch
    # exceptions, so also assert call count and the absence of injected warnings.
    web_tools.web_extract_tool = forbidden_fetch
    with tempfile.TemporaryDirectory(prefix='context-reference-test-') as folder, ExitStack() as scope:
        root = Path(folder)
        profile = root / 'profile'
        profile.mkdir()
        (profile / 'config.yaml').write_text('context_references:\n  fetch_urls: true\n')
        scope.callback(reset_hermes_home_override, set_hermes_home_override(profile))
        cwd = root / 'workspace'
        cwd.mkdir()
        (cwd / 'sample.txt').write_text('FILE_REFERENCE_CANARY')
        (cwd / 'notes').mkdir()
        (cwd / 'notes' / 'entry.txt').write_text('directory fixture')
        (root / 'outside.txt').write_text('OUTSIDE_ROOT_CANARY')

        def git(*args):
            subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True)

        git('init', '-q')
        git('add', 'sample.txt')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-qm', 'context fixture')
        (cwd / 'sample.txt').write_text('FILE_REFERENCE_CANARY\nUNSTAGED_CANARY')
        (cwd / 'staged.txt').write_text('STAGED_CANARY')
        git('add', 'staged.txt')

        common = {'cwd': cwd, 'allowed_root': cwd, 'context_length': 32768}
        message = 'Inspect @url:`https://example.test/page` and @url:https://other.test/.'
        assert all(ref.kind == 'url' for ref in parse_context_references(message))

        def unchanged(result):
            assert result.message == message, result
            assert result.original_message == message
            assert not result.expanded and not result.blocked and not result.warnings
            assert result.injected_tokens == 0
            assert not fetches, fetches

        unchanged(preprocess_context_references(message, **common))
        unchanged(preprocess_context_references(message, url_fetcher=forbidden_fetch, **common))

        class FixtureProvider(ContextReferenceProvider):
            prefix = 'fixturecontext'

            async def autocomplete(self, query, *, limit=10):
                return []

            async def expand(self, target):
                return 'PLUGIN_REFERENCE_CANARY'

        register_context_reference_provider(FixtureProvider())

        async def run_async():
            unchanged(await preprocess_context_references_async(message, **common))
            unchanged(await preprocess_context_references_async(message, plugins=False, **common))
            unchanged(preprocess_context_references(message, **common))  # running-loop sync bridge
            # Many URL chips must not consume the native non-URL expansion budget.
            urls = ' '.join(f'@url:https://example.test/{i}' for i in range(32))
            mixed = urls + ' @file:sample.txt @folder:notes @diff @staged @git:1 @fixturecontext:value'
            result = await preprocess_context_references_async(mixed, **common)
            assert result.expanded and not result.blocked and not result.warnings, result
            assert result.message.startswith(mixed), result.message
            for canary in ('FILE_REFERENCE_CANARY', 'UNSTAGED_CANARY', 'STAGED_CANARY',
                           'PLUGIN_REFERENCE_CANARY', 'entry.txt', 'context fixture'):
                assert canary in result.message, canary
            assert not fetches, fetches
            refused = await preprocess_context_references_async('@file:../outside.txt', **common)
            assert refused.warnings and 'outside the allowed workspace' in str(refused.warnings)

            # A working file reference proves the admitted text got through the
            # gateway's preprocessing, even when it bypasses profile plugins.
            text = message + ' @file:sample.txt @fixturecontext:value'
            for bypass in (False, True):
                policy = SimpleNamespace(
                    cwd=cwd, ignore_user_config=bypass, base_url='', provider='',
                    config=lambda _authority: {'model': {'context_length': common['context_length']}},
                    current_model=lambda _authority: 'fixture',
                )
                received, refusal = await managed_turn_text(None, {'payload': {'text': text}}, policy)
                assert refusal is None, refusal
                assert received.startswith(text) and 'FILE_REFERENCE_CANARY' in received, received
                assert ('PLUGIN_REFERENCE_CANARY' in received) != bypass, received
                assert not fetches, fetches
            assert 'OUTSIDE_ROOT_CANARY' not in refused.message

        asyncio.run(run_async())
    print('PASS: URL references never fetch; chip text, other references and path guards preserved')


def main():
    if '--inside' in sys.argv:
        check()
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    from deployment import engine_command, local_image

    fixture = Path(__file__).resolve()
    with tempfile.TemporaryDirectory(prefix='context-managed-') as managed:
        (Path(managed) / 'config.yaml').write_text('context_references:\n  fetch_urls: false\n')
        subprocess.run([
            *engine_command(), 'run', '--rm', '--network', 'none', '--cap-drop', 'ALL',
            '-e', 'HERMES_HOME=/tmp/context-reference-home', '-e', 'WEBAPP_EXTERNAL_CONTENT=tor_proxied',
            '-e', 'HERMES_MANAGED_DIR=/etc/hermes',
            '--mount', f'type=bind,source={managed},target=/etc/hermes,readonly',
            '--mount', f'type=bind,source={fixture},target=/tmp/context_refs_smoke.py,readonly',
            '--entrypoint', '/opt/hermes/.venv/bin/python',
            local_image('agent'), '/tmp/context_refs_smoke.py', '--inside',
        ], check=True)


if __name__ == '__main__':
    main()
