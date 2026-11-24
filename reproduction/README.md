# Package reproduction checks

Checks on the original experimental archives were run on 20 September 2026.

- All 500 pair IDs are unique. Their conditioning PNG pixels match the linked structural assets, and all 500 rendering PNGs decode successfully.
- Three generation examples cover default density (A091), prescribed counts (E10V2_A001), and fixed-control seed variation with the authored SW1-C input (E11V2_B052). Their geometry and parent relationships match the archived assets within 1e-12 of repeat width. The largest observed coordinate difference was 1.11e-16.
- The public comparison statistics and rating means can be recomputed from the packaged result tables with `python code/summarize_results.py --output results/main_results.json`. See `main_results.json` for the reference output.

These checks use coordinates, parent relationships, candidate selections and recorded observations. The original full generation batches are archived; they were not all rerun during packaging. Image readability and pairing checks do not assign new aesthetic ratings.

The new-seed command was also run with SW1-C, production seed 20260920, expanded main vine and medium soft density. It produced six ordinary parents and one child, passed the recorded geometric checks, and exported semantic JSON, SVG and a 2048-pixel conditioning PNG. See `new_seed_run.json`.
