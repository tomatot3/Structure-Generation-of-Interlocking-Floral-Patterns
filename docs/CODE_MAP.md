# Generation pipeline

The structural generator starts from six supplied procedural prototype inputs and numerical priors. Source-image interpretation and role annotation establish those inputs. They are recorded research inputs, rather than an automatic image-to-structure prediction stage.

Use `code/generate.py` to generate new structures or reproduce recorded cases. The same numerical functions serve both routes.

| Step | Active implementation under `code/experiments/branch_unit/` | Output consumed by the next step |
| --- | --- | --- |
| Load the six prototypes and priors | `dynamic/run_stage3b_l1_flow.py::_load_inputs`, `prototype_strategy_v1.py` | Strict geometry, prototype analysis, morphology and strategy |
| Split the production seed | `dynamic/backbone_variation_v1.py::split_generation_seeds` | Backbone, flower, branch and unit seeds |
| Vary the main vine | `dynamic/global_backbone_wave_v4.py`, `backbone_variation_v1.py` | Variant main-vine geometry and analysis |
| Place flowers and construct supports | `dynamic/flower_placement_v1.py`, `flower_mounting_v1.py`, `authored_svg_prototype.py` | Flower regions and support paths |
| Generate and select ordinary parents | `dynamic/global_l1_flow.py::generate_global_l1_flow_plan` | Global L1 layout under the density/count setting |
| Construct complete parent–child candidates | `dynamic/branch_unit_grammar_v1.py::generate_unit_candidate_inventory` | BranchUnit candidate inventory |
| Build compatibility and co-travel relationships | `dynamic/stage5_global_unit_selection.py::build_conflict_graph`, `composition_geometry.py` | Conflict graph and pair penalties |
| Select complete configurations | `dynamic/stage5_global_unit_selection.py::select_global_units` | JBC selection |
| Check generated geometry | `paper_a_evaluation/evaluate_formal_cases.py::evaluate_case` | Crossings, clearance, attachment and periodic geometry metrics |
| Export geometry and figures | `dynamic/export_batch_svgs.py::render_case_svg`, `code/asset_export.py` | Semantic JSON, role-labelled SVG and unlabelled conditioning SVG; optional PNG |

`paper_a_evaluation/run_formal_cases.py::_run_case` connects the core generation steps. The packaged loader reads materialized inputs from `code/inputs`; it does not access the original workstation directories. Candidate construction, selection, geometric checks, thresholds and weights are retained.

## New structures

From the repository root:

```bash
python code/generate.py --prototype SW1-C --seed 20260920 --variant expanded --density medium --output results/new_sw1c
```

Use repeated `--seed` arguments for a batch. `--control soft` is the default; `--control exact` uses the prescribed total-L1 and L2 counts in `code/inputs/density_control_profile.json`. A prescribed total-L1 count includes the separately recorded flower-support paths.

For a 2048-pixel-wide conditioning PNG, install Inkscape and add `--inkscape inkscape` if it is on PATH, or supply its executable path. SVG and geometric JSON export use the Python requirements only.

The output directory contains `raw_cases/<case_id>/` with the case parameters, main-vine and flower geometry, parent layout, JBC result, `structure.json`, `structure.svg` and `render_input.svg`. When requested, `render_input.png` is saved alongside them. `results.json` contains the counts, runtimes and independent geometry metrics.

## Appearance generation

The completed 500 images, conditioning inputs, matching IDs and submitted prompt are in `data/paired_renderings`. New appearance generation uses an external image service. The original subscription route was an agent's built-in `image_gen` call; its service implementation and model weights are not local project code. The reproducible local pipeline ends at the conditioning image, and the actual appearance-generation procedure is documented in `RENDERING_PROTOCOL.md`.

## Dataset utility

`code/check_dataset.py` checks the 500 paired images and their links to structural assets after extracting the dataset ZIP.

The two modules retained under the historical `paper_a_evaluation/` path supply the generation runner and runtime geometry checks. Both are used by the command-line generator and the website.
