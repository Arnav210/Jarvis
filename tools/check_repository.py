#!/usr/bin/env python3
"""Check publishable source and reachable Git history without reading private data."""
import argparse
import ast
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PRIVATE_ROOTS = {
    'data', 'Footage', 'Masks', 'VoiceProfiles', 'models', 'voices',
    'sam3', 'whisper.cpp', 'Depth-Anything-3', 'Jarvis-Web',
}
PRIVATE_SUFFIXES = {'.wav', '.mp3', '.mp4', '.m4a', '.flac', '.ogg', '.opus',
                    '.jpg', '.jpeg', '.png', '.npz', '.npy', '.onnx', '.bin',
                    '.task', '.pt', '.pth', '.pem', '.key', '.p12', '.pfx', '.log'}
PATTERNS = {
    'private key': rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
    'GitHub token': rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})',
    'API credential': rb'\bsk-(?:proj-)?[A-Za-z0-9_-]{30,}',
    'AWS access key': rb'\bAKIA[A-Z0-9]{16}\b',
    'Slack token': rb'\bxox[baprs]-[A-Za-z0-9-]{20,}',
    'credential in URL': rb'https?://[^\s/:@]+:[^\s/@]{5,}@',
    'literal credential assignment': rb'''(?im)^\s*[A-Z_]*(?:SECRET|PASSWORD|ACCESS_TOKEN|REFRESH_TOKEN|API_KEY|CLIENT_SECRET)\s*=\s*["'][^"'\r\n]{12,}["']''',
}


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def private_path(name):
    parts = pathlib.PurePosixPath(name).parts
    return (not parts or parts[0] in PRIVATE_ROOTS
            or any(x.startswith('.venv') or x == '__pycache__' or x.startswith('.env') for x in parts)
            or pathlib.PurePosixPath(name).suffix.lower() in PRIVATE_SUFFIXES
            or any(x in name for x in ['.before-', '.before_', '.backup-', '.bak-'])
            or name.endswith(('.save', '.bak', '.backup')))


def scan(label, body, errors):
    for kind, pattern in PATTERNS.items():
        for match in re.finditer(pattern, body):
            line = body.count(b'\n', 0, match.start()) + 1
            errors.add(f'{label}:{line}: possible {kind}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true', help='also inspect all reachable commits and blobs')
    args = parser.parse_args()
    errors = set()
    names = set(git('ls-files', '-z', '--cached', '--others', '--exclude-standard').decode().split('\0')) - {''}
    count = 0
    for name in sorted(names):
        f = ROOT / name
        if not f.exists():
            continue  # An already tracked deletion belongs in the next commit.
        if private_path(name):
            errors.add(f'{name}: private/generated path is eligible for Git')
            continue
        if f.is_symlink():
            errors.add(f'{name}: review symlink before publication')
            continue
        body = f.read_bytes()
        count += 1
        if len(body) > 1_000_000:
            errors.add(f'{name}: unexpectedly large source file')
        if b'\0' in body:
            errors.add(f'{name}: unexpected binary file')
        scan(name, body, errors)
        if name.endswith('.py'):
            try:
                tree = ast.parse(body, filename=name)
                for n in ast.walk(tree):
                    imports = ([n.module.split('.')[0]] if isinstance(n, ast.ImportFrom) and n.module else
                               [a.name.split('.')[0] for a in n.names] if isinstance(n, ast.Import) else [])
                    for module in imports:
                        local = module + '.py'
                        if (ROOT / local).is_file() and local not in names:
                            errors.add(f'{name}: local dependency {local} is excluded')
            except SyntaxError as exc:
                errors.add(f'{name}:{exc.lineno}: invalid Python syntax')
        if name.startswith('bin/') and body.startswith(b'#!/'):
            r = subprocess.run(['bash', '-n', str(f)], capture_output=True, text=True)
            if r.returncode:
                errors.add(f'{name}: invalid shell syntax')
    probes = ['data/captains-log/example.mp4', 'Footage/example.jpg', 'Masks/runs/example/manifest.json',
              'VoiceProfiles/example/profile.json', 'models/example.onnx', 'voices/example.onnx',
              '.venv-wake/example.py', 'docs/.env', 'systemd/user/example.key', 'tests/__pycache__/example.pyc']
    for name in probes:
        r = subprocess.run(['git', '-C', str(ROOT), 'check-ignore', '--quiet', '--no-index', name])
        if r.returncode != 0:
            errors.add(f'{name}: private-path exclusion failed')
    history_count = 0
    if args.history:
        # Scan every reachable tree for names, rather than only the first name
        # associated with each blob by rev-list --objects.
        for commit in git('rev-list', '--all').decode().splitlines():
            for name in git('ls-tree', '-rz', '--name-only', commit).decode().split('\0'):
                if name and private_path(name):
                    errors.add(f'history {commit[:10]}:{name}: private/generated path')
            scan('commit ' + commit[:10], git('cat-file', 'commit', commit), errors)
        for row in git('rev-list', '--objects', '--all').decode().splitlines():
            oid = row.split(' ', 1)[0]
            if git('cat-file', '-t', oid).strip() == b'blob':
                history_count += 1
                scan('history blob ' + oid[:10], git('cat-file', 'blob', oid), errors)
    for error in sorted(errors):
        print(error, file=sys.stderr)
    print(f'Checked {count} source files, {len(probes)} exclusions, {history_count} historical blobs; {len(errors)} issues.')
    print('Credential patterns are a useful check, not a guarantee that all secrets are detectable.')
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
