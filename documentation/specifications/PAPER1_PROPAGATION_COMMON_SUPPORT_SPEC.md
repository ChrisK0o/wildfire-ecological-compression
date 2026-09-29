# Paper 1 PR24 Confirmatory Common-Support Specification

## Decision

**COMPLETE_WITH_LIMITATIONS.** PR24 defines response-free, paired predictor-support universes. It does not attach or inspect response labels, `t1`, future FEDS growth, final perimeter, predictive scores, or model output. PR31 may begin as the later labeled-table and leakage gate; modeling remains unauthorized.

## Principal Confirmatory Universe

`PRIMARY_CONFIRMATORY` compares the conventional baseline with the same baseline plus the five LF2016 EVT composition fractions on identical rows. Baseline support requires valid completed-`t0` FEDS state, terrain, FBFM40, canopy product validity, HRRR, and their locked numeric fields. A nonforest canopy state is valid structural information, not automatic row loss. EVT requires valid composition fractions. The resulting support is `3317` of `3317` 1 km rows and `836` of `836` 2 km rows.

For downstream model construction, retained rows with `canopy_applicable_fraction == 0` use `STRUCTURAL_ZERO_FOR_NONAPPLICABLE_CANOPY` for the four conditional canopy fields. Their source-table `NaN` values are intentional `NOT_APPLICABLE` states and do not invalidate support; missing/nonfinite conditional values where canopy applicability is positive do invalidate execution. This downstream representation does not change these frozen support masks.

## Separate Sensitivity Universes

Each authorized sensitivity is paired with its own baseline on the same rows. EVC and EVH require physical applicability. Legacy EAG, V5 EAG, cheatgrass, and their confidence representations require their own source/domain applicability; outside-domain codes are never ecological zero. FACTS requires NFS applicability; RAP requires rangeland applicability. Prior MTBS and forest health retain full structural-domain support because no-recorded-event is information. FDist is descriptive exploratory support only. No optional/domain-limited family changes the principal baseline-versus-EVT universe.

## Reproducibility and Semantics

Input PR23 artifacts, hashes, the current Git HEAD, rule version, support-mask hashes, interval/block counts, and all output hashes are in the PR24 manifest. The same `support_universe_id` mask must be applied to both sides of every later paired comparison. Repeated interval-cell observations are preserved. No imputation is performed or authorized here.

## Limitations

Support locking does not authorize response labeling or modeling. Domain-limited ecology sensitivities may have sparse block support and must remain domain-specific. RCMAP remains exploratory/deferred.
