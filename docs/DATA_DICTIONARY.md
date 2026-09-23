# Data dictionary

## Structural assets

The public dataset ZIP contains `data/structural_assets/asset_index.json`, with one record per distinct structure. `case_records.json` has one record per generation run. Their principal fields are:

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

Inside the public dataset ZIP, `data/paired_renderings/pairs.csv` and `pairs.json` contain the same 500 records. Image and prompt paths are relative to `data/paired_renderings`.

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

These records contain no human ratings. The separate 30-image rendering evaluation is summarized in the manuscript; individual ratings are retained locally.

## Evaluation files

The detailed evaluation tables described below are retained in the local experiment archive. The public repository contains summary results, settings and analysis scripts. `root_coverage_qcov` is the root-position coverage measure used in Table 2; Stage I means use the 106 contexts completed by all three compared methods.

`evaluation/matched/objective_components.csv` has 1,344 rows: 336 requests × four methods. `target` is the requested L2 count; `attained` records whether it was reached. `score` is the common combination objective, `quality` its local-quality sum, `B` the child count, `U` the number of parents with children, and `total`/`peak` the total/maximum co-travel penalties. Objective differences are computed within the same context and requested count. For the confidence interval, request differences are first reduced to a median per context; the median across contexts is bootstrapped 2,000 times with seed 20260825.

Table 3 uses `U` and `U / number of ordinary parents`. This coverage is distinct from the root-position measure `Qcov` in Table 2. `matched/independent_metrics.csv` contains geometric checks for completed requests, including crossings, clearances and periodic seams.

`evaluation/default` contains the corrected soft-density records and 180 matched triplets. `D` is the selected resource score, `target` its requested value and `residual = D − target`. The triplet files retain ties and decreases in each measured quantity. `evaluation/exact` and `evaluation/seed` contain the prescribed-count and seed-control experiments. The prescribed total L1 count includes flower-support paths; ordinary L1 is recorded separately.

`evaluation/human_and_cases` publicly contains D8 and D10 summaries, settings and scripts. The individual D1–D7 records are retained locally. A1 is hierarchical organization; A2 is continuous composition and rhythm; B1 is appearance quality; C1 is structural preservation. Scores range from 1 to 5.

## Prototype inputs and parameters

`code/inputs/prototype_inputs.json` contains the six materialized prototype inputs consumed by generation. The priors and contracts alongside it preserve the numerical settings. The two-stage algorithm and geometric predicates are in `code/experiments/branch_unit/dynamic`. Package changes are limited to input loading and file/font paths; `code/portability_changes.json` records them.

`data/parameters` preserves the numerical prior and selection settings used by the generator.

## Source annotations

`source_materials/index.json` preserves 118 annotation identifiers and their existing source metadata. The vector annotations are provided in `source_materials/role_annotations/`; embedded source images have been removed. Original paths, role colors, transforms and object identifiers are preserved. The ten core cases follow the current Table S1. `docs/SOURCE_INDEX.md` maps the displayed sources to manuscript figures, bibliography entries and page locations. Numerical identifiers are annotation IDs, not bibliographic citations.

No train/validation/test split is imposed. Related generated cases share prototypes and sometimes fixed upstream geometry; case records preserve the information needed to construct a split suited to the intended experiment.
