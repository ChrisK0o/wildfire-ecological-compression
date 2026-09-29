# Ecological compression of vegetation information in wildfire spread prediction

## Authors

1. Christopher Ko, Portola High School, Irvine, CA, USA
2. Hannah Ko, Vanderbilt University, Nashville, TN, USA

Institutional affiliations identify the authors' affiliations and do not imply that Portola High School or Vanderbilt University sponsored, reviewed, funded, or endorsed this research.

## Author contributions

Christopher Ko: Conceptualization, Data curation, Formal analysis, Investigation, Methodology, Software, Validation, Visualization, Writing - original draft, Writing - review & editing.

Hannah Ko: Conceptualization, Investigation, Writing - review & editing.

Both authors read and approved the final manuscript.

## Study overview

This compendium supports a retrospective single-fire case study of the 2020 Brattain Fire. The outcome is conditional next-interval wildfire propagation among locations eligible and exposed at the completed observation time. The primary comparison asks whether a 24-field conventional fire-state, weather, terrain, fuel, and canopy representation is predictively sufficient, or whether five pre-fire LANDFIRE Existing Vegetation Type composition fractions retain incremental predictive information.

L2 logistic regression is primary; Random Forest is a nonlinear robustness check. The primary grid is 1 km, with a required 2 km sensitivity, and validation is forward chronological. Paired differences are defined as baseline loss minus EVT-augmented loss, so positive values favor the EVT-augmented representation. Results are specific to this fire and design. They do not establish causal effects, regional generalizability, ignition risk, real-time operational performance, or suppression effectiveness.

## Repository/package structure

- `code/`: frozen preprocessing and analysis code
- `data/`: frozen derived inputs and Figure 1 support data
- `results/`: authoritative ledger and machine-readable outputs
- `tables/`: final Word tables and CSVs
- `figures/`: final PDFs, SVGs, captions, and source audits
- `documentation/`: specifications, provenance, environment, and claim authorities

## Source data

Raw FEDS, USGS 3DEP, LANDFIRE, NOAA HRRR, and other third-party source products are not redistributed. They must be obtained separately from their providers. `SOURCE_DATA.md` records products, source locations, checksums, and unresolved limitations; `THIRD_PARTY_DATA.md` explains the licensing boundary.

## Reproducing the analysis

Start with `REPRODUCIBILITY.md` and verify integrity using `SHA256SUMS.txt`. Exact derived inputs are included. Rebuilding them requires separately obtaining the documented public source data.

## Authoritative results

`results/RESULTS_AUTHORITY.csv` controls manuscript values. Underlying per-unit predictions/metrics and paired interval, block, aggregate, and bootstrap evidence are included.

## Publication tables

`tables/Publication_Tables.docx` contains native Word tables; `Table1.csv`, `Table2.csv`, and `Table3.csv` are machine-readable.

## Publication figures

Final vector PDFs/SVGs, captions, and source audits are under `figures/`.

## Software environment

The accepted run used Windows 11 and CPython 3.12.13. See `ENVIRONMENT.md` and `documentation/ENVIRONMENT_PACKAGES.csv`.

## Citation and availability

See `CITATION.cff`. Public repository, persistent, and code-archive identifiers remain explicit placeholders in `FIRE_ECOLOGY_AVAILABILITY_DRAFT.txt` until deposition. This local package does not claim that a public repository or DOI already exists.

## Licensing

- Original research source code included in this package is licensed under the MIT License. See `LICENSE`.
- Original derived data, original documentation, and original research-compendium materials for which the authors can grant a license are licensed under Creative Commons Attribution 4.0 International (CC BY 4.0). See `LICENSE-DATA-DOCS.md`.
- Third-party libraries, source datasets, and copied third-party materials are not licensed by those grants. Raw third-party source data are not redistributed and remain governed by their providers' terms. See `THIRD_PARTY_DATA.md` and `SOURCE_DATA.md`.

## Known provenance limitations

The HRRR release number is not embedded in retained GRIB metadata; the 3DEP tile edition/year is unresolved; the original LF2016 EVT download endpoint was not retained; and a complete earliest geospatial package lock is unavailable. See `SOURCE_DATA.md`.
