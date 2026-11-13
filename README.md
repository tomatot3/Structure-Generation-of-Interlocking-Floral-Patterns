# StructVine

This repository accompanies *Compositional modeling and controlled structural generation of single-wave floral scroll borders*. StructVine uses six procedural prototypes to generate editable floral-scroll structures with controlled branch layouts.

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

A new structure can be generated with the code and inputs in this repository. Download the archives below when you need the published data or archived comparison cases.

## Paper data and editable resources

| Material | Location |
| --- | --- |
| Stage I and II comparisons, branch-count and density experiments, and seed variation | [Evaluation tables](data/evaluation/) |
| Individual scores, geometric case statistics, runtime summaries, rating agreement and Stage II weight sensitivity | [Supplementary Data D1, D3, D4, D6, D7 and D8](data/evaluation/human_and_cases/) |
| Source records and 121 vector annotations with the embedded source images removed | [Supplementary Data D9](source_materials/) |
| Geometry-prior sensitivity results and SW1-C ceramic-border editing case | [Supplementary Data D10 and D11](archives/PaperA_Supplementary_Data.zip) |
| 1,128 editable structures, of which 500 are paired with renderings | [Asset download](archives/generated_assets_20261101/) · [Structure index](data/structural_assets/) · [Pair index](data/paired_renderings/) |

Run `python code/download_assets.py` to download and assemble the structure and rendering archive. Open [preview.html](preview.html) after extraction to browse the pairs offline. The separate 30-image appearance evaluation is listed in D3. The [rendering procedure](docs/RENDERING_PROTOCOL.md) documents the image service and prompt.

### Check the numerical comparisons

The [Stage II comparison input archive](archives/PaperA_StageII_Comparison_Inputs.zip) contains the shared candidates and comparison scores for 108 parent layouts and 336 fixed-L2 requests. Download the ZIP and extract it into the repository root before running the comparison commands.

```bash
python -m zipfile -e archives/PaperA_StageII_Comparison_Inputs.zip .
python code/compare_selectors.py --case C019 --output results/C019_selectors
python code/summarize_results.py --output results/main_results.json
```

See the [data dictionary](docs/DATA_DICTIONARY.md) for metric definitions and [D8](data/evaluation/human_and_cases/D8_weight_sensitivity/) for the weight-sensitivity analysis. The comparison ZIP and generated-asset parts use Git LFS.

## Design workbench

[tomatot3.cc](https://tomatot3.cc) provides structural generation and editing, grouped appearance editing and ceramic previews. See [web/](web/) for the implementation. D11 contains the SW1-C input, before-and-after grouped SVGs, the repeatable border and the two views of the plate in Figure 13c.

## Licensing

Original project code uses [MIT](LICENSE). Author-created structural and numerical datasets use [CC BY 4.0](LICENSE-DATA). See [the scope and attribution instructions](docs/LICENSING.md) for covered files. Source images and source-derived tracings, rendered appearance images, and third-party components are not automatically covered by the structural-data license.
