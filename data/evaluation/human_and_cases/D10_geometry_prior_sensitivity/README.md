# D10 Geometry-prior width sensitivity

The experiment used six prototypes, three fixed seeds and parent-shape prior-width factors of 0.8, 1.0 and 1.2: 54 runs and 18 matched inputs per factor. All runs completed and passed independent geometry checks.

Public files include `summary.json`, `summary_by_condition.csv`, `summary_by_prototype.csv`, `prior_width_*.json`, perturbation and run settings, and three scripts. Individual generated structures, case metrics and paired changes are retained in the local experiment archive.

To regenerate cases from the public code and prior settings, run:

```text
python scripts/run_geometry_prior_experiment_20260923.py --repo PATH_TO_REPOSITORY --output NEW_OUTPUT_DIRECTORY
```

The analysis and plotting scripts can then be run on that result directory. The manuscript summarizes the method and results in Supplementary Information S9.
