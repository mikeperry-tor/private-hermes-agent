"""Deployment settings handed to native Hermes terminal and tool policy."""
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "managed_policy", ROOT / "components/hermes/managed_policy.py")
managed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(managed)

SERVING = {
    "WEBAPP_TERMINAL_ENVIRONMENT": "code",
    "WEBAPP_EXTERNAL_CONTENT": "tor_proxied",
    "TERMINAL_SSH_HOST": "10.203.82.3",
    "TERMINAL_SSH_PORT": "2222",
    "TERMINAL_SSH_USER": "runner",
    "TERMINAL_SSH_KEY": "/run/agent-ssh/id_ed25519",
}


class ManagedPolicyTests(unittest.TestCase):
    def test_placement_and_launch_selectors(self):
        for selection, mode in (("code", "executor"), ("agent", "gateway")):
            with self.subTest(selection=selection):
                config, env = managed.policy(dict(SERVING, WEBAPP_TERMINAL_ENVIRONMENT=selection))
                self.assertEqual(config["webapp"]["terminal_environment"], mode)
                self.assertEqual(config["webapp"]["executor_ssh_config"], config["terminal"]["ssh_config"])
                self.assertEqual(config["terminal"]["backend"], "ssh")
                self.assertNotIn("cwd", config["terminal"])
                self.assertNotIn("TERMINAL_CWD", env)
                self.assertEqual(env["HERMES_CONFIG_BACKEND"], "file")
                self.assertEqual(env["TERMINAL_ENV"], "ssh")
                for field in ("ssh_host", "ssh_port", "ssh_user", "ssh_key", "ssh_config"):
                    self.assertEqual(env[f"TERMINAL_{field.upper()}"], config["terminal"][field])
                self.assertEqual(config["context_references"], {"fetch_urls": False})
                self.assertTrue(config["bot_desktop"]["executor_only"])
                self.assertTrue(config["browser"]["require_sandbox"])

    def test_desktop_and_preview_selections(self):
        always = {"browser_cdp", "browser_dialog", "browser_vault", "read_window_below"}
        for mode in ("tor_proxied", "ask", "off", "browser_native"):
            for desktop in ("true", "false"):
                with self.subTest(mode=mode, desktop=desktop):
                    config, _ = managed.policy(dict(SERVING, WEBAPP_EXTERNAL_CONTENT=mode, COMPUTER_USE_ENABLED=desktop))
                    expected = set(always)
                    if desktop == "false":
                        expected.update(("browser_exec", "computer_use"))
                    if mode != "browser_native":
                        expected.update(("desktop_preview", "drive_preview", "annotate_preview"))
                    self.assertEqual(set(config["tools"]["disabled"]), expected)

    def test_invalid_mode_refused(self):
        for name in ("WEBAPP_TERMINAL_ENVIRONMENT", "WEBAPP_EXTERNAL_CONTENT", "COMPUTER_USE_ENABLED"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                managed.policy(dict(SERVING, **{name: ""}))

    def test_applied_roots_are_published_as_literal_path_data(self):
        roots = ["/workspace", "/mnt/projects/nested/a ${NAME} $$ \U0001f680"]
        config, dotenv = managed.policy(dict(SERVING, PRIVATE_HERMES_EXECUTOR_ROOTS=json.dumps(roots)))
        self.assertEqual(config["terminal"]["ssh_workspace_roots"], roots)
        self.assertNotIn("TERMINAL_SSH_WORKSPACE_ROOTS", dotenv)
