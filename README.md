# Structure Generation of Interlocking Floral Patterns

This repository records compositional relationships in the studied floral scrolls and provides the six procedural prototypes, source annotations, evaluation observations and code used for the two-stage selection method. Full generated geometry and paired images are retained in the local research archive.

## Data and code

Source code, parameters, evaluation records and 118 source-annotation SVGs without embedded source images are tracked in this repository. The complete collection of 1,128 generated structures and 500 structure–rendering pairs, together with the 108-context comparison archive, is retained in the project’s local research archive. The source annotations can be downloaded from `source_materials/role_annotations/`; geometry-prior sensitivity data are in `data/evaluation/human_and_cases/D10_geometry_prior_sensitivity/`.

## Contents

| Directory | Contents |
| --- | --- |
| `data/structural_assets/` (local archive) | 1,128 distinct structures in semantic SVG, geometric JSON and PNG; 1,140 case records with seeds and controls |
| `data/paired_renderings/` (local archive) | 500 structure–rendering pairs with matching filenames, case links and the submitted prompt |
| `data/comparison_contexts/` (local archive) | 108 fixed parent layouts, complete candidate inventories and conflict graphs |
| `data/evaluation/` | Stage I and II results, density and seed experiments, robustness results and individual ratings |
| `data/parameters/` | Archived numerical priors and selection settings |
| `data/manual_corrections/` | 25 before/after comparison images of manual corrections, with an offline preview |
| `code/` | New-seed generation, archived-case reproduction, asset export, evaluation and comparison entry points |
| `source_materials/` | 118 editable source-annotation SVGs without embedded source images, with the existing source index |
| `reproduction/` | Recomputed paper results and a concise record of package checks |
| `docs/` | Data dictionary, rendering protocol and release notes |

The 500-pair offline preview is retained with the local image archive.

The interactive website is implemented in **[web/](web/README.md)**. It includes new structure generation, linked role highlighting, fixed-floral-configuration comparisons, the paired collection and downloads. Start it locally using the instructions there. A Cloudflare Quick Tunnel is available for temporary testing; see [the deployment notes](web/CLOUDFLARE.md).

## Quick start

Use Python 3.12. Run these commands from the package directory. CPU execution is sufficient.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r code/requirements.txt
python code/generate.py --prototype SW1-C --seed 20260920 --density medium --output results/new_structure
python code/summarize_results.py --output results/main_results.json
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

The 500 new pairs form a reusable asset collection retained locally. The human rendering evaluation used a separate set of 30 images and five evaluators. Its 150 individual rating records are retained in D3. The 54-structure evaluation has 270 records in D1.

Reproduce ordinal agreement with `python data/evaluation/human_and_cases/analyze_rating_agreement.py`. D7 contains the estimates and image-level summaries. The settings, results and scripts for the Stage II weight-sensitivity analysis are in `data/evaluation/human_and_cases/D8_weight_sensitivity/`.

## Reproduction and release

The package was checked with Python 3.12.14, NumPy 2.3.5 and Pillow 12.3.0 on Windows. The packaged selectors reproduce all 1,344 archived method–request results. The main statistical results can be recomputed with `summarize_results.py`; its output is included in `reproduction/main_results.json`.

Appearance images were produced with the built-in image generation service. The package includes the actual submitted prompt, structure inputs, outputs and generation dates. The service did not return a model ID or random seed. Structural generation and numerical comparisons run locally; new appearance generation requires access to an image service. See [the rendering protocol](docs/RENDERING_PROTOCOL.md).

Author/citation metadata and the license will be supplied separately. The 118 source-annotation SVGs are included without embedded source images in `source_materials/role_annotations/`. Their existing bibliographic and source metadata are retained in `source_materials/index.json`; figure-level sources are listed in `docs/SOURCE_INDEX.md`.

The directory is arranged for a GitHub repository. `.gitignore` excludes large downloaded asset folders, environments, caches, local run outputs and ZIP archives. `.gitattributes` keeps text line endings consistent and treats PNGs as binary files. See [GitHub upload instructions](docs/GITHUB.md).
