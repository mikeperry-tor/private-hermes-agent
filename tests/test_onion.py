"""Identity-preserving refusal and exact ingress configuration contracts."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'components/network'))
import onion
from test_webapp import values
from settings import Settings, proxy_config


class OnionTests(unittest.TestCase):
    def test_four_feature_combinations_keep_fixed_network_membership_on_both_engines(self):
        import os
        from test_engine import model
        for selected in ('docker', 'podman'):
            for onion_enabled in ('false', 'true'):
                for funnel_enabled in ('false', 'true'):
                    with self.subTest(engine=selected, onion=onion_enabled, funnel=funnel_enabled), patch.dict(
                            os.environ, TOR_ONION_ENABLED=onion_enabled,
                            TAILSCALE_FUNNEL_ENABLED=funnel_enabled, TAILSCALE_FUNNEL_HOST='test.example.ts.net',
                            COMPOSE_PROJECT_NAME='', NETWORK_PREFIX=''):
                        files = ['compose.yaml']
                        if funnel_enabled == 'true':
                            files.append('compose.funnel.yaml')
                        if selected == 'podman':
                            files.append('compose.podman.yaml')
                            if funnel_enabled == 'true':
                                files.append('compose.podman.funnel.yaml')
                        config = model(*files)
                        services = config['services']
                        self.assertEqual(services['tor']['networks']['onion-ingress']['ipv4_address'], '10.203.86.2')
                        self.assertEqual(services['webapp-proxy']['networks']['onion-ingress']['ipv4_address'], '10.203.86.3')
                        self.assertEqual(services['tor']['environment']['TOR_ONION_ENABLED'], onion_enabled)
                        self.assertEqual(services['webapp-proxy']['environment']['TOR_ONION_ENABLED'], onion_enabled)
                        self.assertNotIn('onion-ingress', services['agent-net']['networks'])
                        self.assertNotIn('onion-ingress', services['executor-net']['networks'])
                        for service in ('onion-init', 'onion-inspect'):
                            self.assertEqual(services[service]['network_mode'], 'none')
                            self.assertFalse(services[service].get('depends_on'))

    def test_hostname_rejects_injected_or_noncanonical_authorities(self):
        good = 'a' * 56 + '.onion'
        self.assertEqual(onion.hostname(good + '\n'), good)
        for value in (good + '\n\n', good + ':80', good.upper(), 'a.onion',
                      good + '\nfrontend evil', good + ' other.onion'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                onion.hostname(value)

    def test_native_replacement_of_corrupt_or_missing_secret_is_prevented(self):
        for value in (None, b'', b'invalid', b'x' * 96):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                folder = root / 'onion-service'
                folder.mkdir()
                (folder / 'hostname').write_text('a' * 56 + '.onion\n')
                if value is not None:
                    (folder / 'hs_ed25519_secret_key').write_bytes(value)
                with patch.object(onion.subprocess, 'Popen') as start:
                    with self.assertRaises(ValueError):
                        onion.initialize(root)
                    start.assert_not_called()
                self.assertEqual(onion.read_address(root), 'a' * 56 + '.onion')
                if value is not None:
                    self.assertEqual((folder / 'hs_ed25519_secret_key').read_bytes(), value)

    def test_fixed_onion_frontend_keeps_each_ingress_authority_and_scheme(self):
        host = 'a' * 56 + '.onion'
        for funnel in ('false', 'true'):
            selected = Settings.read(values(onion_enabled='true', funnel_enabled=funnel,
                                            funnel_host='test.example.ts.net'))
            text = proxy_config(selected, onion_host=host)
            onion_front = text.split('frontend onion\n')[1]
            self.assertIn('bind 10.203.86.3:8080', onion_front)
            self.assertIn('src 10.203.86.2', onion_front)
            self.assertIn(host + ':80 ' + host, onion_front)
            self.assertIn('X-Forwarded-Proto http', onion_front)
            self.assertNotIn('test.example.ts.net', onion_front)
            self.assertEqual('X-Forwarded-Proto https' in text, funnel == 'true')
        with self.assertRaises(ValueError):
            Settings.read(values(onion_enabled='true', webapp_port='8080'))
        with self.assertRaises(ValueError):
            Settings.read(values(onion_enabled='bad'))
        with self.assertRaises(ValueError):
            proxy_config(selected, onion_host=host + '\nfrontend evil')


if __name__ == '__main__':
    unittest.main()
