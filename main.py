import sys
import os
from pathlib import Path
import traceback

if __name__ == '__main__':
    try:
        from studio.app import main
        sys.exit(main())
    except Exception:
        folder = Path(os.environ.get('FABRIC_STUDIO_DATA') or Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'FabricLabelStudio')
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'startup-error.log').write_text(traceback.format_exc(), 'utf-8')
        raise
