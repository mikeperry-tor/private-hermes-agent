"""Reject grants that could accidentally turn MCP access into host/VM access."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('policy', Path(__file__).parents[1] / 'components/network/network.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class MCPPolicyTests(unittest.TestCase):
    def grants(self, value):
        with patch.object(Path, 'read_text', return_value=json.dumps(value)):
            return policy.mcp_grants()

    def test_no_grants_by_default(self):
        self.assertEqual(self.grants([]), [])

    def test_exact_selected_service_is_accepted(self):
        self.assertEqual(len(self.grants([{'ip': '10.203.84.10', 'port': 8000}])), 1)

    def test_host_vm_router_and_reserved_addresses_are_rejected(self):
        for address in ('172.17.0.1', '192.168.65.254', '127.0.0.1', '169.254.169.254',
                        '10.203.80.3', '10.203.84.0', '10.203.84.1', '10.203.84.2',
                        '10.203.84.255', '::1', 'example.com', '10.203.84.10/24'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                self.grants([{'ip': address, 'port': 8000}])

    def test_ambiguous_or_broad_grants_are_rejected(self):
        for value in ({}, ['10.203.84.10'], [{'ip': '10.203.84.10'}],
                      [{'ip': '10.203.84.10', 'port': 8000, 'allow_all': True}]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.grants(value)
        for port in (True, 0, -1, 65536, '8000', '*', [8000, 8001]):
            with self.subTest(port=port), self.assertRaises(ValueError):
                self.grants([{'ip': '10.203.84.10', 'port': port}])


class LocalIntegrationPolicyTests(unittest.TestCase):
    def test_optional_forwarding_write_failure_requires_confirmed_closed_state(self):
        sysctl = Mock()
        sysctl.write_text.side_effect = PermissionError(13, 'Permission denied')
        with patch.object(policy, 'IP_FORWARD', sysctl):
            sysctl.read_text.return_value = '0\n'
            self.assertIn('Local grants closed', policy.enable_local_forwarding())
            sysctl.read_text.return_value = '1\n'
            with self.assertRaises(PermissionError):
                policy.enable_local_forwarding()
            sysctl.read_text.side_effect = OSError('readback unavailable')
            with self.assertRaisesRegex(OSError, 'readback unavailable'):
                policy.enable_local_forwarding()

    def test_exact_host_ports_and_literal_lan_endpoints(self):
        self.assertEqual(policy.grants({}), ([], []))
        self.assertEqual(policy.grants({
            'HERMES_INTEGRATIONS_ALLOWED_HOST_PORTS': '11434, 443, 443',
            'HERMES_INTEGRATIONS_LAN_ENDPOINTS': '192.168.1.10:8000, 10.8.9.10:443',
        }), ([443, 11434], [('10.8.9.10', 443), ('192.168.1.10', 8000)]))

    def test_invalid_and_reserved_targets_are_rejected(self):
        for value in ('', 'all', '0', '65536', '80-90', '80,', 'none,443'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                policy.grants({'HERMES_INTEGRATIONS_ALLOWED_HOST_PORTS': value})
        for value in ('lan.example:80', '192.168.1.0/24:80', '169.254.169.254:80', '[::1]:80',
                      '100.64.0.1:80', '10.203.87.10:443', '10.203.89.2:80', '10.203.90.3:80',
                      '10.203.91.2:80', '10.204.81.2:80', '192.168.1.2:8000/udp'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                policy.grants({'HERMES_INTEGRATIONS_LAN_ENDPOINTS': value})


if __name__ == '__main__':
    unittest.main()
