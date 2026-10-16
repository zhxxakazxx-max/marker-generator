# Fabric Label Studio / 成分唛工作台

Windows 10/11 x64 desktop app for generating size-free fabric-composition label photographs.

## Run the Windows package

1. Extract the whole ZIP. Keep `FabricLabelStudio.exe` next to its `_internal` folder.
2. Double-click `FabricLabelStudio.exe`.
3. Open **API & models**, paste your API key, choose the provider and models, and save.
4. In **Create**, select one or more compositions and fabric colors. Add them to the queue.
5. In **Review**, click **Start queue**. Inspect each image, then **Approve** or **Regenerate**.
6. Click **Export approved** to save approved PNGs and a composition manifest.

## Included

- 119 validated composition presets from column C of your workbook; original Chinese labels retained.
- 12 original fabric/color reference images extracted from the workbook.
- Custom fiber/percentage editor, Chinese/English paste parsing, and Excel column C import.
- 1–4 parallel generation jobs, persistent queue, pause, separate regeneration versions.
- OpenAI, OpenAI-compatible image-edit endpoints, and native Google Gemini.
- Editable image and text model IDs, API model discovery, optional AI composition interpretation.
- User-scoped Windows DPAPI encryption for saved API keys.

The first photograph defines label placement, dark lettering, cream label, fabric and stitching. Every generation prompt excludes clothing sizes and specifies composition lines followed by `Made in China`. Blends use one line per component. AI images can vary in typography, spelling, texture and color; inspect them before approving. The included size-free example is labeled as an example, not a generated result for another composition.

Rows C48 and C107 include `PU皮革` without a percentage. They are retained as review errors and not guessed. Open **Rows needing correction** to inspect them.

## API compatibility and data

Model IDs can be selected or typed. A text-only model cannot generate images. Compatible providers must implement the supported REST endpoints and reference-image inputs; not every provider/protocol is supported. Model availability depends on your account. Gemini uses its default image options when OpenAI-style pixel settings are selected. API charges are billed by your provider. No key is included in either package.

App data is stored in `%LOCALAPPDATA%\FabricLabelStudio`. It contains encrypted settings, job records, imported references and generated images. Approved exports contain images and composition metadata, never API keys. References and composition data are sent only when you invoke the configured provider. Jobs do not start automatically when the app reopens. Pause stops new requests while active requests finish. Failed requests pause the queue and are not automatically retried. Keep the app open until active requests finish.

## Build from source

Use Python 3.14 x64 on Windows. Create a virtual environment and install `requirements.txt`. Run `python -m unittest discover -s tests -v`, then `python -m PyInstaller --noconfirm FabricLabelStudio.spec`. Or run `build.ps1 -Python <path-to-python.exe>`.

The source includes parser/storage tests, mocked provider tests, and real Qt workflow tests. The release passed 33 automated tests and a packaged startup check. Live calls with your API account have not been exercised because no customer key was supplied.

See `docs/QUICK_START.zh-CN.md`, `docs/API.md`, and `docs/CATALOG.md`.
