# Marker Generator

Source code for the Windows fabric composition label generator, including Fabric Label Studio v1.3 and Fabric Label Batch Generator v1.0.

The desktop app creates fabric label images from composition presets or Excel column C, using 12 supplied fabric colors. It includes a persistent job queue, automatic retries, image review, batch regeneration, and approved-image export.

## Run from source

Use Python 3.12 x64 on Windows 10 or 11. In PowerShell, from this directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

For the batch generator:

```powershell
.\.venv\Scripts\python.exe batch_main.py
```

Configure your provider, API key, and models in Fabric Label Studio before generating images. The batch generator reads the same local settings. API requests may incur provider charges.

## Test and build

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\build.ps1 -Python .\.venv\Scripts\python.exe
.\build_batch.ps1 -Python .\.venv\Scripts\python.exe
```

The existing 61 tests use local fixtures and mocked providers. They do not submit paid image-generation requests.

## Source contents

| Path | Contents |
| --- | --- |
| `studio/` | Current application and batch-generator source |
| `main.py`, `batch_main.py` | Desktop and batch entry points |
| `assets/` | Required catalog, reference images, and 12 fabric colors |
| `tests/` | Existing regression tests |
| `scripts/`, `*.spec`, `build*.ps1` | Original verification and Windows packaging tools |
| `docs/` | Original usage and API documentation |
| `archive/original/` | Unchanged files from the original source ZIP |
| `archive/studio-v1.3/` | Unchanged files from the v1.3 source ZIP |
| `source-manifest.json` | SHA-256 hashes and paths for all 138 preserved source files |

The latest working source is at the repository root. The archived snapshots preserve earlier source; run the root entry points for the current version. The original current-version README is preserved at [docs/FABRIC_LABEL_STUDIO_README.md](docs/FABRIC_LABEL_STUDIO_README.md).

API keys, local job history, generated output, the original input workbook, installed dependencies, and compiled Windows binaries are excluded. App data stays in `%LOCALAPPDATA%\FabricLabelStudio`.

See [source provenance](docs/SOURCE_PROVENANCE.md), [Chinese quick start](docs/QUICK_START.zh-CN.md), [batch instructions](BATCH-README.txt), and [third-party notices](LICENSE-NOTICES.md). Original image rights and third-party licenses continue to apply.
