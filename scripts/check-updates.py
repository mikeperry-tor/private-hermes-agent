#!/usr/bin/env python3
"""Check upstream metadata through the running agent's Tor route; change no pins."""
import argparse
import json
from pathlib import Path
import re
import subprocess
from deployment import ROOT, maintenance_compose


def inventory(root=ROOT):
    root = Path(root)
    hermes = re.search(r'^FROM (nousresearch/hermes-agent@sha256:[a-f0-9]{64})',
                       (root / 'components/hermes/Dockerfile').read_text(), re.M).group(1)
    images = [{'name': 'Hermes', 'pinned': hermes, 'channel': 'nousresearch/hermes-agent:latest'}]
    for name, component, channel in [('Tor', 'network', 'dockurr/tor:latest'),
                                      ('Executor desktop', 'executor', 'nousresearch/hermes-sandbox:desktop'),
                                      ('HAProxy', 'webapp/proxy', None),
                                      ('Tailscale', 'tailscale', 'tailscale/tailscale:stable')]:
        path = root / 'components' / (component + '.Dockerfile' if '/' in component else component + '/Dockerfile')
        # The executor also copies helpers from a pinned Hermes source stage.
        reference = 'nousresearch/hermes-sandbox' if component == 'executor' else r'\S+'
        pinned = re.search(r'^FROM (' + reference + r'@sha256:[a-f0-9]{64})', path.read_text(), re.M).group(1)
        images.append({'name': name, 'pinned': pinned, 'channel': channel or pinned.split('@')[0]})
    sources = []
    for name, component, variable in [('teep', 'teep', 'TEEP_REV'), ('x402_treazury', 'x402_treazury', 'X402_REV')]:
        text = (root / 'components' / component / 'Dockerfile').read_text()
        sources.append({'name': name, 'pinned': re.search(r'^ARG ' + variable + r'=([a-f0-9]{40})$', text, re.M).group(1),
                        'repository': re.search(r'git remote add origin https://github.com/([^\s]+?)\.git', text).group(1)})
    bases = set()
    for path in (root / 'components').rglob('*Dockerfile'):
        text = path.read_text()
        stages = set(re.findall(r'^FROM \S+ AS (\S+)', text, re.M | re.I))
        bases.update(ref for ref in re.findall(r'^FROM (\S+)', text, re.M)
                     if '@sha256:' not in ref and ref not in stages)
    return {'images': images, 'sources': sources, 'unpinned_bases': sorted(bases)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    command = maintenance_compose()
    if not subprocess.check_output([*command, 'ps', '-q', '--status', 'running', 'hermes'], cwd=ROOT, text=True).strip():
        raise SystemExit('Start the stack with make up first; update checks use its Tor route.')
    worker = (ROOT / 'components/updates/check.py').read_text()
    result = subprocess.run([*command, 'exec', '-T', '--user', '10000:10000', 'hermes',
                             '/opt/hermes/.venv/bin/python', '-c', worker], cwd=ROOT,
                            input=json.dumps(inventory()), text=True, stdout=subprocess.PIPE)
    if result.returncode:
        raise SystemExit(f'Update checker could not complete (exit {result.returncode}); no version status is available.')
    report = json.loads(result.stdout)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for row in report['checks']:
            print(f"{row['name']}: {row['status']}\n  pinned: {row['pinned']}\n  upstream ({row.get('channel', 'metadata')}): {row.get('upstream', row.get('error', 'unknown'))}")
        print('Unpinned build bases (no recorded digest to compare): ' + ', '.join(report['unpinned_bases']))
        print('No pins, images, containers, or plugins were changed. Different upstream artifacts require review.')
    raise SystemExit(1 if any(row['status'] == 'error' for row in report['checks']) else 0)


if __name__ == '__main__':
    main()
