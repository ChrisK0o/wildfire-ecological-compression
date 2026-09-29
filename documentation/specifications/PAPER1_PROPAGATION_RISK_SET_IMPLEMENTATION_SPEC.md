# Paper 1 Propagation Risk-Set Implementation Specification

## Locked Rule

For interval `t`, include a cell when:

```text
not covered_by(t0_cumulative_hull, cell_center)
AND (
    distance(cell_center, t0_active_front) <= 5000 m
    OR distance(cell_center, t0_cumulative_hull_boundary) <= 2000 m
)
```

The rule is evaluated in EPSG:9311 on the fixed 1 km response lattice. It is frozen before the `t1` response is loaded.

## Timing Lock

The nominal FEDS `00:00`/`12:00` timestamp is a synthetic AM/PM bin identifier. It is not the observation time or historical product-availability time.

For each interval:

- `nominal_t0_bin_timestamp` is the archived `t0` bin identifier;
- `latest_t0_viirs_observation_utc` is the latest VIIRS acquisition incorporated into the completed `t0` state;
- `effective_t0_observation_cutoff_utc` equals `latest_t0_viirs_observation_utc` and is the retrospective information cutoff;
- `nominal_t1_bin_timestamp` is the next archived bin identifier;
- `effective_t1_observation_time_utc` is the latest VIIRS acquisition incorporated into the next completed state;
- `effective_response_interval_hours` is the elapsed time from the effective `t0` cutoff to the effective `t1` observation time.

Historical FEDS processing/publication latency remains unresolved. The implementation is retrospective, pseudo-prospective, and forecast-like; it must not claim operational or historical real-time availability.

## Inputs

1. FEDS Western-US v1.2.1 event `65371` state table.
2. Locked interval list `1, 3, 4, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 18, 21, 22`.
3. For each interval, only the completed `t0` state's cumulative `hull` and `fline` geometries after the effective `t0` observation cutoff during eligibility construction.
4. Fixed EPSG:9311 response-grid definition.
5. A separately prespecified static landscape/domain mask and common-support rules, once those gates pass.

The final perimeter, `t1` geometry, later detections, later active lines, and future suppression geometry are not inputs to eligibility.

## Exact Algorithm

### 1. Freeze Interval Provenance

Read the locked interval row and record:

- event ID;
- interval ID;
- `t0` and `t1` state numbers;
- `nominal_t0_bin_timestamp`;
- `latest_t0_viirs_observation_utc`;
- `effective_t0_observation_cutoff_utc`;
- `nominal_t1_bin_timestamp`;
- `effective_t1_observation_time_utc`;
- `effective_response_interval_hours`;
- source artifact path and SHA-256;
- FEDS version and CRS.

Verify the interval belongs to the locked set, the effective cutoff equals the latest incorporated `t0` observation, and the effective `t1` time is later than the effective `t0` cutoff. The `t1` identifier and timing may be recorded, but its geometry must not be loaded into the eligibility-construction object.

### 2. Load And Validate `t0`

Load only `t0.hull` and `t0.fline` from event 65371. Require:

- the completed state is treated as usable no earlier than `effective_t0_observation_cutoff_utc`;
- CRS resolves to EPSG:9311;
- cumulative hull is nonempty and valid;
- active front is nonempty and valid;
- active front lies on the cumulative-hull boundary within numerical tolerance;
- geometry is from the same event and state.

If the active front is absent or invalid, stop. Do not silently fall back to the full perimeter; that would change the locked estimand.

### 3. Construct The Fixed Grid

Use the EPSG:9311 global lattice, not a grid re-anchored to each fire state:

```text
center_x = (integer_column + 0.5) * 1000 m
center_y = (integer_row + 0.5) * 1000 m
cell_id = EPSG9311_1000_{integer_column}_{integer_row}
```

Enumerate only enough lattice cells to cover the `t0` cumulative hull buffered by 5,000 m. Grid bounds therefore use `t0` only.

### 4. Exclude Already-Reached Cells

For each cell center, calculate:

