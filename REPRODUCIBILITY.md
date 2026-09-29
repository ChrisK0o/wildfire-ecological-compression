# Reproducing the analysis

This package freezes the accepted single-fire analysis at commit `ba565d6cae23d39f28ba5fd148d380c1ed24e343`. No analysis was executed during packaging.

## From frozen derived inputs

The 15 Parquet files in `data/derived/` are the exact labeled, predictor, and support tables selected by the final descriptor. `data/DATA_INDEX.csv` records their source paths and hashes. The scientific code is under `code/`; model and preprocessing primitives are in `code/src/paper1_pr34_modeling.py`, and the accepted serial entry point was `code/scripts/run_paper1_focused53.py`.

The accepted runner is bound to its original Git state, selection descriptor, and execution authorization. This package does not claim a portable one-command rerun. A reproducer must restore recorded repository-relative paths in a checkout of the frozen commit, recreate the documented environment, and establish independently reviewed execution authorization before invoking the controlled runner.

## Rebuilding derived inputs

1. Obtain raw products listed in `SOURCE_DATA.md` and verify them against the source audit.
2. Run `run_paper1_pr23.py` for response-free predictors.
3. Run `run_paper1_pr24.py` for paired support.
4. Run `run_paper1_pr31.py` for frozen response labels.
5. Run the three `run_paper1_pr32*` scripts for alternate risk sets.
6. Validate model inputs/definitions with `run_paper1_pr34_models.py` and the frozen specifications.
7. Execute the selected analyses and audit only after restoring provenance requirements.

Source acquisition/geospatial aggregation, 1,000-tree five-seed Random Forest fitting, and the 10,000-replicate moving-block bootstrap are computationally expensive.

## Authoritative outputs

`results/RESULTS_AUTHORITY.csv` controls manuscript values. `results/paired_evidence/` contains interval, block, aggregate, and bootstrap evidence. `results/units/` contains final predictions, metrics, tuning records, RF seed evidence, boundary diagnostics, and LOIO output. Publication artifacts are under `tables/` and `figures/`.

Verify files against `SHA256SUMS.txt`. It covers every file except itself. `MANIFEST.csv` inventories payload files; manifest/checksum self-reference is excluded by convention and documented in `PUBLIC_RELEASE_AUDIT.txt`.
