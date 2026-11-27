"""Run the canonical offline setup service and manage opt-in research policy."""
import difflib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from deployment import ROOT, engine_command, check_bind_sources

RESEARCH_CONFIG_DIR = Path('config/x402_treazury')
RESEARCH_CONFIG = RESEARCH_CONFIG_DIR / 'research_desk.toml'
RESEARCH_CONFIG_BASE = RESEARCH_CONFIG_DIR / '.research_desk.toml.base'
RESEARCH_CONFIG_BACKUP = RESEARCH_CONFIG_DIR / 'research_desk.toml.bak'
RESEARCH_CONFIG_MERGE = RESEARCH_CONFIG_DIR / 'research_desk.toml.merge'
PACKAGED_RESEARCH_CONFIG = '/opt/x402/defaults/deployments/research_desk.toml'


def setup_container(command):
    return subprocess.check_output([*command, 'ps', '-a', '-q', 'setup'], cwd=ROOT, text=True).strip()


def initialize_setup(command):
    # --wait expects a running/healthy service and can reject a successfully
    # exited one-shot. Wait for this container's exit status explicitly instead.
    check_bind_sources(command, ['up', '--no-deps', 'setup'])
    subprocess.run([*command, 'up', '-d', '--no-deps', '--force-recreate', 'setup'], cwd=ROOT, check=True)
    identifier = setup_container(command)
    if not identifier:
        raise RuntimeError('Setup container was not created')
    code = int(subprocess.check_output([*engine_command(), 'wait', identifier], cwd=ROOT, text=True).strip())
    if code:
        subprocess.run([*command, 'logs', '--tail', '40', 'setup'], cwd=ROOT, check=False)
        raise RuntimeError(f'Offline setup failed (exit {code}); application startup was not attempted.')


def _require_config_dir(directory, *, create=False):
    try:
        info = os.lstat(directory)
    except FileNotFoundError:
        if not create:
            return False
        directory.mkdir(parents=True, exist_ok=True)
        info = os.lstat(directory)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise RuntimeError('config/x402_treazury must be a directory')
    if create:
        # Treasury UID 10003 needs read/traverse access; mount the leaf directory
        # read-only while keeping the parent config directory host-owned.
        os.chmod(directory, 0o755)
    return True


def ensure_research_config_dir(root=ROOT):
    """Ensure the static x402_treazury config bind directory exists without seeding a file."""
    _require_config_dir(Path(root) / RESEARCH_CONFIG_DIR, create=True)


def _require_regular_file(path, label):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f'{label} must be a regular file')
    return path.read_bytes()


def _stage_file(directory, content, mode=0o644, prefix='.research-config-'):
    with tempfile.NamedTemporaryFile(dir=directory, prefix=prefix, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), mode)
            return temporary
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise


def _write_atomic(path, content, mode=0o644):
    temporary = _stage_file(path.parent, content, mode=mode)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def research_image(command):
    """Resolve the local x402_treazury image tag from the active Compose model."""
    model = json.loads(subprocess.check_output(
        [*command, '--profile', 'x402_treazury', 'config', '--format', 'json'],
        cwd=ROOT, text=True))
    return model['services']['x402_treazury']['image']