```text
already_reached_t0 = t0_hull.covers(center)
```

`covers` is inclusive of a center on the hull boundary. Exclude every cell for which it is true. Do not use partial overlap with the final perimeter or `t1` extent.

### 5. Compute Exposure Distances

In EPSG:9311, calculate:

- `distance_t0_active_front_m = center.distance(t0_fline)`;
- `distance_t0_cumulative_perimeter_m = center.distance(t0_hull.boundary)`.

No wind, slope, future growth direction, predictor value, or outcome label enters these distances.

### 6. Apply The Locked Inclusion Rule

For cells not already reached at `t0`:

```text
active_component = distance_t0_active_front_m <= 5000
perimeter_backstop_component = distance_t0_cumulative_perimeter_m <= 2000
candidate = active_component OR perimeter_backstop_component
```

Distance equality is included. For every row with valid component geometry,
record the complete joint state as:

| `active_component` | `perimeter_backstop_component` | `hybrid_membership` |
| --- | --- | --- |
| `True` | `False` | `ACTIVE_ONLY` |
| `False` | `True` | `PERIMETER_BACKSTOP_ONLY` |
| `True` | `True` | `BOTH` |
| `False` | `False` | `NEITHER_PRIMARY_COMPONENT` |

The primary hybrid risk set requires `active_component OR
perimeter_backstop_component`, so only the first three states occur in its
existing artifacts. `NEITHER_PRIMARY_COMPONENT` completes the global domain
for locked broader sensitivity risk sets; it means only that neither primary
hybrid component is satisfied. It is not `OUTSIDE_DOMAIN`, `UNEXPOSED`, or an
ecological state. Missing component geometry or any value outside these four
states is a hard error. The dedicated PR32A0 authority amendment controls this
global-domain clarification without changing the primary inclusion rule.

### 6a. Global Terrain-Source Selector (PR32A1)

For every global membership state and every locked risk-set sensitivity, the
active component is the sole terrain-source selector:

```text
if distance_to_completed_t0_active_front <= 5000 m:
    terrain_source_type = ACTIVE_FRONT
    source point = nearest point on completed-t0 active front
else:
    terrain_source_type = CUMULATIVE_HULL_BOUNDARY
    source point = nearest point on completed-t0 cumulative-hull boundary
```

Thus `ACTIVE_ONLY` and `BOTH` use the active front, while
`PERIMETER_BACKSTOP_ONLY` and `NEITHER_PRIMARY_COMPONENT` use the completed-t0
cumulative-hull boundary. This rule applies only to terrain source-target
elevation difference and uphill alignment. Target terrain, fire-state
distances, weather, fuels, canopy, ecology, and risk-set eligibility do not
change. `PAPER1_TERRAIN_SOURCE_AUTHORITY_AMENDMENT.md` is the governing
amendment; historical PR23 generated specifications remain provenance.

### 7. Apply Static Domain And NoData Rules

After geometric exposure is frozen, apply only masks whose values are static/pre-fire or otherwise valid at `t0`. Record every exclusion reason separately. Predictor missingness cannot be recoded as a negative response.

The domain/common-support mask remains a separate unresolved gate. It may reduce eligible rows identically across model comparisons, but it may not use the final fire perimeter or any `t1` outcome and may not alter the 5 km/2 km exposure rule.

### 8. Deduplicate Within Interval

Require exactly one row per `interval_id, cell_id`. A duplicate is an implementation error. The same `cell_id` may legitimately occur in multiple intervals and must retain the same spatial identifier.

### 9. Freeze Eligibility Receipt

Before response construction, save or hash a receipt containing:

- interval and cell IDs;
- nominal `t0`/`t1` bin timestamps, effective `t0`/`t1` observation times, and effective response duration;
- `t0` source hashes;
- grid definition;
- distances;
- component membership;
- static-domain/common-support flags;
- eligibility decision;
- code version and parameters.

Eligibility must be frozen using only the completed `t0` state at its effective observation cutoff. The receipt must be reproducible without access to `t1` or final-perimeter geometry.

