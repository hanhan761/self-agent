"""Run the installed yun control plane with hidden, pinned Windows subprocesses."""
import os
import pathlib
import subprocess
import sys

skill = pathlib.Path.home() / '.codex' / 'skills' / 'yun' / 'scripts'
sys.path.insert(0, str(skill))
import yunctl

def hidden(argv, *, capture=False, dry_run=False, display=None, input_text=None):
    args = [str(x) for x in argv]
    if os.name == 'nt':
        binaries = pathlib.Path('C:/Program Files/Git/usr/bin')
        name = pathlib.Path(args[0]).name.removesuffix('.exe')
        if name in ('ssh', 'scp', 'sftp', 'ssh-keygen', 'ssh-keyscan'):
            candidate = binaries / (name + '.exe')
            if candidate.is_file():
                args[0] = str(candidate)
    if dry_run:
        return subprocess.CompletedProcess(args, 0, '', '')
    result = subprocess.run(args, input=input_text, capture_output=True, text=True,
                            encoding='utf-8', errors='replace',
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if not capture:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
    return result

yunctl.run_external = hidden
if __name__ == '__main__':
    raise SystemExit(yunctl.main())
