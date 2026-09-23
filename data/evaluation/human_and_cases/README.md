# Supplementary Data for Paper A

The data files accompany Supplementary Information. Individual observations and ratings are retained.

| File | Contents |
| --- | --- |
| D1_structure_ratings.json | Individual structure ratings by example and evaluator |
| D2_structure_comments.json | Optional structure comments (none submitted) |
| D3_render_ratings.json | Rendering identifiers, inputs, models and individual ratings |
| D4_cotravel_intervals.json | Effective co-travel intervals for the C019 example |
| D5_C076_components.json | Objective components for the C076 paired example |
| D6_runtime_by_parent_count.json | Runtime summaries by run group and parent count |
| D7_rating_agreement.json | Ordinal agreement, item-bootstrap intervals and image-level score summaries from D1 and D3 |
| D8_weight_sensitivity/ | Six Stage II weights varied individually by ±20%; settings, full results, selected candidates and reproduction scripts |

Example and evaluator identifiers match the manuscript and Supplementary Information. The tables and explanations in the English Supplementary Information provide their interpretation.

A1 measures hierarchical organization; A2 measures continuous composition and rhythm. B1 measures overall appearance quality; C1 measures structural preservation. All use five-point scales. D1 has 270 structure–evaluator records and D3 has 150 rendering–evaluator records.

D2 is an empty list because no optional structure comments were submitted.

Agreement estimates use ordinal Krippendorff alpha and 5,000 complete-image bootstrap resamples, retaining all five evaluators (seed 20260922). Reproduce D7 by running `python analyze_rating_agreement.py` in this directory; Python and NumPy are required. Image-level scores and within-image score ranges are retained for inspection. The script does not modify D1 or D3.

## D10 Geometry-prior width sensitivity

`D10_geometry_prior_sensitivity/` contains the 54 generated outputs, paired results, prior settings and scripts used in Supplementary Information S9.
