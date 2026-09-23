# D8 Stage II weight sensitivity

The public files provide `settings.json`, aggregate results (`summary.csv`, `summary.json`) and the scripts `run_sensitivity.py` and `analyze.py`. The 108 fixed skeletons, selected candidates, request-level outcomes and paired differences are retained in the local experiment archive.

Six Stage II weights were varied individually by ±20% while candidate geometry, conflicts, counts and search budgets were fixed. The summaries describe configuration retention and paired objective differences for the original setting and 12 changed settings. To rerun the experiment, supply the full comparison-context archive as the package root required by `run_sensitivity.py`.
