# Fabric Label Studio v1.3 / 成分唛工作台

Windows 10/11 x64 desktop app for generating size-free fabric-composition label photographs.

## Run the Windows package

1. Extract the whole ZIP. Keep `FabricLabelStudio.exe` next to its `_internal` folder.
2. Double-click `FabricLabelStudio.exe`.
3. Open **API & models**, paste your API key, choose the provider and models, and save.
4. In **Create**, select compositions and colors, or use **Queue all document combinations** after importing Excel. Adding all 119 × 12 pairs creates 1,428 queued jobs but does not start the API.
5. In **Review**, click **Start queue**. Inspect each image, then **Approve** or **Regenerate**. To regenerate several jobs, select their rows with Ctrl/Shift and click **Regenerate selected**.
6. Click **Export approved** to save approved PNGs and a composition manifest.

## Included

- 119 validated composition presets from column C of your workbook; original Chinese labels retained.
- 12 original fabric/color reference images extracted from the workbook.
- Custom fiber/percentage editor, Chinese/English paste parsing, and Excel column C import.
- One-click queuing for every valid document composition × all 12 document colors, with a count and maximum-attempt warning before jobs are added.
- 1–4 parallel generation jobs, persistent queue, pause, separate regeneration versions, and batch regeneration with Ctrl/Shift row selection.
- OpenAI, OpenAI-compatible image-edit endpoints, and native Google Gemini.
- Editable image and text model IDs, API model discovery, optional AI composition interpretation.
- User-scoped Windows DPAPI encryption for saved API keys.

The first photograph defines label placement, dark lettering, cream label, fabric and stitching. Every generation prompt excludes clothing sizes and specifies composition lines followed by `Made in China`. Blends use one line per component. AI images can vary in typography, spelling, texture and color; inspect them before approving. The included size-free example is labeled as an example, not a generated result for another composition.

Rows C48 and C107 include `PU皮革` without a percentage. They are retained as review errors and not guessed. Open **Rows needing correction** to inspect them.

## API compatibility and data

Model IDs can be selected or typed. A text-only model cannot generate images. Compatible providers must implement the supported REST endpoints and reference-image inputs; not every provider/protocol is supported. Model availability depends on your account. Gemini uses its default image options when OpenAI-style pixel settings are selected. API charges are billed by your provider. No key is included in either package.

App data is stored in `%LOCALAPPDATA%\FabricLabelStudio`. It contains encrypted settings, job records, imported references and generated images. Approved exports contain images and composition metadata, never API keys. References and composition data are sent only when you invoke the configured provider. Jobs do not start automatically when the app reopens.

In v1.1, generation requests start at least 10 seconds apart within the concurrency limit. HTTP 408/429/5xx, connection interruptions and timeouts trigger automatic retries on the same job, with at least 10 seconds after each failure and **3 attempts total**. The UI shows Retrying until the last attempt fails, then Failed and enables Regenerate. Exhausted transient failures do not stop other jobs. Configuration and unexpected errors pause immediately. Pause suspends dispatch and retries; Cancel queued also cancels waiting retries. Active requests finish. Attempt counts survive pause/reopen and only a new regeneration version receives a fresh budget. **Retry failed** queues new versions of failed/interrupted jobs and avoids duplicating existing retries. A retry can incur another provider charge. Failed counts include retained older versions. Keep the app open until active requests finish.

## Batch regeneration in v1.2

In **Review**, use Ctrl-click to select individual rows, Shift-click for a range, **Select all** for the whole list, or **Clear** to reset the selection. Optionally enter shared instructions in the existing feedback field, then click **Regenerate selected**. Nonempty feedback is applied to each new version; an empty field preserves each selected job's existing notes.

Failed, review, approved, cancelled and interrupted jobs can produce new versions. Queued, running and retrying jobs are skipped. A job is also skipped if it already has an immediate child version that is queued, running or retrying, preventing repeated clicks from duplicating pending work. Old images and statuses are retained. Each eligible job creates a new queued child with 0 attempts used and a fresh 3-attempt limit, following the same request spacing of at least 10 seconds introduced in v1.1.

The selection stays in place through list refreshes and the batch action. A banner reports how many new versions were queued and how many selected rows were skipped. If the queue is paused, click **Start**; a running queue picks up the new versions. See [批量重新生成说明](docs/BATCH_REGENERATE.zh-CN.md).

## All document combinations in v1.3

After importing column C, click **Queue all document combinations / 全部组合入队** to combine every valid composition with all 12 document colors. A confirmation dialog shows the exact image count and the maximum number of billable attempts. Confirming only adds jobs; API calls begin when you click **Start queue**. Generated and exported PNG files use `composition__color__short-job-id.png`, so files are readable and regenerated versions do not overwrite earlier images.

## Build from source

Use Python 3.12 or 3.14 x64 on Windows. Create a virtual environment and install `requirements.txt`. Run `python -m unittest discover -s tests -v`, then `python -m PyInstaller --noconfirm FabricLabelStudio.spec`. Or run `build.ps1 -Python <path-to-python.exe>`.

The source includes parser/storage tests, mocked provider tests, and real Qt workflow tests. Verification uses local fixtures and does not submit paid image requests. See [v1.2 batch regeneration and upgrade instructions](docs/BATCH_REGENERATE.zh-CN.md); [v1.1 queue retry notes](docs/QUEUE_FIX.zh-CN.md) describe the earlier update.

See `docs/QUICK_START.zh-CN.md`, `docs/API.md`, and `docs/CATALOG.md`.
