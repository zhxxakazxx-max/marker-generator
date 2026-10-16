"""Create distribution/source archives with explicit inputs, excluding local user data."""
from pathlib import Path
from importlib import metadata
import shutil
import sys
import urllib.request
import zipfile
import hashlib

root = Path(__file__).resolve().parents[1]
app = root / 'dist' / 'FabricLabelStudio'
if not (app / 'FabricLabelStudio.exe').is_file():
    raise SystemExit('Build the Windows application first.')
for name in ['README.md', 'LICENSE-NOTICES.md']:
    shutil.copy2(root / name, app / name)
shutil.copytree(root / 'docs', app / 'docs', dirs_exist_ok=True)
licenses = app / 'licenses'
licenses.mkdir(exist_ok=True)
if (root / 'licenses').is_dir():
    shutil.copytree(root / 'licenses', licenses, dirs_exist_ok=True)
for distribution in metadata.distributions():
    package_name = distribution.metadata['Name']
    for file in distribution.files or []:
        if any(word in file.name.lower() for word in ['license', 'copying', 'notice']) and '.dist-info' in str(file):
            source = Path(distribution.locate_file(file))
            if source.is_file():
                target = licenses / package_name / file.name
                target.parent.mkdir(exist_ok=True)
                shutil.copy2(source, target)
for filename, url in [
    ('LGPL-3.0.txt', 'https://raw.githubusercontent.com/qt/qtbase/dev/LICENSES/LGPL-3.0-only.txt'),
    ('GPL-3.0.txt', 'https://raw.githubusercontent.com/qt/qtbase/dev/LICENSES/GPL-3.0-only.txt'),
]:
    path = licenses / filename
    if not path.exists():
        with urllib.request.urlopen(url, timeout=30) as response:
            path.write_bytes(response.read())
pylicense = Path(sys.base_prefix) / 'LICENSE.txt'
if pylicense.exists():
    shutil.copy2(pylicense, licenses / 'Python-LICENSE.txt')
release = root / 'release'
release.mkdir(exist_ok=True)
portable = release / 'FabricLabelStudio-Windows-x64.zip'
with zipfile.ZipFile(portable, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(app.rglob('*')):
        if path.is_file():
            archive.write(path, path.relative_to(app.parent))
source_zip = release / 'FabricLabelStudio-Source.zip'
with zipfile.ZipFile(source_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for entry in ['studio', 'assets', 'docs', 'scripts', 'tests', 'licenses', 'main.py', 'requirements.txt',
                  'FabricLabelStudio.spec', 'build.ps1', 'README.md', 'LICENSE-NOTICES.md']:
        item = root / entry
        for path in sorted(item.rglob('*')) if item.is_dir() else [item]:
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                archive.write(path, Path('FabricLabelStudio-Source') / path.relative_to(root))
lines = []
for path in [portable, source_zip]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    lines.append(f'{digest}  {path.name}')
    print(f'{path.name}: {path.stat().st_size / 1024 / 1024:.1f} MB')
(release / 'SHA256SUMS.txt').write_text('\n'.join(lines) + '\n', 'utf-8')
