# Structure Generation of Interlocking Floral Patterns

This package records compositional relationships in the studied floral scrolls and provides editable structures for analysis, redesign and appearance generation. It contains the six procedural prototypes, generated geometry, paired images, evaluation observations and the code used for the two-stage selection method.

## Download the data

Source code, parameters, small indexes and evaluation records are tracked in this repository. Large files are distributed as two assets in [Releases](https://github.com/tomatot3/Structure-Generation-of-Interlocking-Floral-Patterns/releases):

| Download | Contents |
| --- | --- |
| `PaperA_Generated_Dataset_1128_Structures_500_Pairs_v1.0.0.zip` | 1,128 structural assets and 500 structure–rendering pairs, with indexes and an offline preview |
| `PaperA_Experiment_Reproduction_Data_v1.0.0.zip` | 108 comparison contexts with candidate inventories and archived method results |

Download the first archive to browse the collection or run the website. Download the second to recompute the result summaries and rerun the selector comparisons. Extract the archives directly into the repository root, merging their `data/` folders with the existing folder. The 118 source-annotation SVGs and their embedded source images are excluded from both archives and this repository.

## Contents

| Directory | Contents |
| --- | --- |
| `data/structural_assets/` | 1,128 distinct structures in semantic SVG, geometric JSON and PNG; 1,140 case records with seeds and controls |
| `data/paired_renderings/` | 500 structure–rendering pairs with matching filenames, case links and the submitted prompt |
| `data/comparison_contexts/` | 108 fixed parent layouts, complete candidate inventories and conflict graphs |
| `data/evaluation/` | Stage I and II results, density and seed experiments, robustness results and individual ratings |
| `data/parameters/` | Archived numerical priors and selection settings |
| `code/` | New-seed generation, archived-case reproduction, asset export, evaluation and comparison entry points |
| `source_materials/` | Source metadata for 118 annotations; annotation SVGs and embedded reference images are retained locally |
| `reproduction/` | Recomputed paper results and a concise record of package checks |
| `docs/` | Data dictionary, rendering protocol and release notes |

Open **[preview.html](preview.html)** to browse the 500 pairs in a horizontal layout. The page works offline.

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
python code/export_svg.py --asset A001 --output results/A001.svg
python code/generate.py --case A091 --compare-archive --output results/generated_A091
python code/compare_selectors.py --case C019 --output results/C019_selectors
```

Generation and comparison commands create new output directories. Choose a new directory for a repeat run. All inputs are resolved relative to the package, so the scripts can also be called from another working directory.

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

The 500 new pairs form a reusable asset collection. The human rendering evaluation used a separate set of 30 images and five evaluators. Its 150 individual rating records are retained in D3. The 54-structure evaluation has 270 records in D1.

## Reproduction and release

The package was checked with Python 3.12.14, NumPy 2.3.5 and Pillow 12.3.0 on Windows. The packaged selectors reproduce all 1,344 archived method–request results. The main statistical results can be recomputed with `summarize_results.py`; its output is included in `reproduction/main_results.json`.

Appearance images were produced with the built-in image generation service. The package includes the actual submitted prompt, structure inputs, outputs and generation dates. The service did not return a model ID or random seed. Structural generation and numerical comparisons run locally; new appearance generation requires access to an image service. See [the rendering protocol](docs/RENDERING_PROTOCOL.md).

Author/citation metadata and the license will be supplied separately. The 118 source-annotation SVGs and embedded reference images are not included in this repository. Their existing bibliographic and source metadata are retained in `source_materials/index.json`; figure-level sources are listed in `docs/SOURCE_INDEX.md`.

The directory is arranged for a GitHub repository. `.gitignore` excludes large downloaded asset folders, environments, caches, local run outputs and ZIP archives. `.gitattributes` keeps text line endings consistent and treats PNGs as binary files. See [GitHub upload instructions](docs/GITHUB.md).
