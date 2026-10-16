# Windows portable distribution. Qt remains in separate replaceable libraries.
from pathlib import Path
root = Path(SPECPATH)
a = Analysis(['main.py'], pathex=[str(root)], binaries=[],
             datas=[(str(root / 'assets'), 'assets')],
             hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtWebEngineCore', 'tkinter'],
             noarchive=False)
# Qt uses Windows' unversioned ICU API. Do not bundle unrelated Poppler/libheif
# DLLs found on the build host PATH in place of Windows 10/11 system libraries.
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in {'icuuc.dll', 'icudt78.dll', 'ucrtbase.dll'}
              and not Path(entry[0]).name.lower().startswith('api-ms-')]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='FabricLabelStudio',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='FabricLabelStudio')