def packaged_research_config(command):
    """Read the rendered default from the selected local image, offline."""
    image = research_image(command)
    try:
        return subprocess.check_output(
            [*engine_command(), 'run', '--rm', '--pull', 'never', '--network', 'none',
             '--entrypoint', 'cat', image, PACKAGED_RESEARCH_CONFIG],
            cwd=ROOT, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as error:
        stderr = error.stderr.decode('utf-8', 'replace').strip() if isinstance(error.stderr, bytes) else (error.stderr or '').strip()
        detail = stderr.splitlines()[-1] if stderr else f'exit {error.returncode}'
        raise RuntimeError(
            f'Could not read packaged research_desk.toml from {image} ({detail}). Run make build or make up first.'
        ) from error


def validate_research_config_candidate(command, candidate_path, root=ROOT):
    """Validate a candidate config offline using only a read-only config bind mount."""
    image = research_image(command)
    config_dir = (Path(root) / RESEARCH_CONFIG_DIR).resolve()
    result = subprocess.run(
        [*engine_command(), 'run', '--rm', '--pull', 'never', '--network', 'none',
         '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
         '--tmpfs', '/tmp:mode=1777',
         '--mount', f'type=bind,src={config_dir},dst=/opt/x402/examples/deployments,readonly',
         '-e', f'X402_TREAZURY_CONFIG=/opt/x402/examples/deployments/{candidate_path.name}',
         '--entrypoint', 'python3', image, '/opt/onboarding.py', 'validate'],
        cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or f'Offline validation failed (exit {result.returncode})')


def research_config_status(command, root=ROOT):
    """Inspect whether an opt-in local override exists and how it relates to packaged defaults."""
    directory = Path(root) / RESEARCH_CONFIG_DIR
    if not _require_config_dir(directory, create=False):
        return {'mode': 'default'}
    saved = _require_regular_file(Path(root) / RESEARCH_CONFIG, str(RESEARCH_CONFIG))
    if saved is None:
        return {'mode': 'default'}
    base = _require_regular_file(Path(root) / RESEARCH_CONFIG_BASE, str(RESEARCH_CONFIG_BASE))
    packaged = packaged_research_config(command)
    if saved == packaged:
        state = 'matches_packaged'
    elif base is None:
        state = 'differs_no_base'
    elif packaged == base:
        state = 'current'
    elif saved == base:
        state = 'stale_unmodified'
    else:
        state = 'diverged'
    return {'mode': 'local', 'state': state, 'saved': saved, 'packaged': packaged, 'base': base}


def research_config_diff(command, root=ROOT):
    """Display textual differences without changing policy or wallet state."""
    status = research_config_status(command, root)
    if status['mode'] == 'default':
        print('Using packaged image defaults (no local override at config/x402_treazury/research_desk.toml). '
              'Run make x402_treazury-config to create an editable local copy.', flush=True)
        return
    saved = status['saved'].decode('utf-8')
    packaged = status['packaged'].decode('utf-8')
    # Normalize line endings and supply a terminator for readable final diff lines.
    changes = list(difflib.unified_diff(
        packaged.splitlines(), saved.splitlines(),
        fromfile='packaged default (local image)', tofile='saved config (config/x402_treazury/research_desk.toml)',
        lineterm=''))
    if changes:
        print('Differences from packaged defaults (includes intentional customization; saved config is preserved):')
        print('\n'.join(changes), flush=True)
    else:
        print('Research config matches packaged defaults.', flush=True)


def report_research_config_notice(command, root=ROOT):
    """Print a concise end-of-startup notice only when an opt-in local copy needs attention."""
    try:
        status = research_config_status(command, root)
        if status['mode'] == 'default' or status['state'] in ('current', 'matches_packaged'):
            return
        state = status['state']
        if state == 'stale_unmodified':
            print('Notice: config/x402_treazury/research_desk.toml has no local edits relative to the previous '
                  'image default, while the packaged image version has updated. Run make x402_treazury-config-diff '
                  'to display differences, or make x402_treazury-config-reset to restore the latest image version.',
                  flush=True)
        elif state == 'diverged':
            print('Notice: config/x402_treazury/research_desk.toml has differences compared to the updated image '
                  'version. Run make x402_treazury-config-diff to display differences, '
                  'make x402_treazury-config-merge to merge image updates into your local copy, or '
                  'make x402_treazury-config-reset to restore the latest image version.', flush=True)
        else:
            print('Notice: config/x402_treazury/research_desk.toml has differences compared to the image version. '
                  'Run make x402_treazury-config-diff to display differences, or '
                  'make x402_treazury-config-reset to restore the latest image version.', flush=True)
    except (OSError, UnicodeError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'Research config comparison unavailable: {error}. Retry make x402_treazury-config-diff.',
              file=sys.stderr, flush=True)


def initialize_research_config(command, root=ROOT):
    """Create an opt-in local copy and base snapshot from the built image without overwriting."""
    ensure_research_config_dir(root)
    path = Path(root) / RESEARCH_CONFIG
    if os.path.lexists(path):
        _require_regular_file(path, str(RESEARCH_CONFIG))
        return False
    content = packaged_research_config(command)
    temporary = _stage_file(path.parent, content, mode=0o644)
    published = False
    try:
        try:
            os.link(temporary, path)
            published = True
        except FileExistsError:
            _require_regular_file(path, str(RESEARCH_CONFIG))
    finally:
        temporary.unlink(missing_ok=True)
    if published:
        _write_atomic(Path(root) / RESEARCH_CONFIG_BASE, content, mode=0o644)
    return published


def merge_research_config(command, root=ROOT):
    """3-way merge packaged image updates into an opt-in local copy and validate offline."""
    status = research_config_status(command, root)
    if status['mode'] == 'default':
        print('Using packaged image defaults (no local override at config/x402_treazury/research_desk.toml); '
              'nothing to merge.', flush=True)
        return
    path = Path(root) / RESEARCH_CONFIG
    base_path = Path(root) / RESEARCH_CONFIG_BASE
    merge_path = Path(root) / RESEARCH_CONFIG_MERGE
    state = status['state']
    if state == 'matches_packaged':
        if status['base'] is not None and status['base'] != status['packaged']:
            _write_atomic(base_path, status['packaged'], mode=0o644)
        merge_path.unlink(missing_ok=True)
        print('config/x402_treazury/research_desk.toml already matches the packaged image default.', flush=True)
        return
    if state == 'current':
        print('Packaged image defaults have not changed since config/x402_treazury/research_desk.toml was '
              'created or last merged; nothing to merge.', flush=True)
        return
    if state == 'differs_no_base':
        raise RuntimeError(
            'Cannot 3-way merge config/x402_treazury/research_desk.toml because '
            'config/x402_treazury/.research_desk.toml.base is absent. Run make x402_treazury-config-diff to '
            'display differences, or make x402_treazury-config-reset to back up your local copy and restore '
            'the latest image version.'
        )
    if state == 'stale_unmodified':
        merged = status['packaged']
    else:
        git = shutil.which('git')
        if not git:
            raise RuntimeError('git is required for 3-way merge (make x402_treazury-config-merge).')
        with tempfile.TemporaryDirectory(prefix='x402-config-merge-') as folder:
            saved_tmp = Path(folder) / 'saved.toml'
            base_tmp = Path(folder) / 'base.toml'
            packaged_tmp = Path(folder) / 'packaged.toml'
            saved_tmp.write_bytes(status['saved'])
            base_tmp.write_bytes(status['base'])
            packaged_tmp.write_bytes(status['packaged'])
            result = subprocess.run(
                [git, 'merge-file', '-p',
                 '-L', 'saved (config/x402_treazury/research_desk.toml)',
                 '-L', 'previous image default',
                 '-L', 'new image default (local image)',
                 str(saved_tmp), str(base_tmp), str(packaged_tmp)],
                capture_output=True)
        if result.returncode < 0 or result.returncode > 127:
            detail = result.stderr.decode('utf-8', 'replace').strip()
            raise RuntimeError(f'3-way merge failed (exit {result.returncode}): {detail or "git merge-file error"}')
        if result.returncode > 0:
            _write_atomic(merge_path, result.stdout, mode=0o644)
            raise RuntimeError(
                f'3-way merge found {result.returncode} conflict(s); wrote conflicted result to '
                'config/x402_treazury/research_desk.toml.merge and left config/x402_treazury/research_desk.toml '
                'unchanged. Resolve conflicts in research_desk.toml.merge and copy it over research_desk.toml '
                '(make up will continue showing the advisory notice until you reset), or run '
                'make x402_treazury-config-reset and reapply your edits.'
            )
        merged = result.stdout

    ensure_research_config_dir(root)
    candidate = _stage_file(path.parent, merged, mode=0o644, prefix='.research-config-candidate-')
    try:
        try:
            validate_research_config_candidate(command, candidate, root=root)
        except RuntimeError as error:
            _write_atomic(merge_path, merged, mode=0o644)
            raise RuntimeError(
                'Merged config failed offline x402_treazury validation; wrote candidate to '
                'config/x402_treazury/research_desk.toml.merge and left config/x402_treazury/research_desk.toml '
                f'unchanged.\n{error}'
            ) from error
        base_temp = _stage_file(path.parent, status['packaged'], mode=0o644, prefix='.research-config-base-')
        try:
            # Replace the live policy first so a crash between updates never
            # advances .base ahead of research_desk.toml.
            os.replace(candidate, path)
            os.replace(base_temp, base_path)
        finally:
            base_temp.unlink(missing_ok=True)
    finally:
        candidate.unlink(missing_ok=True)
    merge_path.unlink(missing_ok=True)
    if state == 'stale_unmodified':
        print('Updated unmodified config/x402_treazury/research_desk.toml to the latest image default. '
              'Run make down && make up to apply (or run make x402_treazury-config-reset to track future '
              'image defaults automatically).', flush=True)
    else:
        print('Merged packaged image updates into config/x402_treazury/research_desk.toml and validated offline. '
              'Run make down && make up to apply.', flush=True)


def _unlink_non_dir(path, label):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISDIR(info.st_mode):
        raise RuntimeError(f'{label} must not be a directory')
    path.unlink()


def reset_research_config(command, root=ROOT):
    """Return to packaged image defaults, backing up an edited local override first."""
    directory = Path(root) / RESEARCH_CONFIG_DIR
    path = Path(root) / RESEARCH_CONFIG
    base_path = Path(root) / RESEARCH_CONFIG_BASE
    backup_path = Path(root) / RESEARCH_CONFIG_BACKUP
    merge_path = Path(root) / RESEARCH_CONFIG_MERGE
    if not _require_config_dir(directory, create=False) or not os.path.lexists(path):
        _unlink_non_dir(base_path, str(RESEARCH_CONFIG_BASE))
        _unlink_non_dir(merge_path, str(RESEARCH_CONFIG_MERGE))
        print('Already using packaged image defaults (no local override at '
              'config/x402_treazury/research_desk.toml).', flush=True)
        return
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        _unlink_non_dir(base_path, str(RESEARCH_CONFIG_BASE))
        _unlink_non_dir(merge_path, str(RESEARCH_CONFIG_MERGE))
        path.unlink()
        print('Removed symlink override at config/x402_treazury/research_desk.toml; x402_treazury will now use '
              'the packaged image default. Run make down && make up to apply.', flush=True)
        return
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError('config/x402_treazury/research_desk.toml must be a regular file')
    # Reject wrong-type companion directories before mutating the live override.
    for companion, label in ((base_path, str(RESEARCH_CONFIG_BASE)), (merge_path, str(RESEARCH_CONFIG_MERGE))):
        if os.path.lexists(companion) and stat.S_ISDIR(os.lstat(companion).st_mode):
            raise RuntimeError(f'{label} must not be a directory')
    saved = path.read_bytes()
    backup_needed = True
    try:
        backup_needed = saved != packaged_research_config(command)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError):
        backup_needed = True
    if backup_needed:
        mode = stat.S_IMODE(info.st_mode) or 0o644
        _write_atomic(backup_path, saved, mode=mode)
    path.unlink()
    _unlink_non_dir(base_path, str(RESEARCH_CONFIG_BASE))
    _unlink_non_dir(merge_path, str(RESEARCH_CONFIG_MERGE))
    if backup_needed:
        print('Saved previous local config to config/x402_treazury/research_desk.toml.bak.', flush=True)
    print('Removed local override config/x402_treazury/research_desk.toml; x402_treazury will now use the '
          'packaged image default. Run make down && make up to apply.', flush=True)
