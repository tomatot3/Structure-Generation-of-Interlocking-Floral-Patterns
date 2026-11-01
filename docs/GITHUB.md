# Repository data layout

Repository: https://github.com/tomatot3/Structure-Generation-of-Interlocking-Floral-Patterns

Git tracks code, source annotations, numerical settings, indexes, evaluation results and website source. The ZIP archives and generated-asset parts under `archives/` use Git LFS.

- `generated_assets_20261101/`: the generated-data ZIP split into 50 MiB parts; `python code/download_assets.py` downloads, assembles and extracts it into the repository root.
- `PaperA_StageII_Comparison_Inputs.zip`: all 108 comparison contexts and the reference fixed-L2 objective table; extract into the repository root.
- `PaperA_Supplementary_Data.zip`: current D1–D11 and their reproduction instructions; extract into the repository root to create `Supplementary_Data/`.

The generated-data archive does not contain the repository's `dataset_summary.json` or `docs/` files. Extracting it therefore preserves the current resource descriptions. Its own description is in `README_DATASET.md`.

Environments, runtime projects, submitted edits, caches and local outputs stay outside Git. Source SVGs have their embedded source images removed. The 121 source records and their annotations are directly available in `source_materials/` and mirrored in Supplementary Data D9.
