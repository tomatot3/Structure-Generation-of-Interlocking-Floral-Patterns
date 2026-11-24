# Data dictionary

## Structural assets

`data/structural_assets/asset_index.json` has one record per distinct structure. `case_records.json` has one record per generation run. Their principal fields are:

| Field | Meaning |
| --- | --- |
| `case_id` | Original experimental identity |
| `asset_id` | Canonical geometry record; used to locate the asset directory |
| `group` | `density`: default soft-density control; `exact`: prescribed counts; `seed`: fixed-control seed variation |
| `prototype` | Paper label, such as SW1-A |
| `prototype_id` | Internal identifier used by the generator |
| `backbone_variant` | `expanded`, `compact` or `swept` |
| `density_level` | `simple`, `medium` or `rich` |
| `generation_parameters` | Recorded case controls and production, backbone, flower, branch and unit seeds |
| `ordinary_L1_count`, `L2_count` | Ordinary parent-branch and child-branch counts |
| `flower_support_count` | Number of separately represented flower-support paths |
| `asset_directory`, `input_image` | Paths relative to `data/structural_assets` |

Each asset directory contains:

- `structure.json`: central-repeat geometry, flowers, supports and selected parent–child configurations.
- `structure.svg`: role-labelled, editable three-repeat view.
- `render_input.svg` and `render_input.png`: the unlabelled conditioning view, with white background and the original role colours.

In `structure.json`, `analysis.backbone.samples` records the main vine; `analysis.flowers` records flower regions; `flower_mount_plan.mounts` records flower-support paths. `selection.selected_candidates` contains complete parent–child configurations. A candidate's `curves` contain its L1 parent and L2 children; `parent_curve_id` links a child to its parent. Cubic control points and sampled centre lines are both stored. The `parent_graph` field preserves the candidate's attachment relationships.

Distances use repeat width W = 1. The central repeat has shift zero; the SVG displays adjacent copies at shifts −1 and +1. SVG attributes such as `data-role`, `data-level` and `data-repeat-shift` retain the role and repeat identity. Geometry in the JSON describes the generated structure; appearance images can add small leaves and decorative detail as allowed by the prompt.

## Paired images

`data/paired_renderings/pairs.csv` and `pairs.json` contain the same 500 records. Image and prompt paths are relative to `data/paired_renderings`.

| Field | Meaning |
| --- | --- |
| `pair_id` | Shared filename stem, independently numbered within each prototype |
| `case_id`, `asset_id` | Links to the original run and distinct structural asset |
| `structure_image`, `render_image` | Corresponding PNG paths |
| `prompt_file` | Actual prompt used for the image request |
| `generation_route` | Recorded service route (`builtin_image_gen`) |
| `returned_model_id` | Null because the tool did not return a model identifier |
| `attempt` | Archived attempt used for the delivered image |
| `started_at`, `finished_at` | Recorded generation times, including timezone |

These records contain no new human ratings. D3 describes the separate 30-image rendering evaluation.

## Evaluation files

Table 3 uses `data/evaluation/matrix_c/evaluated_results.csv` for IC and Global L1 (`Ours`) and `data/evaluation/controls/l1/results.csv` for HCG. Average `l1_layout_crossing_count` over each method’s completed layouts. Average `root_coverage_qcov` over the 106 inputs completed by all three methods.

`evaluation/matched/objective_components.csv` has 1,344 rows: 336 requests × four methods. `target` is the requested L2 count; `attained` records whether it was reached. `score` is the common combination objective, `quality` its local-quality sum, `B` the child count, `U` the number of parents with children, and `total`/`peak` the total/maximum co-travel penalties. Objective differences are computed within the same context and requested count. For the confidence interval, request differences are first reduced to a median per context; the median across contexts is bootstrapped 2,000 times with seed 20260825.

Table 4 uses `attained` and `score` to compare the four methods. The objective difference is the median of the per-layout medians, using matched L2 targets. Figure 10 uses the same grouping of 336 requests across 108 layouts. For Supplementary Section S3.4, use `U` for the number of parents with children and divide it by `ordinary_l1_count` from the corresponding Global L1 (`Ours`) result for the share. `data/evaluation/matched/independent_metrics.csv` contains the independent geometry checks.

`evaluation/default` contains the corrected soft-density records and 180 matched triplets. `D` is the composite density of the selected parent layout, `target` its requested value and `residual = D − target`. The triplet files retain ties and decreases in each measured quantity. `evaluation/exact` and `evaluation/seed` contain the prescribed-count and seed-control experiments. The prescribed total L1 count includes flower-support paths; ordinary L1 is recorded separately.

`data/evaluation/human_and_cases` supplies D1–D7 and the agreement script for direct analysis. The [Supplementary Data D1–D11 archive](../archives/PaperA_Supplementary_Data.zip) also provides D8 per-request results, D9 source records, D10 final structures and paired metrics, and the D11 ceramic-border case (Figure 13). A1 is hierarchical organization; A2 is continuous composition and rhythm; B1 is appearance quality; C1 is structural preservation. Scores range from 1 to 5. D2 is empty because no optional comments were submitted. D7 reports ordinal agreement and item-bootstrap intervals; D8 contains Stage II weight-sensitivity settings and results.

## Prototype inputs and parameters

`code/inputs/prototype_inputs.json` contains the six materialized prototype inputs consumed by generation. The priors and contracts alongside it preserve the numerical settings. The two-stage algorithm and geometric predicates are in `code/experiments/branch_unit/dynamic`. Package changes are limited to input loading and file/font paths; `code/portability_changes.json` records them.

`data/parameters` preserves the archived parameters. The generator reads the parent-curve prior from `code/inputs/curve_geometry_prior.json` and the child-placement prior from `code/experiments/branch_unit/dynamic/EDITOR_L2_PLACEMENT_PRIOR_V1.json`. Use this numerical prior and the accompanying settings to reproduce the archived runs.

## Source annotations

`source_materials/index.json` preserves 121 annotation identifiers and their existing source metadata. The vector annotations are provided in `source_materials/role_annotations/`; embedded source images have been removed. Original paths, role colors, transforms and object identifiers are preserved. The ten reviewed source patterns and the representative comparisons follow Supplementary Tables S1 and S2, respectively. `docs/SOURCE_INDEX.md` maps the displayed sources to manuscript figures, bibliography entries and page locations. Numerical identifiers are annotation IDs, not bibliographic citations.

No train/validation/test split is imposed. Related generated cases share prototypes and sometimes fixed upstream geometry; case records preserve the information needed to construct a split suited to the intended experiment.
