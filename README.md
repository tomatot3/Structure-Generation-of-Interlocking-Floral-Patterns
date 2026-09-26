# Structure Generation of Interlocking Floral Patterns

This repository provides six procedural prototypes, the two-stage structural generator, and reusable floral-scroll assets. It includes structure editing, geometric export and a website for exploring the generated collection.

## Contents

| Directory | Contents |
| --- | --- |
| `code/` | Core generation, geometry checks, asset export and dataset utilities |
| `code/inputs/` | Materialized prototype inputs, numerical priors and control settings |
| `data/parameters/` | Reference copies of the numerical priors and selection settings |
| `data/structural_assets/` | Indexes and recorded controls for 1,128 distinct structures; asset files are in the dataset ZIP |
| `data/paired_renderings/` | Links and submitted prompt for 500 structure–rendering pairs; images are in the dataset ZIP |
| `data/manual_corrections/` | 25 before/after correction images with an offline preview |
| `source_materials/` | 118 editable source-annotation SVGs and source metadata |
| `web/` | Interactive generation, hierarchy exploration, editing and paired-image browsing |
| `docs/` | Code map, data dictionary, rendering protocol and source index |

Download [`PaperA_Generated_Dataset_1128_Structures_500_Pairs.zip`](archives/PaperA_Generated_Dataset_1128_Structures_500_Pairs.zip) and extract it into the repository root. The archive includes the structural assets, paired images and an offline `preview.html`. Git LFS is required when cloning the archive.

## Quick start

Use Python 3.12. Run these commands from the repository root; CPU execution is sufficient.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r code/requirements.txt
python code/generate.py --prototype SW1-C --seed 20260920 --density medium --output results/new_structure
```

Choose a new output directory for each run. Input paths are resolved relative to the repository.

Generation accepts six prototype labels, a production seed, a main-vine variant (`expanded`, `compact` or `swept`) and a density (`simple`, `medium` or `rich`). Repeat `--seed` for a batch. Add `--control exact` for the prescribed-count profile.

Each run saves geometric JSON, a semantic SVG and an unlabelled conditioning SVG, along with its parameters and geometry checks. To export a conditioning PNG, install Inkscape and add `--inkscape inkscape` or its executable path. See [the code map](docs/CODE_MAP.md) for the full generation path and output schema.

Recorded assets can also be regenerated using `--case` with a case ID from `data/structural_assets/case_records.json`. Use `--group density`, `--group exact` or `--group seed` to regenerate a complete recorded group. The optional `--compare-archive` checks the regenerated geometry against the corresponding extracted asset.

For the interactive generator, editor and gallery, follow [the website instructions](web/README.md).

## Using the assets

The collection contains 1,128 distinct structures and 1,140 generation records. Twelve records share geometry with another record; use `asset_id` when joining records to asset files. Seeds and controls are retained in `case_records.json`.

The 500 pairs link to 500 distinct assets. Structure and rendering images share a filename, such as `sw1-A-01.png`. `pairs.csv` links each pair to its recorded case and canonical asset. SW1-A and SW1-B have 84 pairs each; the other four prototypes have 83 each.

Coordinates are normalized by repeat width. Geometry, roles and parent attachments are stored in `structure.json`; semantic SVGs retain object identifiers and role attributes. See [the data dictionary](docs/DATA_DICTIONARY.md). After extracting the dataset, `python code/check_dataset.py` checks paired images and their structural-asset links.

The local generation pipeline exports conditioning inputs. The completed appearance images and submitted prompt are included; new appearance generation uses an external image service. See [the rendering protocol](docs/RENDERING_PROTOCOL.md).

Source annotations are in `source_materials/role_annotations/`, with their existing metadata in `source_materials/index.json` and figure-level references in [the source index](docs/SOURCE_INDEX.md).

## Repository information

The generation dependencies are listed in `code/requirements.txt`. Author/citation metadata and the license will be supplied separately. The dataset ZIP is tracked with Git LFS; extracted asset files, environments and local run outputs are excluded from Git. See [the repository data layout](docs/GITHUB.md).
