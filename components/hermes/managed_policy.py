"""Publish the serving container's native Hermes managed configuration."""
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


SSH_CONFIG = "/etc/ssh/ssh_config.d/99-private-hermes.conf"
MODES = {"code": "executor", "agent": "gateway"}
# Keep JSON valid in the YAML reader, including paths outside the BMP.
YAML_ESCAPES = {ord(char): f"\\u{ord(char):04x}" for char in "\u2028\u2029\ufffe\uffff"}


def policy(env):
    mode = env["WEBAPP_TERMINAL_ENVIRONMENT"]
    if mode not in MODES:
        raise ValueError("WEBAPP_TERMINAL_ENVIRONMENT must be code or agent")
    desktop = env.get("COMPUTER_USE_ENABLED", "false")
    if desktop not in ("true", "false"):
        raise ValueError("COMPUTER_USE_ENABLED must be exactly true or false")
    content = env.get("WEBAPP_EXTERNAL_CONTENT")
    if content not in ("tor_proxied", "ask", "off", "browser_native"):
        raise ValueError("WEBAPP_EXTERNAL_CONTENT must be tor_proxied, ask, off or browser_native")

    disabled = ["browser_cdp", "browser_dialog", "browser_vault", "read_window_below"]
    if desktop == "false":
        disabled += ["computer_use", "browser_exec"]
    if content != "browser_native":
        disabled += ["desktop_preview", "drive_preview", "annotate_preview"]

    terminal = {
        "backend": "ssh",
        "ssh_host": env["TERMINAL_SSH_HOST"],
        "ssh_port": int(env["TERMINAL_SSH_PORT"]),
        "ssh_user": env["TERMINAL_SSH_USER"],
        "ssh_key": env["TERMINAL_SSH_KEY"],
        "ssh_config": SSH_CONFIG,
    }
    config = {
        "terminal": terminal,
        "webapp": {"terminal_environment": MODES[mode], "executor_ssh_config": SSH_CONFIG},
        "context_references": {"fetch_urls": False},
        "cron": {"ssh_scripts_base": "/workspace/cron"},
        "tools": {"disabled": disabled},
        "bot_desktop": {"executor_only": True},
        "computer_use": {"backend": "cua", "permission_mode": "standard"},
        "browser": {
            "require_sandbox": True,
            "executor_python": "/opt/browser-harness/bin/python",
            "executor_workspace": "/workspace/browser-use",
        },
    }
    dotenv = {"HERMES_CONFIG_BACKEND": "file", "TERMINAL_ENV": terminal["backend"]}
    # Apply after profile dotenv loading so native clients keep using the
    # namespace route and the gateway remains the authority for local grants.
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        dotenv[name] = dotenv[name.lower()] = ""
    dotenv.update({f"TERMINAL_{key.upper()}": value for key, value in terminal.items()
                   if key != "backend"})
    roots = env.get("PRIVATE_HERMES_EXECUTOR_ROOTS")
    if roots:
        terminal["ssh_workspace_roots"] = json.loads(roots)
    return config, dotenv


def publish(path, text):
    # The managed directory is root-owned in the image's filesystem. The
    # application UID can read the generated policy but cannot replace it.
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(text)
            stream.flush()
            temporary.chmod(0o644)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    directory = Path("/etc/hermes")
    config, dotenv = policy(os.environ)
    directory.mkdir(mode=0o755, exist_ok=True)
    config_text = json.dumps(config, indent=2, ensure_ascii=False).translate(YAML_ESCAPES)
    publish(directory / "config.yaml", config_text + "\n")
    publish(directory / ".env", "".join(f"{key}={json.dumps(value)}\n" for key, value in dotenv.items()))


if __name__ == "__main__":
    main()
