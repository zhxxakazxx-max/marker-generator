"""Validate ZIP integrity and run the extracted EXE with no development PATH."""
from pathlib import Path
import os
import tempfile
import subprocess
import zipfile

root = Path(__file__).resolve().parents[1]
for name in ['FabricLabelStudio-Windows-x64.zip', 'FabricLabelStudio-Source.zip']:
    with zipfile.ZipFile(root / 'release' / name) as archive:
        assert archive.testzip() is None, 'Damaged archive'
        assert not any(Path(p).name in ['settings.json', 'jobs.json'] for p in archive.namelist())
with tempfile.TemporaryDirectory(prefix='FabricLabelStudio-release-check-') as temp:
    with zipfile.ZipFile(root / 'release/FabricLabelStudio-Windows-x64.zip') as archive:
        archive.extractall(temp)
    package = Path(temp) / 'FabricLabelStudio'
    env = os.environ.copy()
    env['FABRIC_STUDIO_DATA'] = str(Path(temp) / 'user-data')
    env['PATH'] = str(Path(os.environ['WINDIR']) / 'System32')
    env.pop('PYTHONPATH', None)
    result = subprocess.run([str(package / 'FabricLabelStudio.exe'), '--smoke-test'],
                            cwd=package, env=env, timeout=35)
    assert result.returncode == 0, f'Packaged startup failed: {result.returncode}'
print('PASS: ZIP CRCs, no saved credentials/jobs, extracted Windows EXE startup without development PATH.')
