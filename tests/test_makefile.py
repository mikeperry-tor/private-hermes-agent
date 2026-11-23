"""Makefile default help runs standalone and references defined targets."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / 'Makefile'
INHERITED_MAKE_VARS = ('MAKEFLAGS', 'MFLAGS', 'MAKELEVEL', 'GNUMAKEFLAGS')


def clean_make_env(**overrides):
    env = {key: value for key, value in os.environ.items() if key not in INHERITED_MAKE_VARS}
    env.update(overrides)
    return env


def parse_makefile(text):
    joined = re.sub(r'\\\n\s*', ' ', text)
    targets = set()
    phony = set()
    for line in joined.splitlines():
        if line.startswith('.PHONY:'):
            phony.update(line.split(':', 1)[1].split())
            continue
        match = re.match(r'^([A-Za-z0-9_-]+)\s*:(?!=)', line)
        if match:
            targets.add(match.group(1))
    return targets, phony


class MakefileHelpTests(unittest.TestCase):
    def test_default_goal_runs_help_without_env_or_engine(self):
        env = clean_make_env(CONTAINER_ENGINE='invalid-engine')
        with tempfile.TemporaryDirectory() as directory:
            shutil.copy2(MAKEFILE, Path(directory) / 'Makefile')
            default_run = subprocess.run(
                ['make', '--no-print-directory'],
                cwd=directory, env=env, text=True, capture_output=True, check=False,
            )
            help_run = subprocess.run(
                ['make', '--no-print-directory', 'help'],
                cwd=directory, env=env, text=True, capture_output=True, check=False,
            )
        self.assertEqual(default_run.returncode, 0, default_run.stderr)
        self.assertEqual(default_run.stderr, '')
        self.assertEqual(help_run.returncode, 0, help_run.stderr)
        self.assertEqual(help_run.stderr, '')
        self.assertEqual(default_run.stdout, help_run.stdout)
        self.assertTrue(help_run.stdout.strip())

    def test_help_and_phony_match_defined_targets(self):
        targets, phony = parse_makefile(MAKEFILE.read_text())
        self.assertEqual(phony, targets)

        result = subprocess.run(
            ['make', '--no-print-directory', 'help'],
            cwd=ROOT, env=clean_make_env(), text=True, capture_output=True, check=True,
        )
        referenced = set(re.findall(r'\bmake\s+([A-Za-z0-9_-]+)', result.stdout))
        self.assertTrue(referenced)
        self.assertEqual(referenced - targets, set())


if __name__ == '__main__':
    unittest.main()
