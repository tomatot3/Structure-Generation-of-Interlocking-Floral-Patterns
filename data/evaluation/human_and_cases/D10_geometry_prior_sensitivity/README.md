# Supplementary Data D10 Geometry-prior width sensitivity

The dataset covers six prototypes, three fixed seeds (20260923–20260925), and three prior-width factors (0.8, 1.0, 1.2): 54 runs and 18 matched inputs per perturbation. All runs completed and passed independent geometry checks. The main-vine form is expanded and density is medium.

Each marginal sample x was transformed as x′ = m + a(x − m), where m is its marginal median and a is the width factor. The unmodified prior is retained for a = 1. Nonnegative handle ratios and the absolute start angle are clipped at zero. Descriptor dependence, length and child-attachment priors, scoring, geometric constraints and search budgets remain unchanged. Candidates and complete outputs were regenerated for each condition.

`case_metrics.csv` reports all cases; `paired_changes.csv` records perturbation minus matched-default differences, and `summary_by_condition.csv` and `summary_by_prototype.csv` summarize the outputs. Ordinary-branch length is normalized by repeat width W. The root-coverage definition matches the main text. `prior_width_*.json` and `perturbations_*.json` retain the actual priors and clipping counts. `raw_cases/` contains the generated curves, parent layouts and fixed flower–vine inputs.

Regenerate with the released repository and its Python requirements:

```text
python scripts/run_geometry_prior_experiment_20260923.py --repo PATH_TO_REPOSITORY --output NEW_OUTPUT_DIRECTORY
```

Recompute descriptive summaries or figures from this dataset, or pass another result directory as the positional argument:

```text
python scripts/analyze_geometry_prior_experiment_20260923.py
python scripts/plot_geometry_prior_experiment_20260923.py
```

Plots require NumPy and Matplotlib. Points represent all paired prototype–seed inputs; interval marks are median/interquartile range, not confidence intervals. No significance test is used. Timings were recorded with four parallel CPU workers. Existing generation inputs and manuscript experiments were not overwritten.
