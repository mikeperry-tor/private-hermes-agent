"""Upstream differences are advisory; failures must never look up-to-date."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


worker = module('upstream_checks', ROOT / 'components/updates/check.py')
host = module('update_inventory', ROOT / 'scripts/check-updates.py')


class UpdateTests(unittest.TestCase):
    def test_inventory_reads_all_pinned_runtime_images_and_sources(self):
        inventory = host.inventory()
        self.assertEqual({row['name'] for row in inventory['images']}, {'Hermes', 'Tor', 'HAProxy', 'Tailscale', 'Executor desktop'})
        self.assertEqual({row['name'] for row in inventory['sources']}, {'teep', 'x402_treazury'})
        for row in inventory['images']:
            self.assertRegex(row['pinned'], r'@sha256:[a-f0-9]{64}$')
        desktop = next(row for row in inventory['images'] if row['name'] == 'Executor desktop')
        self.assertTrue(desktop['pinned'].startswith('nousresearch/hermes-sandbox@sha256:'))
        self.assertNotEqual(desktop['pinned'], inventory['images'][0]['pinned'])
        self.assertIn('alpine:3.24', inventory['unpinned_bases'])

    def test_platform_digest_matches_without_claiming_an_update(self):
        calls = []
        def request(url, headers=None):
            calls.append(url)
            if 'auth.docker.io' in url:
                return {'token': 'anonymous-public-token'}, ''
            if 'registry-1.docker.io' in url:
                return {'manifests': [{'digest': 'sha256:platform'}]}, 'sha256:index'
            return [{'sha': 'new-source'}], ''
        data = {'images': [{'name': 'image', 'pinned': 'example@sha256:platform', 'channel': 'example:latest'}],
                'sources': [{'name': 'source', 'repository': 'owner/repo', 'pinned': 'old-source'}],
                'unpinned_bases': []}
        report = worker.check(data, request)
        self.assertEqual([row['status'] for row in report['checks']], ['matches', 'different'])
        self.assertTrue(all(url.startswith('https://') for url in calls))
        self.assertEqual(data['sources'][0]['pinned'], 'old-source')

    def test_failed_remote_check_remains_an_error(self):
        def request(*args):
            raise TimeoutError('metadata unavailable')
        data = {'images': [], 'sources': [{'name': 'source', 'repository': 'owner/repo', 'pinned': 'old'}],
                'unpinned_bases': []}
        self.assertEqual(worker.check(data, request)['checks'][0]['status'], 'error')


if __name__ == '__main__':
    unittest.main()
