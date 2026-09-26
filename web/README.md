# Floral Scroll Atlas website

The local website provides prototype previews, controlled branch generation, linked hierarchy highlighting, editable comparisons, a 500-pair gallery, and the original direct structural editor. The default interface is Chinese, with an English toggle for the main website.

The numerical generator is the existing code in `code/`. Each job runs in a separate Python process. A SQLite queue stores task states and one worker processes them at a time. The queue and generator run locally without a separate database service.

## Start

Requires Python 3.12, Node 20.19+ or 22.12+, pnpm, and Inkscape on PATH or supplied by absolute path.

```bash
python web/manage.py install
cd web/frontend
pnpm install --frozen-lockfile
pnpm run build
cd ../..
python web/manage.py thumbnails
python web/manage.py start --inkscape inkscape
```

Open `http://127.0.0.1:8976`. With an Inkscape installation outside PATH, replace `inkscape` with the executable path. That path is remembered in the ignored local settings file. `--port` selects another local port.

```bash
python web/manage.py status
python web/manage.py stop
```

The launcher preserves stdout, stderr and the process ID under `web/.runtime`. It does not open a public tunnel. Start and stop apply only to this website. Generated results, logs, SQLite data, installed Python dependencies and thumbnail caches stay under `web/.runtime` and are excluded from Git.

For frontend development, keep the backend running, then run `pnpm dev` in `web/frontend`. Vite forwards API requests to the backend on port 8976.

## What the controls do

- **Choose a prototype** displays only its main vine and flower sites. **Generate branches** runs the six-prototype production chain with the displayed variant, density and seed. The advanced prescribed-count mode uses the archived count profile. Hierarchy controls appear after generation.
- **Structure comparison** has separate parameters and generation buttons for A and B. Each side can also use an existing gallery structure, a recent generation, an edited version, or a local image. Local images stay in the browser and are used for visual comparison only.
- **Keep A's floral configuration** preserves the actual main-vine, flower-site and flower-support geometry from A when generating B. For an archived gallery example, the service first regenerates its recorded case to obtain the complete upstream snapshot. This option is unavailable for manually edited structures and local images.
- Clicking a parent highlights it and its children. Clicking a child highlights its parent. A flower site and its support path share their flower identifier. The role legend isolates each category.
- The collection has 500 pairs with unchanged original numbering. SVG, JSON and parameter downloads link back to the canonical structural asset.
- **Edit structure** opens the direct editor used for manual corrections. Drag roots, tips and Bézier handles; children follow changes to their parent. Add or delete branches, define root intervals, tip regions, curve envelopes and forbidden regions, and undo or redo edits. Main vines, flowers and support paths remain fixed. Save a version and download SVG, PNG or the editable JSON session. Saved versions can be selected for comparison.

## Voluntary edit submissions

Saving a personal version and submitting research data are separate actions. The submission checkbox starts unchecked. Only checking it and selecting **Submit for improvement** copies the original structure, edited structure, generation parameters and edit records into the feedback collection. An optional note can explain the edit. Submission does not change the current generator parameters.

Private drafts are stored in `web/.runtime/editor/sessions/`; the anonymous browser cookie controls access. Keep downloaded JSON copies if clearing browser data. Voluntary submissions are stored separately in `web/.runtime/editor/feedback/`, one folder per submission. Each includes `before.json`, `after.json`, `edit_session.json`, `parameters.json` and `submission.json`. This runtime folder is excluded from Git.

For later parameter research, export submitted edits only:

```bash
python web/scripts/export_feedback.py
```

This creates `web/.runtime/feedback_review.csv` with added/deleted branches, root and tip displacement, control-point changes, mount changes and notes. It reads only the explicit feedback collection. Review the submitted geometry and constraints before using cases for parameter estimation. The script does not fit or overwrite parameters, and these user edits are separate from the paper's existing evaluation data.

The displayed structure uses an unclipped conditioning view; downloaded SVGs retain the original semantic export. Appearance generation uses the already completed image collection. The website does not invoke a paid image API.

## Research introduction

The bilingual Research page introduces the cultural purpose of recording composition, then explains the SW families using flower position, connection origin and complete flower-bearing paths. Its terminology follows manuscript Section 2.2.3: SW1 crest–trough, SW2 axial flower-passing, and SW3 tangential flower-bearing. Six configuration diagrams can highlight the vine, flowers or their connecting paths; each links to its corresponding studio prototype.

`scripts/build_research_diagrams.py` extracts these diagrams from the first archived pair of each prototype. It preserves the original vine, flower and support coordinates in `frontend/public/research/configurations.json`, with source asset identifiers. The page omits ordinary branches from these explanatory diagrams. Its appearance example is the existing `sw1-C-01` pair. Rebuild the frontend after changing the page or diagram data.

## Implementation

`backend/app.py` exposes the API and durable single-worker queue. `backend/generate_task.py` calls the original generation functions and checks the actual output geometry before completing a task. `frontend/src/AppV2.tsx` contains the working surfaces; `StructureView.tsx` renders interactive semantic SVGs. `backend/editor_api.py` connects the reused editor in `editor/` to generated assets. `backend/legacy_editor_core.py` retains its geometry and attachment validation. `scripts/build_thumbnails.py` derives browsing thumbnails without altering the original images.

For optional temporary access from another device, the Windows tunnel helper is documented in [CLOUDFLARE.md](CLOUDFLARE.md).