### 10. Construct The Response Separately

Only after the risk-set receipt is frozen, load the corresponding next completed state's `t1` cumulative hull and assign:

```text
y = 1 if t1_hull.covers(center) else 0
```

Do not modify eligibility based on the label. A positive outside the frozen risk set is a missed-positive diagnostic, not a reason to add the cell retrospectively.

Record `effective_t1_observation_time_utc` and `effective_response_interval_hours` with the response. Do not describe the interval as fixed midnight-to-noon, noon-to-midnight, or an exact 12-hour forecast.

### 11. Add Boundary-Uncertainty Flags

For included candidates, record center distances to both `t0` and `t1` boundaries and Boolean flags for:

- within 500 m of `t0` boundary;
- within 500 m of `t1` boundary;
- within either 500 m zone;
- within 1,000 m of `t0` boundary;
- within 1,000 m of `t1` boundary;
- within either 1,000 m zone;
- response cell intersects each boundary, when cell polygons are materialized.

These are uncertainty diagnostics. They do not change the primary eligibility rule.

### 12. Preserve Provenance Fields

Every row must contain at least:

- `event_id`;
- `interval_id`;
- `t0_state_number`, `t1_state_number`;
- `nominal_t0_bin_timestamp`, `effective_t0_observation_cutoff_utc`, and `latest_t0_viirs_observation_utc`;
- `nominal_t1_bin_timestamp`, `effective_t1_observation_time_utc`, and `effective_response_interval_hours`;
- `cell_id`, row, column, center coordinates, CRS, and grid size;
- `distance_t0_active_front_m`;
- `distance_t0_cumulative_perimeter_m`;
- component-membership flags;
- `already_reached_t0`;
- static-domain/common-support status and exclusion reason;
- final `eligible_risk_set` flag;
- `y`, added only in the response stage;
- boundary-uncertainty flags;
- source paths, hashes, product version, and code receipt.

## Required Sensitivity Algorithms

Use the same frozen cells, distance fields, domain rules, and response-stage separation. Replace only the Boolean exposure expression:

```text
ACTIVE_FRONT_ONLY_5KM:
distance_t0_active_front_m <= 5000

PERIMETER_ONLY_2KM:
distance_t0_cumulative_perimeter_m <= 2000

PERIMETER_ONLY_5KM:
distance_t0_cumulative_perimeter_m <= 5000
```

For the 2 km response-grid sensitivity, use the same EPSG:9311 lattice formula with 2,000 m cells and retain the same physical distances. Do not scale the 5 km/2 km radii with cell size.

For the no-early sensitivity, use only intervals `4, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 18, 21, 22` without changing any row rule.

## Assertions That Must Halt Construction

Stop with an error if:

- event ID is not 65371;
- interval set differs from the lock;
- source hash or CRS is unexpected;
- the effective `t0` cutoff is missing or differs from the latest incorporated `t0` VIIRS observation;
- effective `t1` observation time is not later than the effective `t0` cutoff;
- `t0` hull or active front is absent/invalid;
- any eligibility function receives `t1` or final-perimeter geometry;
- any distance is computed in geographic coordinates;
- a cell occurs more than once in an interval;
- a response label exists before the eligibility receipt is frozen;
- a candidate was added because it later became positive;
- a model score, predictor importance, class-balance target, or final perimeter influenced eligibility.

## Interpretation Boundary

The algorithm creates a reproducible geometric opportunity set under an imperfect satellite-derived fire state. It does not identify a complete physical flame front, exact spread mechanism, spotting event, suppression-free opportunity, or independent sample. Modeling remains unauthorized until the remaining scientific and implementation gates pass.

Permitted timing terms are `nominal FEDS bin`, `completed t0 observation state`, `VIIRS observation time`, `observation-based information cutoff`, `next FEDS interval`, `approximately 12-hour interval`, `pseudo-prospective`, and `forecast-like retrospective evaluation`. Historical real-time availability, operational forecasting, and an exact 12-hour response are not established.
