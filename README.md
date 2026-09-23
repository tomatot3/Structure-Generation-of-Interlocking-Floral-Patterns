# Structure Generation of Interlocking Floral Patterns

This repository records compositional relationships in the studied floral scrolls and provides the six procedural prototypes, source annotations and code used for the two-stage selection method. The generated structure and rendering collection is available as a Git LFS archive.

## Data and code

Download [`PaperA_Generated_Dataset_1128_Structures_500_Pairs.zip`](archives/PaperA_Generated_Dataset_1128_Structures_500_Pairs.zip) for 1,128 generated structures, 500 structure–rendering pairs and an offline preview. Git LFS is required when cloning the archive. Source code, parameters, summary results and 118 source-annotation SVGs without embedded source images are also available here. Individual ratings and detailed experimental records remain in the local research archive.

## Contents

| Directory | Contents |
| --- | --- |
| `data/structural_assets/` (dataset ZIP) | 1,128 distinct structures in semantic SVG, geometric JSON and PNG; 1,140 case records with seeds and controls |
| `data/paired_renderings/` (dataset ZIP) | 500 structure–rendering pairs with matching filenames, case links and the submitted prompt |
| `data/comparison_contexts/` (local archive) | 108 fixed parent layouts, complete candidate inventories and conflict graphs |
| `data/evaluation/` | Published summaries, settings and analysis scripts |
| `data/parameters/` | Archived numerical priors and selection settings |
| `data/manual_corrections/` | 25 before/after comparison images of manual corrections, with an offline preview |
| `code/` | New-seed generation, archived-case reproduction, asset export, evaluation and comparison entry points |
| `source_materials/` | 118 editable source-annotation SVGs without embedded source images, with the existing source index |
| `reproduction/` | Recomputed paper results and a concise record of package checks |
| `docs/` | Data dictionary, rendering protocol and release notes |

Extract the dataset ZIP into the repository root to use the 500-pair offline preview.

The interactive website is implemented in **[web/](web/README.md)**. It includes new structure generation, linked role highlighting, fixed-floral-configuration comparisons, the paired collection and downloads. Start it locally using the instructions there. A Cloudflare Quick Tunnel is available for temporary testing; see [the deployment notes](web/CLOUDFLARE.md).

## Quick start

Use Python 3.12. Run these commands from the package directory. CPU execution is sufficient.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r code/requirements.txt
python code/generate.py --prototype SW1-C --seed 20260920 --density medium --output results/new_structure
```

Generation and comparison commands create new output directories. Choose a new directory for a repeat run. All inputs are resolved relative to the package, so the scripts can also be called from another working directory.
Archived-case export and selector comparisons require the comparison and structural-asset folders retained in the local research archive.

New generation accepts six prototype labels, a production seed, a main-vine variant and a density level. Use repeated `--seed` arguments for a batch. Add `--control exact` for the prescribed-count profile. Each successful run saves geometric JSON, a semantic SVG and an unlabelled conditioning SVG. For a conditioning PNG, install Inkscape and add `--inkscape inkscape` or its executable path.

The complete structural path and its source files are listed in [the code map](docs/CODE_MAP.md). It starts from the supplied procedural prototypes and priors. It generates new main-vine, flower/support and ordinary-branch geometry, then performs both selection stages and independent geometry checks.

To rerun all 336 Stage II requests across the four methods:

```bash
python code/compare_selectors.py --all --output results/all_selectors
```

To rerun the compatible greedy parent-layout control for one context:

```bash
python code/compare_parent_layout.py --case C019 --output results/C019_parent
```

To regenerate all cases in a group, use `generate.py --group density`, `--group exact` or `--group seed`, followed by `--output`. These groups contain 540, 540 and 60 records. Individual case IDs can be supplied with repeated `--case` options. The script uses the recorded seeds and the appropriate control profile, exports an SVG, and checks the generated geometry.

## Using the data

Pairs have the same filename in `structures/` and `renderings/`, for example `sw1-A-01.png`. `pairs.csv` links each pair to its original case and canonical structural asset. The pair counts are 84 for SW1-A and SW1-B, and 83 for each of SW1-C, SW2-A, SW3-A and SW3-B.

`case_records.json` retains all 1,140 experimental identities. Twelve records share geometry with another record, leaving 1,128 distinct assets. Use `asset_id` when joining records to files. The 500 selected pairs link to 500 distinct assets.

Coordinates are normalized by repeat width. Geometry, roles and parent attachments are stored separately in `structure.json`. SVG files retain object identifiers and role attributes. See [the data dictionary](docs/DATA_DICTIONARY.md) for the schema and coordinate conventions.

The 500 pairs form a reusable public asset collection. The separate 30-image rendering evaluation and 54-structure evaluation are reported as manuscript summaries; their individual rating records are retained locally.

The repository retains the ordinal-agreement analysis script and summary statistics. Settings, summaries and scripts for Stage II weight sensitivity and geometry-prior sensitivity are in `data/evaluation/human_and_cases/`.

## Reproduction and release

The original package was checked with Python 3.12.14, NumPy 2.3.5 and Pillow 12.3.0 on Windows. The main statistical summaries are in `reproduction/main_results.json`; detailed comparison inventories are retained locally.

Appearance images were produced with the built-in image generation service. The package includes the actual submitted prompt, structure inputs, outputs and generation dates. The service did not return a model ID or random seed. Structural generation and numerical comparisons run locally; new appearance generation requires access to an image service. See [the rendering protocol](docs/RENDERING_PROTOCOL.md).

Author/citation metadata and the license will be supplied separately. The 118 source-annotation SVGs are included without embedded source images in `source_materials/role_annotations/`. Their existing bibliographic and source metadata are retained in `source_materials/index.json`; figure-level sources are listed in `docs/SOURCE_INDEX.md`.

The dataset ZIP is tracked with Git LFS. `.gitignore` excludes extracted asset folders, other ZIP archives, environments, caches and local run outputs. See [the data layout](docs/GITHUB.md).
