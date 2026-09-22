# D8 Stage II scoring weight sensitivity

This experiment reruns LG+CS and JBC on the archived 108 skeletons and 336 fixed-L2 requests. It contains the original setting and 12 individual weight changes. Parent geometry, eligible candidates, conflicts, counts and search budgets are fixed. Local quality weights are renormalized to sum to one after each change.

## Files

- `settings.json`: all original and changed weights.
- `request_results.csv`: 8,736 method-request records (13 settings × 336 requests × 2 methods). Repeated settings are not independent samples.
- `selections.jsonl`: selected candidate identifiers, resolved in the matching comparison context of the data/code package.
- `summary.csv` and `summary.json`: paired comparisons and configuration retention for all 13 settings.
- `paired_differences.csv`: JBC minus LG+CS for each matched request.
- `run_sensitivity.py` and `analyze.py`: selection and analysis scripts.

## Reproduction

Use the Python environment of the Paper A data/code package, with NumPy available. Pass the package root containing `code` and `data/comparison_contexts`. The output directory must be new.

```shell
python run_sensitivity.py --package /path/to/PaperA_Data_Code_20260920 --output /path/to/new_results
python analyze.py --results /path/to/new_results
```

The scripts temporarily change the scorer in memory and do not edit package source files. The original setting is checked against archived objective components. Compatibility is checked against the fixed conflict graph; this experiment does not regenerate candidate geometry.

## Fields and analysis

`score` uses the weights of the current setting; `reference_score` uses the original weights. `reference_score_change` is relative to the same method and request under the original setting. `configuration_same` compares child geometry and attachments, not candidate labels. `changed_parents` counts parents whose child configuration changed. `B` is the child count and `U` the number of parents with children. `total` and `peak` are unweighted co-travel terms. `complete` checks counts and parent coverage; `conflict_edges` counts selected incompatibilities. Search nodes, budget flags and selection-only wall times are also retained.

Summary wins/ties/losses compare JBC with LG+CS (tie tolerance 1e-10). Paired differences are summarized by the median within each skeleton and then the median across 108 skeletons. Intervals use 2,000 whole-skeleton bootstrap resamples with seed 20260922. `reference_*` columns use the original weights for both methods. Method-specific `*_same_percent` compares complete configurations with the original setting. Raw values retain computational precision; manuscript values are rounded.

All 12 changed settings are reported. Under the changed objective, JBC has 280–285 wins and no losses per setting. Under the original objective, four settings include 2–5 reversed requests, with maximum reversal magnitude 0.002515. All skeleton-level median differences remain positive under both scoring references.
