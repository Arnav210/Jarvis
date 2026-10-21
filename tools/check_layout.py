#!/usr/bin/env python3
"""Validate package imports and launcher/service source paths without hardware access."""
import ast
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
errors = []
count = 0

def module_exists(name):
    path = ROOT / 'src' / name.replace('.', '/')
    return path.with_suffix('.py').is_file() or (path / '__init__.py').is_file()

for path in [*(ROOT / 'src').rglob('*.py'), *(ROOT / 'tests').glob('*.py')]:
    count += 1
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
            if node.module.startswith('jarvis.'):
                base = ROOT / 'src' / node.module.replace('.', '/')
                if (base / '__init__.py').is_file():
                    names += [node.module + '.' + alias.name for alias in node.names]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            continue
        for name in names:
            if name.startswith('jarvis_') or name in {'gesture_analyzer', 'mediapipe_tracker', 'config'}:
                errors.append(f'{path.relative_to(ROOT)}:{node.lineno}: stale flat import {name}')
            if name == 'jarvis' or name.startswith('jarvis.'):
                if not module_exists(name):
                    errors.append(f'{path.relative_to(ROOT)}:{node.lineno}: missing package module {name}')

pattern = re.compile(r'(?:Jarvis/|\$project_dir/|\$\{JARVIS_HOME:-\$HOME/Jarvis\}/)([A-Za-z0-9_./-]+\.py)')
paths = [*(ROOT / 'bin').glob('*'), *(ROOT / 'systemd').rglob('*')]
installed = Path.home() / '.config/systemd/user'
if installed.exists():
    paths += [p for p in installed.rglob('*') if not p.is_symlink() and p.suffix in {'.service', '.conf'}]
for path in paths:
    if not path.is_file():
        continue
    for target in pattern.findall(path.read_text()):
        if not (ROOT / target).is_file():
            errors.append(f'{path}: missing entry point {target}')
for path in (ROOT / 'src').rglob('*.py'):
    if subprocess.run(['git', '-C', str(ROOT), 'check-ignore', '--quiet', '--no-index', str(path)]).returncode == 0:
        errors.append(f'{path.relative_to(ROOT)}: source excluded by Git')
for error in errors:
    print(error)
print(f'Checked {count} Python sources, package imports, source eligibility, and service/launcher paths; {len(errors)} issues.')
raise SystemExit(bool(errors))
