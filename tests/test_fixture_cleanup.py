"""A failed disposable teardown cannot be reported as successful qualification."""
from contextlib import redirect_stdout
import io
import subprocess
import unittest
from unittest.mock import patch
import smoke


class FixtureCleanupTests(unittest.TestCase):
    def test_cleanup_failure_is_visible_without_masking_original_failure(self):
        for check in (True, False):
            result = subprocess.CompletedProcess([], 1, 'cleanup stdout', 'cleanup stderr')
            with self.subTest(check=check), patch.object(smoke, 'COMPOSE', ['compose']), \
                    patch.object(smoke, 'inspect_launch', return_value=(None, False)), \
                    patch.object(smoke.subprocess, 'run', return_value=result), \
                    patch.object(smoke, 'remove_networks') as networks, redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(subprocess.CalledProcessError):
                    smoke.compose('down', check=check)
                try:
                    raise ValueError('original test failure')
                except ValueError:
                    self.assertIs(smoke.compose('down', check=check), result)
                self.assertIn('cleanup stderr', output.getvalue())
                networks.assert_not_called()
