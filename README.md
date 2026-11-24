# Floral scroll structures and controlled generation

This repository accompanies *Modeling compositional relationships for controlled structural generation of single-wave floral scroll borders*. It provides six procedural prototypes, the two-stage structural generator, editable assets, source annotations and the structure and appearance editing workbench.

## Data downloads

| Archive | Contents | Extract into |
| --- | --- | --- |
| [Generated structures and paired renderings](https://github.com/tomatot3/Structure-Generation-of-Interlocking-Floral-Patterns/tree/main/archives/generated_assets_20261101) | 1,128 structures, 1,140 generation records and 500 structure–rendering pairs | Run `python code/download_assets.py` |
| [Figure S8 comparison example](archives/PaperA_StageII_Comparison_Inputs.zip) | C049 geometry and objective components for the two selected configurations | Any folder |
| [Supplementary Data D1–D11](https://github.com/tomatot3/Structure-Generation-of-Interlocking-Floral-Patterns/blob/main/archives/PaperA_Supplementary_Data.zip) | Ratings, weight and geometry-prior sensitivity results, 121 source annotations, and the ceramic-border case | Repository root; creates `Supplementary_Data/` |

The generated-asset ZIP is distributed in 50 MiB parts. Run `python code/download_assets.py` to download, assemble and extract it automatically. The other two ZIP files can be downloaded directly. The archive files and parts use Git LFS; install Git LFS before cloning to fetch them together. `git lfs pull` downloads the archive contents for an existing clone. Extracted assets and local user projects are not tracked in Git. The 121 image-free source SVGs and their index are also directly available in [`source_materials/`](source_materials/).

## Paper figures and supplementary data

The [figure and case index](docs/FIGURE_CASE_INDEX.csv) links the paper’s examples to archived IDs. C019 supplies the examples in Figures 4, 6 and 10. C044 is the Stage I example in Figure 9. The Figure 13 ceramic-border case starts from structure A452.

[Source records for Figures 2 and 3](docs/SOURCE_INDEX.md) follow Supplementary Tables S1 and S2 and the current bibliography. The [data dictionary](docs/DATA_DICTIONARY.md) identifies the files and averaging rules behind Tables 3 and 4. The [code map](docs/CODE_MAP.md) links the two stages to the implementation and numerical inputs.

## Quick start

Use Python 3.12. CPU execution is sufficient for structural generation.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r code/requirements.txt
python code/generate.py --prototype SW1-C --seed 20260920 --density medium --output results/new_structure
```

Generation accepts six prototype labels, a seed, a main-vine shape (`expanded`, `compact`, `swept`) and a density level (`simple`, `medium`, `rich`). Use repeated `--seed` arguments for a batch. Add `--control exact` for the prescribed-count profile. Each successful run exports geometric JSON and semantic and conditioning SVGs. For a conditioning PNG, install Inkscape and add `--inkscape inkscape` or its executable path. Choose a new output directory for each run.

After extracting the generated-asset archive, `python code/generate.py --case A091 --compare-archive --output results/A091` regenerates an archived case. Open `preview.html` to browse the 500 pairs offline. The generator does not require the generated-asset archive when creating a new structure from the packaged prototype inputs.

## Check the reported results

Run this command from the repository root to recompute Tables 3 and 4 from the public per-layout and per-request CSV files.

```bash
python code/summarize_results.py --output results/main_results.json
```

D8 contains the settings and per-request results behind the sensitivity comparison in Supplementary Table S19. D10 provides the 54 final structures, prior settings and paired metrics behind Supplementary Table S20 and Figures S16–S17.

## Contents and correspondence

| Location | Contents |
| --- | --- |
| `code/` | Generation, layout and BranchUnit comparisons, export and summary entry points |
| `data/structural_assets/` | Indexes for 1,128 distinct assets and 1,140 generation records; geometry and images supplied in the generated-asset archive |
| `data/paired_renderings/` | 500 pair records and the submitted prompt; images supplied in the generated-asset archive |
| `data/parameters/` | Numerical priors and selection settings |
| `data/evaluation/` | Archived numerical results and ratings; comparison inputs are in the separate archive |
| `source_materials/` | 121 source records and 121 vector annotations with embedded source images removed |
| `web/` | Structural generation and editing, appearance grouping and editing, and 3D ceramic previews |
| `docs/` | Code map, data dictionary, rendering procedure, source references and licensing scope |

The 500 pairs link to 500 distinct structural assets. Pair counts are 84 each for SW1-A and SW1-B, and 83 each for SW1-C, SW2-A, SW3-A and SW3-B. Use `asset_id` to join generation records to assets. The 30-image rendering evaluation is a separate dataset with five evaluators, supplied in D3; it is not an evaluation of the 500-pair collection.

The 500 paired renderings were generated with ChatGPT’s image-generation tool using the archived prompt. Each pair record identifies the input, output and generation route. Structural generation and numerical comparisons run locally. New appearance generation uses an external image service. See [the rendering procedure](docs/RENDERING_PROTOCOL.md).

## Interactive workbench and ceramic case

The public workbench is at [tomatot3.cc](https://tomatot3.cc). Follow [the website instructions](web/README.md) to run it locally after extracting the generated-asset archive. The appearance module at `/appearance/` imports structure-guided artwork, supports registration and region correction, and edits grouped vectors. Its application view maps the edited border onto plates, bowls and cups with a sea-and-dragon motif or a blank central area.

Supplementary Data D11 retain the paper's specific SW1-C editing example, initial and edited projects, grouped artwork, and the plate model, texture and two views used in Figure 13c. The current workbench code and the archived case materials are supplied separately. Runtime drafts and voluntary user submissions are excluded from this repository.

## Licensing

Original project code uses [MIT](LICENSE). Author-created structural and numerical datasets use [CC BY 4.0](LICENSE-DATA). See [the scope and attribution instructions](docs/LICENSING.md) for covered files. Source images and source-derived tracings, rendered appearance images, and third-party components are not automatically covered by the structural-data license.
