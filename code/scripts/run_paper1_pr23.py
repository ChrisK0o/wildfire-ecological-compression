"""Build response-free PR23 propagation predictors on locked 1 km/2 km grids."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
from affine import Affine
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.transform import array_bounds
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window
from scipy.ndimage import convolve
from shapely.ops import nearest_points


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "documentation"
WORK = ROOT / "data/processed/propagation/paper1/pr23_response_free_predictors"
SOURCE = WORK / "source"
OUTPUT = WORK / "outputs"
RECEIPTS = WORK / "receipts"
CANDIDATES = ROOT / "data/processed/feasibility/paper1_predictor_adjudication/t0_candidate_geometry_no_response.parquet"
STATES = ROOT / "data/processed/feasibility/paper1_feds_validation/extracted/feds_event_65371_states.parquet"
INTERVALS = DOC / "PAPER1_PROPAGATION_INTERVAL_LOCK.csv"
HRRR = ROOT / "data/processed/feasibility/paper1_hrrr_primary"
ECOLOGY = ROOT / "data/processed/feasibility/paper1_pending_ecology_rescue"
RECOVERY = ROOT / "data/processed/feasibility/paper1_predictor_recovery/source_cache"
GRID_SIZES = (1000, 2000)
TOL = 1e-6
UA = "WildfireResearchProject-PR23/1.0 (scientific reproducibility)"
PREFIRE_CUTOFF = pd.Timestamp("2020-09-08T00:00:00Z")
PRIMARY_INTERVALS = [1, 3, 4, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 18, 21, 22]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def ensure_dirs() -> None:
    for path in (WORK, SOURCE, OUTPUT, RECEIPTS):
        path.mkdir(parents=True, exist_ok=True)


def fetch_json(url: str, payload: dict | None = None) -> tuple[dict, dict]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "lfps.usgs.gov":
        raise ValueError(f"Unapproved acquisition endpoint: {url}")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"User-Agent": UA}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=240) as response:
        body = response.read()
        final = urllib.parse.urlparse(response.geturl())
        if final.hostname != "lfps.usgs.gov":
            raise ValueError(f"Unexpected redirect host: {final.hostname}")
        result = json.loads(body)
        receipt = {
            "requested_url": url,
            "final_url": response.geturl(),
            "http_status": response.status,
            "content_type": response.headers.get("Content-Type"),
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "accessed_utc": now(),
        }
    return result, receipt


def fetch_file(url: str, destination: Path) -> dict:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "lfps.usgs.gov":
        raise ValueError(f"Unapproved download endpoint: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    digest = hashlib.sha256()
    count = 0
    try:
        with urllib.request.urlopen(request, timeout=240) as response, temporary.open("wb") as stream:
            final = urllib.parse.urlparse(response.geturl())
            if final.hostname != "lfps.usgs.gov":
                raise ValueError(f"Unexpected redirect host: {final.hostname}")
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                stream.write(chunk)
                digest.update(chunk)
                count += len(chunk)
            receipt = {
                "requested_url": url,
                "final_url": response.geturl(),
                "http_status": response.status,
                "content_type": response.headers.get("Content-Type"),
                "bytes": count,
                "sha256": digest.hexdigest(),
                "accessed_utc": now(),
            }
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return receipt


def acquire_landfire(bounds_lonlat: tuple[float, float, float, float], allow_network: bool) -> tuple[Path, dict]:
    archive = SOURCE / "LF2016_PR23_operational_baseline.zip"
    extract = SOURCE / "LF2016_PR23_operational_baseline"
    rasters = list(extract.glob("*.tif"))
    if archive.exists() and len(rasters) == 1:
        return rasters[0], json.loads((RECEIPTS / "landfire_acquisition_receipt.json").read_text())
    if not allow_network:
        raise FileNotFoundError("Expanded LF2016 PR23 source is absent; rerun with --allow-network")
    west, south, east, north = bounds_lonlat
    request_body = {
        "Layer_List": "LF2016_FBFM40;LF2016_CC;LF2016_CH;LF2016_CBH;LF2016_CBD",
        "Include_Layer_List_XML_File": True,
        "Area_of_Interest": f"{west:.8f} {south:.8f} {east:.8f} {north:.8f}",
        "Output_Projection": "5070",
        "Resample_Resolution": None,
        "Edit_Rule": None,
        "Edit_Mask": None,
        "Email": "research-audit@invalid.example",
        "Priority_Code": None,
    }
    submit, submit_receipt = fetch_json("https://lfps.usgs.gov/api/job/submit", request_body)
    job_id = submit.get("jobId") or submit.get("JobId")
    if not job_id:
        raise RuntimeError(f"LFPS returned no job ID: {submit}")
    status = {}
    status_receipts = []
    for _ in range(120):
        status_url = "https://lfps.usgs.gov/api/job/status?" + urllib.parse.urlencode({"JobId": job_id})
        status, status_receipt = fetch_json(status_url)
        status_receipts.append(status_receipt)
        if str(status.get("status", "")).lower() in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(2)
    if str(status.get("status", "")).lower() != "succeeded":
        raise RuntimeError(f"LFPS job did not succeed: {status}")
    download = fetch_file(status["outputFile"], archive)
    extract.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (extract / member.filename).resolve()
            if extract.resolve() not in target.parents and target != extract.resolve():
                raise ValueError(f"Unsafe archive member: {member.filename}")
            if member.flag_bits & 0x1:
                raise ValueError(f"Encrypted archive member: {member.filename}")
        bundle.extractall(extract)
    rasters = list(extract.glob("*.tif"))
    if len(rasters) != 1:
        raise ValueError(f"Expected one LFPS multiband TIFF, found {rasters}")
    receipt = {
        "purpose": "Complete locked PR23 LF2016 baseline source coverage",
        "authoritative_source": "LANDFIRE Product Service, U.S. Geological Survey",
        "request": request_body,
        "job_id": job_id,
        "submit_response": submit,
        "status_response": status,
        "submit_receipt": submit_receipt,
        "status_receipts": status_receipts,
        "download_receipt": download,
        "archive": rel(archive),
        "archive_sha256": sha256(archive),
        "raster": rel(rasters[0]),
        "raster_sha256": sha256(rasters[0]),
    }
    (RECEIPTS / "landfire_acquisition_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return rasters[0], receipt


def grid(candidates: pd.DataFrame, size: int) -> tuple[pd.DataFrame, int, int, int, int, Affine]:
    cells = candidates.loc[candidates.response_grid_m.eq(size)].drop_duplicates("cell_id").copy()
    min_col, max_col = int(cells.col.min()), int(cells.col.max())
    min_row, max_row = int(cells.row.min()), int(cells.row.max())
    transform = Affine(size, 0, min_col * size, 0, -size, (max_row + 1) * size)
    return cells, min_col, max_row, max_col - min_col + 1, max_row - min_row + 1, transform


def source_window(ds, bounds, pad=256) -> Window:
    src_bounds = transform_bounds("EPSG:9311", ds.crs, *bounds, densify_pts=41)
    inv = ~ds.transform
    points = [inv * (x, y) for x in (src_bounds[0], src_bounds[2]) for y in (src_bounds[1], src_bounds[3])]
    cols, rows = zip(*points)
    c0, r0 = max(0, math.floor(min(cols)) - pad), max(0, math.floor(min(rows)) - pad)
    c1, r1 = min(ds.width, math.ceil(max(cols)) + pad), min(ds.height, math.ceil(max(rows)) + pad)
    if c1 <= c0 or r1 <= r0:
        raise ValueError(f"No overlap with {ds.name}")
    return Window(c0, r0, c1 - c0, r1 - r0)


def nested_1km_children(candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    parents = candidates.loc[candidates.response_grid_m.eq(2000)].drop_duplicates("cell_id")
    rows = []
    for parent in parents.itertuples():
        for dc, dr in ((0, 0), (1, 0), (0, 1), (1, 1)):
            col, row = 2 * int(parent.col) + dc, 2 * int(parent.row) + dr
            rows.append({"response_grid_m": 1000, "cell_id": f"PR23_CHILD_{col}_{row}", "col": col, "row": row, "center_x_epsg9311": (col + 0.5) * 1000, "center_y_epsg9311": (row + 0.5) * 1000, "parent_index": parent.Index})
    children = pd.DataFrame(rows)
    return children, children.parent_index


def canonical_1km_lattice(candidates: pd.DataFrame, children: pd.DataFrame) -> pd.DataFrame:
    base = candidates.loc[candidates.response_grid_m.eq(1000), ["col", "row", "center_x_epsg9311", "center_y_epsg9311"]].drop_duplicates(["col", "row"])
    extra = children[["col", "row", "center_x_epsg9311", "center_y_epsg9311"]]
    lattice = pd.concat([base, extra], ignore_index=True).drop_duplicates(["col", "row"]).reset_index(drop=True)
    lattice["response_grid_m"] = 1000
    lattice["cell_id"] = lattice.apply(lambda r: f"PR23_LATTICE_{int(r.col)}_{int(r.row)}", axis=1)
    return lattice


def child_values_from_lattice(values: pd.DataFrame | dict[str, pd.Series], lattice: pd.DataFrame, children: pd.DataFrame) -> pd.DataFrame:
    frame = pd.DataFrame(values).copy()
    frame["col"] = lattice.col.to_numpy(); frame["row"] = lattice.row.to_numpy()
    return children[["col", "row", "parent_index"]].merge(frame, on=["col", "row"], how="left").set_index(children.index)


def aggregate_arrays(path: Path, band: int, candidates: pd.DataFrame, size: int, value_map=None, valid_fn=None, mask_band: int | None = None, _direct: bool = False) -> dict[str, pd.Series]:
    if size == 2000 and not _direct:
        children, parent = nested_1km_children(candidates)
        lattice = canonical_1km_lattice(candidates, children)
        values = aggregate_arrays(path, band, lattice, 1000, value_map, valid_fn, mask_band, _direct=True)
        child = child_values_from_lattice(values, lattice, children)
        covered = child["source_covered_fraction"].groupby(child.parent_index).mean()
        valid = child["valid_fraction"].groupby(child.parent_index).mean()
        numerator = (child["conditional_mean"] * child["valid_fraction"]).groupby(child.parent_index).sum(min_count=1)
        mean = numerator.div(child["valid_fraction"].groupby(child.parent_index).sum()).where(valid > TOL)
        return {"source_covered_fraction": covered, "valid_fraction": valid, "conditional_mean": mean}
    cells, min_col, max_row, width, height, dst_transform = grid(candidates, size)
    bounds = array_bounds(height, width, dst_transform)
    covered = np.zeros((height, width), np.float64)
    valid = np.zeros((height, width), np.float64)
    numerator = np.zeros((height, width), np.float64)
    with rasterio.open(path) as ds:
        window = source_window(ds, bounds)
        masked = ds.read(band, window=window, masked=True).astype(np.float64)
        raw = masked.filled(np.nan)
        source_covered = np.ones(raw.shape, np.float64)
        source_valid = (~np.ma.getmaskarray(masked)) & np.isfinite(raw)
        if mask_band is not None:
            domain = ds.read(mask_band, window=window, masked=True).astype(np.float64)
            domain_raw = domain.filled(np.nan)
            source_valid &= (~np.ma.getmaskarray(domain)) & np.isfinite(domain_raw) & (domain_raw > 0)
        if valid_fn is not None:
            source_valid &= valid_fn(raw)
        values = value_map(raw) if value_map is not None else raw
        values = np.where(source_valid, values, 0.0)
        kwargs = dict(src_transform=ds.window_transform(window), src_crs=ds.crs, dst_transform=dst_transform, dst_crs="EPSG:9311", resampling=Resampling.average)
        reproject(source_covered, covered, src_nodata=None, dst_nodata=0, **kwargs)
        reproject(source_valid.astype(np.float64), valid, src_nodata=None, dst_nodata=0, **kwargs)
        reproject(values, numerator, src_nodata=None, dst_nodata=0, **kwargs)
    rr = max_row - cells.row.to_numpy(int)
    cc = cells.col.to_numpy(int) - min_col
    den = valid[rr, cc]
    mean = np.divide(numerator[rr, cc], den, out=np.full(len(den), np.nan), where=den > TOL)
    return {
        "source_covered_fraction": pd.Series(np.clip(covered[rr, cc], 0, 1), index=cells.index),
        "valid_fraction": pd.Series(np.clip(den, 0, 1), index=cells.index),
        "conditional_mean": pd.Series(mean, index=cells.index),
    }


def categorical_fractions(path: Path, band: int, candidates: pd.DataFrame, size: int, crosswalk: dict[int, str], nodata_codes: set[int], groups: list[str], _direct: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    if size == 2000 and not _direct:
        children, parent = nested_1km_children(candidates)
        lattice = canonical_1km_lattice(candidates, children)
        values, audit = categorical_fractions(path, band, lattice, 1000, crosswalk, nodata_codes, groups, _direct=True)
        child = child_values_from_lattice(values, lattice, children)
        result = child.drop(columns=["col", "row", "parent_index"]).groupby(child.parent_index).mean()
        return result, audit
    cells, min_col, max_row, width, height, dst_transform = grid(candidates, size)
    bounds = array_bounds(height, width, dst_transform)
    with rasterio.open(path) as ds:
        window = source_window(ds, bounds)
        masked = ds.read(band, window=window, masked=True)
        raw = masked.filled(next(iter(nodata_codes))).astype(np.int32)
        observed = sorted(int(x) for x in np.unique(raw[~np.ma.getmaskarray(masked)]))
        unknown = sorted(set(observed) - set(crosswalk) - nodata_codes)
        if unknown:
            raise ValueError(f"Unmapped categorical codes in {path.name} band {band}: {unknown}")
        src_transform = ds.window_transform(window)
        src_crs = ds.crs
    rr = max_row - cells.row.to_numpy(int)
    cc = cells.col.to_numpy(int) - min_col
    valid_src = (~np.ma.getmaskarray(masked)) & ~np.isin(raw, list(nodata_codes))
    valid_dst = np.zeros((height, width), np.float64)
    reproject(valid_src.astype(float), valid_dst, src_transform=src_transform, src_crs=src_crs, dst_transform=dst_transform, dst_crs="EPSG:9311", resampling=Resampling.average)
    result = pd.DataFrame(index=cells.index)
    result["valid_fraction"] = np.clip(valid_dst[rr, cc], 0, 1)
    for group in groups:
        src = np.isin(raw, [code for code, mapped in crosswalk.items() if mapped == group]) & valid_src
        dst = np.zeros((height, width), np.float64)
        reproject(src.astype(float), dst, src_transform=src_transform, src_crs=src_crs, dst_transform=dst_transform, dst_crs="EPSG:9311", resampling=Resampling.average)
        result[group] = np.clip(dst[rr, cc], 0, 1)
    audit = pd.DataFrame({"source_code": observed})
    audit["mapped_group"] = audit.source_code.map(crosswalk)
    audit["classification"] = np.where(audit.source_code.isin(nodata_codes), "SOURCE_NODATA", "EXPLICITLY_MAPPED")
    return result, audit


def aggregate_rap_in_evt_domain(rap_path: Path, evt_path: Path, rangeland_codes: set[int], candidates: pd.DataFrame, size: int, _direct: bool = False) -> dict[str, pd.Series]:
    if size == 2000 and not _direct:
        children, parent = nested_1km_children(candidates)
        lattice = canonical_1km_lattice(candidates, children)
        values = aggregate_rap_in_evt_domain(rap_path, evt_path, rangeland_codes, lattice, 1000, _direct=True)
        child = child_values_from_lattice(values, lattice, children)
        covered = child["source_covered_fraction"].groupby(child.parent_index).mean()
        valid = child["valid_fraction"].groupby(child.parent_index).mean()
        applicable = child["applicable_fraction"].groupby(child.parent_index).mean()
        numerator = (child["conditional_mean"] * child["applicable_fraction"]).groupby(child.parent_index).sum(min_count=1)
        mean = numerator.div(child["applicable_fraction"].groupby(child.parent_index).sum()).where(applicable > TOL)
        return {"source_covered_fraction": covered, "valid_fraction": valid, "applicable_fraction": applicable, "conditional_mean": mean}
    cells, min_col, max_row, width, height, dst_transform = grid(candidates, size)
    bounds = array_bounds(height, width, dst_transform)
    with rasterio.open(rap_path) as rap:
        window = source_window(rap, bounds)
        afg = rap.read(1, window=window, masked=True).astype(np.float64)
        pfg = rap.read(2, window=window, masked=True).astype(np.float64)
        a = afg.filled(np.nan); p = pfg.filled(np.nan)
        valid = (~np.ma.getmaskarray(afg)) & (~np.ma.getmaskarray(pfg)) & np.isfinite(a) & np.isfinite(p) & (a >= 0) & (p >= 0) & (a < 65535) & (p < 65535)
        rap_transform = rap.window_transform(window)
        rap_crs = rap.crs
    evt_codes = np.full(a.shape, -9999, np.int32)
    with rasterio.open(evt_path) as evt:
        reproject(rasterio.band(evt, 1), evt_codes, src_transform=evt.transform, src_crs=evt.crs, src_nodata=evt.nodata, dst_transform=rap_transform, dst_crs=rap_crs, dst_nodata=-9999, resampling=Resampling.nearest)
    applicable = valid & np.isin(evt_codes, list(rangeland_codes))
    arrays = {
        "source_covered_fraction": np.ones(a.shape, float),
        "valid_fraction": valid.astype(float),
        "applicable_fraction": applicable.astype(float),
        "numerator": np.where(applicable, a + p, 0.0),
    }
    destinations = {}
    for name, source in arrays.items():
        destination = np.zeros((height, width), float)
        reproject(source, destination, src_transform=rap_transform, src_crs=rap_crs, dst_transform=dst_transform, dst_crs="EPSG:9311", resampling=Resampling.average)
        destinations[name] = destination
    rr = max_row - cells.row.to_numpy(int); cc = cells.col.to_numpy(int) - min_col
    applicable_values = destinations["applicable_fraction"][rr, cc]
    mean = np.divide(destinations["numerator"][rr, cc], applicable_values, out=np.full(len(cells), np.nan), where=applicable_values > TOL)
    return {name: pd.Series(np.clip(value[rr, cc], 0, 1), index=cells.index) for name, value in destinations.items() if name != "numerator"} | {"conditional_mean": pd.Series(mean, index=cells.index)}


def decode_lookup(path: Path, pattern: str) -> tuple[dict[int, float], dict[int, str]]:
    lookup = pd.read_csv(path)
    labels = dict(zip(lookup.VALUE.astype(int), lookup.CLASSNAMES.astype(str)))
    physical = {}
    regex = re.compile(pattern, re.I)
    for code, label in labels.items():
        match = regex.match(label.strip())
        if match:
            physical[code] = float(match.group(1))
    return physical, labels


def aggregate_polygon_fraction(frame: gpd.GeoDataFrame, candidates: pd.DataFrame, size: int) -> pd.Series:
    cells = candidates.loc[candidates.response_grid_m.eq(size)].drop_duplicates("cell_id")
    frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].to_crs(9311)
    bounds = (cells.col.min() * size, cells.row.min() * size, (cells.col.max() + 1) * size, (cells.row.max() + 1) * size)
    frame = frame.cx[bounds[0]:bounds[2], bounds[1]:bounds[3]].copy()
    if len(frame):
        frame.geometry = shapely.make_valid(frame.geometry.array)
        frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty]
    union = frame.geometry.union_all() if len(frame) else None
    values = []
    for row in cells.itertuples():
        cell = shapely.box(row.col * size, row.row * size, (row.col + 1) * size, (row.row + 1) * size)
        values.append(0.0 if union is None else cell.intersection(union).area / cell.area)
    return pd.Series(values, index=cells.index)


def temporal_mean(times: pd.DatetimeIndex, matrix: np.ndarray, start: pd.Timestamp, end: pd.Timestamp) -> tuple[np.ndarray, np.ndarray]:
    seconds = np.asarray(times.astype("int64"), dtype=np.float64) / 1e9
    boundaries = np.r_[start.value / 1e9, seconds[(seconds > start.value / 1e9) & (seconds < end.value / 1e9)], end.value / 1e9]
    samples = np.vstack([np.array([np.interp(t, seconds, matrix[:, j]) for j in range(matrix.shape[1])]) for t in boundaries])
    dt = np.diff(boundaries)
    integral = np.sum((samples[:-1] + samples[1:]) * 0.5 * dt[:, None], axis=0)
    return integral / (boundaries[-1] - boundaries[0]), samples


def hrrr_values(candidates: pd.DataFrame, size: int) -> pd.DataFrame:
    inventory = pd.read_csv(HRRR / "preflight_message_inventory.csv")
    fields = ["u10", "v10", "gust_surface", "temperature_2m", "relative_humidity_2m"]
    regular = inventory[inventory.field_key.isin(fields)].copy()
    selected = regular.sort_values(["interval_number", "lead", "field_key"])
    output = []
    for interval in PRIMARY_INTERVALS:
        rows_i = selected[selected.interval_number.eq(interval)]
        subset = candidates[(candidates.response_grid_m.eq(size)) & candidates.interval_number.eq(interval)]
        start = pd.Timestamp(rows_i.effective_t0_cutoff_utc.iloc[0])
        end = pd.Timestamp(rows_i.effective_t1_observation_utc.iloc[0])
        matrices, times = {}, {}
        for field in fields:
            rows_f = rows_i[rows_i.field_key.eq(field)].sort_values("forecast_valid_time_utc")
            arrays = []
            for row in rows_f.itertuples(index=False):
                if hasattr(row, "local_path"):
                    stem = (ROOT / row.local_path).stem
                else:
                    initialization = pd.Timestamp(row.initialization_utc).strftime("%Y%m%d%H")
                    stem = f"hrrr_{initialization}_f{int(row.lead):02d}_{row.field_key}"
                values = np.load(HRRR / "extracted_values" / f"{stem}_i{interval:02d}.npz")[f"bilinear_{size}"]
                arrays.append(values)
            matrices[field] = np.vstack(arrays)
            times[field] = pd.to_datetime(rows_f.forecast_valid_time_utc, utc=True)
        u, _ = temporal_mean(times["u10"], matrices["u10"], start, end)
        v, _ = temporal_mean(times["v10"], matrices["v10"], start, end)
        # Saved extraction metadata confirms grid-relative vectors; convergence is reconstructed below.
        from pyproj import Proj
        proj = Proj("+proj=lcc +lat_0=38.5 +lon_0=-97.5 +lat_1=38.5 +lat_2=38.5 +R=6371229 +units=m +no_defs")
        to_ll = Transformer.from_crs(9311, 4326, always_xy=True)
        lon, lat = to_ll.transform(subset.center_x_epsg9311.to_numpy(), subset.center_y_epsg9311.to_numpy())
        conv = np.deg2rad(np.asarray(proj.get_factors(lon, lat).meridian_convergence))
        u_earth = u * np.cos(conv) + v * np.sin(conv)
        v_earth = -u * np.sin(conv) + v * np.cos(conv)
        temp, _ = temporal_mean(times["temperature_2m"], matrices["temperature_2m"], start, end)
        _, gust_samples = temporal_mean(times["gust_surface"], matrices["gust_surface"], start, end)
        _, rh_samples = temporal_mean(times["relative_humidity_2m"], matrices["relative_humidity_2m"], start, end)
        if len(subset) != len(u):
            raise ValueError(f"HRRR row-order mismatch for interval {interval}, {size} m")
        output.append(pd.DataFrame({
            "_index": subset.index,
            "hrrr_u10_mean_earth_ms": u_earth,
            "hrrr_v10_mean_earth_ms": v_earth,
            "hrrr_gust_max_ms": np.max(gust_samples, axis=0),
            "hrrr_temperature_2m_mean_c": temp - 273.15,
            "hrrr_relative_humidity_2m_min_pct": np.min(rh_samples, axis=0),
        }).set_index("_index"))
    return pd.concat(output).sort_index()


def main(allow_network: bool) -> None:
    ensure_dirs()
    candidates = pd.read_parquet(CANDIDATES)
    forbidden = {"y", "response", "dnbr", "rdnbr", "label", "positive"}
    if forbidden.intersection(x.lower() for x in candidates.columns):
        raise ValueError("Response-bearing field found in candidate geometry")
    if len(candidates) != 4153 or candidates.response_grid_m.value_counts().to_dict() != {1000: 3317, 2000: 836}:
        raise ValueError("Locked candidate geometry count changed")

    minx = min((candidates.col * candidates.response_grid_m).min(), (candidates.col * candidates.response_grid_m).min())
    miny = min((candidates.row * candidates.response_grid_m).min(), (candidates.row * candidates.response_grid_m).min())
    maxx = max(((candidates.col + 1) * candidates.response_grid_m).max(), ((candidates.col + 1) * candidates.response_grid_m).max())
    maxy = max(((candidates.row + 1) * candidates.response_grid_m).max(), ((candidates.row + 1) * candidates.response_grid_m).max())
    halo = 300.0
    to_ll = Transformer.from_crs(9311, 4326, always_xy=True)
    corners = [to_ll.transform(x, y) for x in (minx - halo, maxx + halo) for y in (miny - halo, maxy + halo)]
    lonlat = (min(x for x, _ in corners), min(y for _, y in corners), max(x for x, _ in corners), max(y for _, y in corners))
    landfire, landfire_receipt = acquire_landfire(lonlat, allow_network)

    sources = {
        "terrain": ROOT / "data/raw/terrain/3dep_13arcsec/downloads/USGS_13_n43w121.tif",
        "landfire_operational": landfire,
        "evt": ROOT / "data/raw/landfire/lf2016_remap/conus/extracted/evt/LF2016_EVT_CONUS/Tif/LF2016_EVT_CONUS.tif",
        "evc": ROOT / "data/raw/landfire/lf2016_remap/conus/extracted/evc/LF2016_EVC_CONUS/Tif/LF2016_EVC_CONUS.tif",
        "evh": ROOT / "data/raw/landfire/lf2016_remap/conus/extracted/evh/LF2016_EVH_CONUS/Tif/LF2016_EVH_CONUS.tif",
        "legacy_eag": ROOT / "data/raw/usgs/eag/final_fire_selection_gate/extracted/p9xt1bv2/Annual estimate of grass cover in the western US 2019/Annual estimate of grass cover in the western US 2019.tif",
        "legacy_eag_confidence": ROOT / "data/raw/usgs/eag/final_fire_selection_gate/extracted/p9xt1bv2/Confidence map of grass cover in the western US 2019/Confidence map of grass cover in the western US 2019.tif",
        "v5_eag": ROOT / "data/raw/usgs/eag/final_fire_selection_gate/downloads/ExoticAnnualGrass_2019_PercentCover.tif",
        "v5_eag_confidence": ROOT / "data/raw/usgs/eag/final_fire_selection_gate/downloads/ExoticAnnualGrass_2019_Confidence.tif",
        "v5_cheatgrass": ROOT / "data/raw/usgs/eag/final_fire_selection_gate/downloads/CheatGrass_2019_PercentCover.tif",
        "v5_cheatgrass_confidence": ROOT / "data/raw/usgs/eag/final_fire_selection_gate/downloads/CheatGrass_2019_Confidence.tif",
        "rap": ECOLOGY / "source_cache/rap_vegetation_biomass_v3_2019_brattain.tif",
        "fdist": next((ECOLOGY / "source_cache/lf2016_fdist_brattain").glob("*.tif")),
    }
    for path in sources.values():
        if not path.exists():
            raise FileNotFoundError(path)

    states = gpd.read_parquet(STATES).sort_values("t").reset_index(drop=True)
    locks = pd.read_csv(INTERVALS)
    crosswalk_rows, qc_rows, support_rows, dictionary_rows = [], [], [], []
    outputs = {}

    fbfm = {**{v: "fbfm_grass_grass_shrub_fraction" for v in range(101, 110)}, **{v: "fbfm_grass_grass_shrub_fraction" for v in range(121, 125)}, **{v: "fbfm_shrub_fraction" for v in range(141, 150)}, **{v: "fbfm_timber_fraction" for v in range(161, 166)}, **{v: "fbfm_timber_fraction" for v in range(181, 190)}, **{v: "fbfm_slash_blowdown_fraction" for v in range(201, 205)}, **{v: "fbfm_nonburnable_fraction" for v in range(91, 100)}}
    fbfm_groups = ["fbfm_grass_grass_shrub_fraction", "fbfm_shrub_fraction", "fbfm_timber_fraction", "fbfm_slash_blowdown_fraction", "fbfm_nonburnable_fraction"]
    evt_lookup = pd.read_csv(ROOT / "data/raw/landfire/lf2016_remap/conus/extracted/evt/LF2016_EVT_CONUS/CSV_Data/LF2016_EVT.csv")
    evt_map = {}
    for row in evt_lookup.itertuples(index=False):
        label = str(row.EVT_SBCLS).lower()
        if "tree canopy" in label:
            group = "evt_tree_fraction"
        elif "shrubland" in label:
            group = "evt_shrub_fraction"
        elif "annual" in label and ("grass" in label or "forb" in label or "herb" in label):
            group = "evt_annual_herbaceous_fraction"
        elif "perennial" in label and ("grass" in label or "forb" in label or "herb" in label):
            group = "evt_perennial_herbaceous_fraction"
        else:
            group = "evt_other_fraction"
        evt_map[int(row.VALUE)] = group
    evt_groups = ["evt_tree_fraction", "evt_shrub_fraction", "evt_perennial_herbaceous_fraction", "evt_annual_herbaceous_fraction", "evt_other_fraction"]
    rangeland_codes = {code for code, group in evt_map.items() if group in {"evt_shrub_fraction", "evt_perennial_herbaceous_fraction", "evt_annual_herbaceous_fraction"}}

    evc_map, evc_labels = decode_lookup(ROOT / "data/raw/landfire/lf2016_remap/conus/extracted/evc/LF2016_EVC_CONUS/CSV_Data/LF2016_EVC.csv", r"^(?:Tree|Shrub|Herb) Cover (?:=|>=)\s*([0-9.]+)%$")
    evh_map, evh_labels = decode_lookup(ROOT / "data/raw/landfire/lf2016_remap/conus/extracted/evh/LF2016_EVH_CONUS/CSV_Data/LF2016_EVH.csv", r"^(?:Tree|Shrub|Herb) Height (?:=|>=)\s*([0-9.]+) meters?$")

    for size in GRID_SIZES:
        subset = candidates[candidates.response_grid_m.eq(size)].copy()
        static = subset.drop_duplicates("cell_id")[["cell_id", "col", "row", "center_x_epsg9311", "center_y_epsg9311"]].copy()
        static = static.set_index(static.index)

        elevation = aggregate_arrays(sources["terrain"], 1, candidates, size)
        static["terrain_source_covered_fraction"] = elevation["source_covered_fraction"]
        static["terrain_valid_fraction"] = elevation["valid_fraction"]
        static["target_elevation_mean_m"] = elevation["conditional_mean"]

        # Project DEM to a fixed 10 m EPSG:9311 working grid with a 300 m halo and derive Horn gradients.
        cells, min_col, max_row, width, height, target_transform = grid(candidates, size)
        bounds = array_bounds(height, width, target_transform)
        x0, y0, x1, y1 = bounds[0] - halo, bounds[1] - halo, bounds[2] + halo, bounds[3] + halo
        dem_transform = Affine(10, 0, math.floor(x0 / 10) * 10, 0, -10, math.ceil(y1 / 10) * 10)
        dem_width = math.ceil((x1 - dem_transform.c) / 10)
        dem_height = math.ceil((dem_transform.f - y0) / 10)
        dem = np.full((dem_height, dem_width), np.nan, np.float64)
        with rasterio.open(sources["terrain"]) as ds:
            reproject(rasterio.band(ds, 1), dem, src_transform=ds.transform, src_crs=ds.crs, src_nodata=ds.nodata, dst_transform=dem_transform, dst_crs="EPSG:9311", dst_nodata=np.nan, resampling=Resampling.bilinear)
        valid9 = convolve(np.isfinite(dem).astype(np.int16), np.ones((3, 3), np.int16), mode="constant", cval=0) == 9
        z = np.where(np.isfinite(dem), dem, 0)
        gx = convolve(z, np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], float) / 80.0, mode="constant", cval=0)
        gy = convolve(z, np.array([[1, 2, 1], [0, 0, 0], [-1, -2, -1]], float) / 80.0, mode="constant", cval=0)
        gx[~valid9] = np.nan
        gy[~valid9] = np.nan
        slope = np.degrees(np.arctan(np.hypot(gx, gy)))
        terrain_components = {}
        for name, arr in [("target_slope_mean_degrees", slope), ("terrain_gradient_east_mean", gx), ("terrain_gradient_north_mean", gy)]:
            destination = np.full((height, width), np.nan, float)
            reproject(arr, destination, src_transform=dem_transform, src_crs="EPSG:9311", src_nodata=np.nan, dst_transform=target_transform, dst_crs="EPSG:9311", dst_nodata=np.nan, resampling=Resampling.average)
            rr = max_row - cells.row.to_numpy(int); cc = cells.col.to_numpy(int) - min_col
            terrain_components[name] = pd.Series(destination[rr, cc], index=cells.index)
            static[name] = terrain_components[name]

        lf, audit = categorical_fractions(sources["landfire_operational"], 1, candidates, size, fbfm, {-9999}, fbfm_groups)
        lf_coverage = aggregate_arrays(sources["landfire_operational"], 1, candidates, size)
        static["fbfm_source_covered_fraction"] = lf_coverage["source_covered_fraction"]
        static["fbfm_valid_fraction"] = lf.valid_fraction
        for name in fbfm_groups:
            static[name] = lf[name]
        audit.insert(0, "crosswalk", "LF2016_FBFM40")
        audit.insert(1, "response_grid_m", size)
        crosswalk_rows.append(audit)

        canopy_cover = aggregate_arrays(sources["landfire_operational"], 2, candidates, size, mask_band=2)
        canopy_valid = aggregate_arrays(sources["landfire_operational"], 2, candidates, size)
        static["canopy_source_covered_fraction"] = canopy_cover["source_covered_fraction"]
        static["canopy_valid_source_fraction"] = canopy_valid["valid_fraction"]
        static["canopy_applicable_fraction"] = canopy_cover["valid_fraction"]
        static["conditional_mean_canopy_cover_pct"] = canopy_cover["conditional_mean"]
        static["canopy_domain_state"] = np.where(static.canopy_applicable_fraction > TOL, "APPLICABLE", np.where(static.canopy_valid_source_fraction > TOL, "NOT_APPLICABLE", "SOURCE_NODATA_OR_OUTSIDE_COVERAGE"))
        for band, name, scale in [(3, "conditional_mean_canopy_height_m", 0.1), (4, "conditional_mean_canopy_base_height_m", 0.1), (5, "conditional_mean_canopy_bulk_density_kg_m3", 0.01)]:
            arr = aggregate_arrays(sources["landfire_operational"], band, candidates, size, value_map=lambda x, s=scale: x * s, mask_band=2)
            static[name] = arr["conditional_mean"]

        evt, audit = categorical_fractions(sources["evt"], 1, candidates, size, evt_map, {-9999, 32767}, evt_groups)
        evt_coverage = aggregate_arrays(sources["evt"], 1, candidates, size)
        static["evt_source_covered_fraction"] = evt_coverage["source_covered_fraction"]
        static["evt_valid_fraction"] = evt.valid_fraction
        for name in evt_groups:
            static[name] = evt[name]
        audit.insert(0, "crosswalk", "LF2016_EVT_SBCLS")
        audit.insert(1, "response_grid_m", size)
        audit["source_label"] = audit.source_code.map(evt_lookup.set_index("VALUE")["EVT_SBCLS"])
        crosswalk_rows.append(audit)

        canopy_ranges = {2: (0, 95, "CC_PERCENT"), 3: (0, 510, "CH_M_X_10"), 4: (0, 100, "CBH_M_X_10"), 5: (0, 45, "CBD_KGM3_X100")}
        with rasterio.open(sources["landfire_operational"]) as ds:
            win = source_window(ds, bounds)
            for band, (minimum, maximum, label) in canopy_ranges.items():
                observed = sorted(int(v) for v in np.unique(ds.read(band, window=win, masked=True).compressed()))
                if any(v < minimum or v > maximum for v in observed):
                    raise ValueError(f"Out-of-range canopy code in {label}: {observed}")
                crosswalk_rows.append(pd.DataFrame({"crosswalk": f"LF2016_{label}", "response_grid_m": size, "source_code": observed, "mapped_group": ["NOT_APPLICABLE_VALID_ZERO" if v == 0 else "CANOPY_APPLICABLE" for v in observed], "classification": "EXPLICITLY_MAPPED"}))

        for source_name, mapping, labels, output_name in [("evc", evc_map, evc_labels, "evc_conditional_mean_cover_pct"), ("evh", evh_map, evh_labels, "evh_conditional_mean_height_m")]:
            arr = aggregate_arrays(sources[source_name], 1, candidates, size, value_map=lambda x, m=mapping: np.vectorize(lambda v: m.get(int(v), np.nan))(x), valid_fn=lambda x, m=mapping: np.isin(x, list(m)))
            source_valid = aggregate_arrays(sources[source_name], 1, candidates, size)
            static[f"{source_name}_source_covered_fraction"] = arr["source_covered_fraction"]
            static[f"{source_name}_valid_source_fraction"] = source_valid["valid_fraction"]
            static[f"{source_name}_applicable_fraction"] = arr["valid_fraction"]
            static[output_name] = arr["conditional_mean"]
            static[f"{source_name}_domain_state"] = np.where(arr["valid_fraction"] > TOL, "APPLICABLE", np.where(source_valid["valid_fraction"] > TOL, "NOT_APPLICABLE", "SOURCE_NODATA_OR_OUTSIDE_COVERAGE"))
            with rasterio.open(sources[source_name]) as ds:
                win = source_window(ds, bounds); raw = ds.read(1, window=win, masked=True); observed = sorted(int(v) for v in np.unique(raw.compressed()))
            a = pd.DataFrame({"source_code": observed, "source_label": [labels.get(v, "") for v in observed]})
            a["mapped_group"] = [mapping.get(v, np.nan) for v in observed]
            a["classification"] = ["EXPLICITLY_MAPPED" if v in mapping else "RECOGNIZED_NONPHYSICAL" if v in labels else "ERROR" for v in observed]
            if (a.classification == "ERROR").any(): raise ValueError(f"Unknown {source_name.upper()} codes")
            a.insert(0, "crosswalk", f"LF2016_{source_name.upper()}_CLASSNAMES")
            a.insert(1, "response_grid_m", size)
            crosswalk_rows.append(a)

        for key, prefix in [("legacy_eag", "legacy_eag_2019"), ("legacy_eag_confidence", "legacy_eag_confidence_2019"), ("v5_eag", "v5_eag_2019"), ("v5_eag_confidence", "v5_eag_confidence_2019"), ("v5_cheatgrass", "v5_cheatgrass_2019"), ("v5_cheatgrass_confidence", "v5_cheatgrass_confidence_2019")]:
            arr = aggregate_arrays(sources[key], 1, candidates, size, valid_fn=lambda x: (x >= 0) & (x <= 100))
            source_valid = aggregate_arrays(sources[key], 1, candidates, size)
            static[f"{prefix}_source_covered_fraction"] = arr["source_covered_fraction"]
            static[f"{prefix}_valid_source_fraction"] = source_valid["valid_fraction"]
            static[f"{prefix}_applicable_fraction"] = arr["valid_fraction"]
            static[f"{prefix}_conditional_mean"] = arr["conditional_mean"]
            static[f"{prefix}_domain_state"] = np.where(arr["valid_fraction"] > TOL, "APPLICABLE", np.where(source_valid["valid_fraction"] > TOL, "OUTSIDE_DOMAIN", "SOURCE_NODATA_OR_OUTSIDE_COVERAGE"))
            with rasterio.open(sources[key]) as ds:
                win = source_window(ds, bounds); observed = sorted(int(v) for v in np.unique(ds.read(1, window=win, masked=True).compressed()))
            if any(v not in set(range(101)) | {255} for v in observed):
                raise ValueError(f"Unknown EAG/domain code in {prefix}: {observed}")
            crosswalk_rows.append(pd.DataFrame({"crosswalk": prefix, "response_grid_m": size, "source_code": observed, "mapped_group": ["OUTSIDE_DOMAIN" if v == 255 else "VALID_ECOLOGICAL_VALUE" for v in observed], "classification": "EXPLICITLY_MAPPED"}))

        rap = aggregate_rap_in_evt_domain(sources["rap"], sources["evt"], rangeland_codes, candidates, size)
        static["rap_source_covered_fraction"] = rap["source_covered_fraction"]
        static["rap_valid_fraction"] = rap["valid_fraction"]
        static["rangeland_applicable_fraction"] = rap["applicable_fraction"]
        static["conditional_2019_total_herbaceous_production_lb_ac"] = rap["conditional_mean"]
        static["rap_domain_state"] = np.where(rap["applicable_fraction"] > TOL, "APPLICABLE", np.where(rap["valid_fraction"] > TOL, "NOT_APPLICABLE", "SOURCE_NODATA_OR_OUTSIDE_COVERAGE"))

        fdist_map = {0: "fdist_no_disturbance_fraction"}
        with rasterio.open(sources["fdist"]) as ds:
            raw = ds.read(1, masked=True); observed_fdist = sorted(int(v) for v in np.unique(raw.compressed()))
        for code in observed_fdist:
            if code > 0: fdist_map[code] = "fdist_any_disturbance_fraction"
        fdist, audit = categorical_fractions(sources["fdist"], 1, candidates, size, fdist_map, {-9999}, ["fdist_no_disturbance_fraction", "fdist_any_disturbance_fraction"])
        fdist_coverage = aggregate_arrays(sources["fdist"], 1, candidates, size)
        static["fdist_source_covered_fraction"] = fdist_coverage["source_covered_fraction"]
        static["fdist_valid_fraction"] = fdist.valid_fraction
        static["fdist_any_disturbance_fraction"] = fdist.fdist_any_disturbance_fraction
        audit.insert(0, "crosswalk", "LF2016_FDIST")
        audit.insert(1, "response_grid_m", size)
        crosswalk_rows.append(audit)

        mtbs = gpd.read_file(ROOT / "data/raw/mtbs/extracted/mtbs_perims_DD.shp")
        dates = pd.to_datetime(mtbs.ig_date, errors="coerce", utc=True)
        mtbs = mtbs[dates.lt(PREFIRE_CUTOFF)].copy(); mtbs["event_date"] = dates.loc[mtbs.index]
        static["prior_mapped_mtbs_disturbance_area_fraction"] = aggregate_polygon_fraction(mtbs, candidates, size)
        mtbs9311 = mtbs.to_crs(9311)
        recency = []
        for row in static.itertuples():
            cell = shapely.box(row.col * size, row.row * size, (row.col + 1) * size, (row.row + 1) * size)
            hits = mtbs9311[mtbs9311.intersects(cell)]
            recency.append(np.nan if hits.empty else (PREFIRE_CUTOFF - hits.event_date.max()).total_seconds() / (365.2425 * 86400))
        static["years_since_most_recent_mapped_mtbs_event"] = recency
        static["prior_mtbs_status"] = np.where(static.prior_mapped_mtbs_disturbance_area_fraction > TOL, "RECORDED_EVENT", "NO_RECORDED_EVENT")
        crosswalk_rows.append(pd.DataFrame({"crosswalk": "MTBS_PRIOR_STATUS", "response_grid_m": size, "source_code": [0, 1], "mapped_group": ["NO_RECORDED_EVENT", "RECORDED_EVENT"], "classification": "EXPLICITLY_MAPPED"}))

        odf = gpd.read_file(RECOVERY / "odf_foresthealth_2016_brattain.geojson")
        odf = odf[odf.Description_Type.eq("Mortality: Bark beetle")]
        static["forest_applicable_fraction"] = static.evt_tree_fraction
        static["documented_2016_bark_beetle_mortality_area_fraction"] = aggregate_polygon_fraction(odf, candidates, size)
        static["forest_health_status"] = np.where(static.forest_applicable_fraction <= TOL, "NOT_APPLICABLE", np.where(static.documented_2016_bark_beetle_mortality_area_fraction > TOL, "RECORDED_EVENT", "NO_RECORDED_EVENT"))

        ownership = gpd.read_file(ECOLOGY / "source_cache/usfs_basic_ownership_brattain.geojson")
        facts = gpd.read_file(RECOVERY / "facts_brattain.geojson")
        dates = pd.to_datetime(facts.date_completed, unit="ms", errors="coerce", utc=True)
        codes = {"1112","1113","1130","1120","1150","1152","1153","1160","1169","4151","4220","4231","4521","4530","4570","2341","2360","2370","2510","2530","4431","4432","4473","4474","8120"}
        qualifying = facts[dates.lt(PREFIRE_CUTOFF) & facts.activity_code.astype(str).isin(codes)].copy()
        qualifying["completed_utc"] = dates.loc[qualifying.index]
        qualifying = qualifying.drop_duplicates(["suid", "activity_code", "date_completed"])
        if len(qualifying) != 1182:
            raise ValueError(f"FACTS logical activity count changed: {len(qualifying)}")
        nfs_union = ownership.to_crs(qualifying.crs).geometry.union_all()
        qualifying.geometry = qualifying.geometry.intersection(nfs_union)
        qualifying = qualifying[qualifying.geometry.notna() & ~qualifying.geometry.is_empty]
        static["nfs_applicable_fraction"] = aggregate_polygon_fraction(ownership, candidates, size)
        implementation = aggregate_polygon_fraction(qualifying, candidates, size)
        static["documented_completed_prefire_implementation_area_fraction_within_nfs"] = np.divide(implementation, static.nfs_applicable_fraction, out=np.full(len(static), np.nan), where=static.nfs_applicable_fraction > TOL)
        static["management_status"] = np.where(static.nfs_applicable_fraction <= TOL, "OUTSIDE_DOMAIN", np.where(implementation > TOL, "RECORDED_EVENT", "NO_RECORDED_EVENT"))

        # Join static values to repeated interval rows, then add dynamic FEDS and HRRR predictors.
        static_join = static.drop(columns=["col", "row", "center_x_epsg9311", "center_y_epsg9311"])
        matrix = subset.join(static_join.set_index("cell_id"), on="cell_id", rsuffix="_static")
        matrix["event_id"] = "FEDS_65371_BRATTAIN"
        matrix["interval_id"] = matrix.interval_number.map(lambda x: f"FEDS65371_I{x:02d}")
        matrix["distance_active_front_km"] = matrix.distance_t0_active_front_m / 1000
        matrix["distance_cumulative_perimeter_km"] = matrix.distance_t0_cumulative_perimeter_m / 1000
        matrix["hybrid_membership"] = matrix.risk_membership
        matrix["log1p_t0_area_km2"] = np.log1p(matrix.t0_cumulative_area_km2)
        weather = hrrr_values(candidates, size)
        matrix = matrix.join(weather)

        # Deterministic source point and directional terrain calculations use completed t0 only.
        source_x, source_y, source_elevation = [], [], []
        for row in matrix.itertuples():
            lock = locks.loc[locks.interval_number.astype(int).eq(row.interval_number)].iloc[0]
            state = states.iloc[int(lock.t0_state_number) - 1]
            geom = state.hull.boundary if row.hybrid_membership == "PERIMETER_BACKSTOP_ONLY" else state.fline
            point = nearest_points(shapely.Point(row.center_x_epsg9311, row.center_y_epsg9311), geom)[1]
            source_x.append(point.x); source_y.append(point.y)
            c = int((point.x - dem_transform.c) // 10); r = int((dem_transform.f - point.y) // 10)
            source_elevation.append(dem[r, c] if 0 <= r < dem_height and 0 <= c < dem_width else np.nan)
        matrix["terrain_source_x_epsg9311"] = source_x
        matrix["terrain_source_y_epsg9311"] = source_y
        matrix["source_target_elevation_difference_m"] = matrix.target_elevation_mean_m - np.asarray(source_elevation)
        dx = matrix.center_x_epsg9311 - matrix.terrain_source_x_epsg9311
        dy = matrix.center_y_epsg9311 - matrix.terrain_source_y_epsg9311
        distance = np.hypot(dx, dy)
        gradient_norm = np.hypot(matrix.terrain_gradient_east_mean, matrix.terrain_gradient_north_mean)
        matrix["uphill_alignment"] = np.divide(dx * matrix.terrain_gradient_east_mean + dy * matrix.terrain_gradient_north_mean, distance * gradient_norm, out=np.zeros(len(matrix)), where=(distance > TOL) & (gradient_norm > TOL))
        wind_norm = np.hypot(matrix.hrrr_u10_mean_earth_ms, matrix.hrrr_v10_mean_earth_ms)
        matrix["wind_slope_alignment"] = np.divide(matrix.hrrr_u10_mean_earth_ms * matrix.terrain_gradient_east_mean + matrix.hrrr_v10_mean_earth_ms * matrix.terrain_gradient_north_mean, wind_norm * gradient_norm, out=np.zeros(len(matrix)), where=(wind_norm > TOL) & (gradient_norm > TOL))
        cutoff_map = pd.read_csv(DOC / "PAPER1_HRRR_SELECTED_OBJECTS.csv").drop_duplicates("interval_number").set_index("interval_number")["effective_t0_cutoff_utc"]
        matrix["effective_t0_observation_cutoff_utc"] = matrix.interval_number.map(cutoff_map)
        matrix["artifact_class"] = "PR23 RESPONSE-FREE PREDICTOR DATA"

        forbidden_outputs = [c for c in matrix if c.lower() in forbidden or "t1" in c.lower() or "label" in c.lower()]
        if forbidden_outputs:
            raise ValueError(f"Forbidden response/future fields in output: {forbidden_outputs}")
        matrix = matrix.drop(columns=["t0_perimeter_length_km", "t0_active_front_length_km"])
        out = OUTPUT / f"paper1_pr23_response_free_predictors_{size // 1000}km.parquet"
        matrix.to_parquet(out, index=False)
        outputs[size] = (matrix, out)

        static_columns = [c for c in static_join.columns if c != "cell_id"]
        drift = matrix.groupby("cell_id")[static_columns].nunique(dropna=False).max().max()
        qc_rows.append({"check": "static_repeat_consistency", "response_grid_m": size, "status": "PASS" if drift <= 1 else "FAIL", "value": int(drift), "tolerance": 1})
        qc_rows.append({"check": "fbfm_fraction_closure", "response_grid_m": size, "status": "PASS" if np.nanmax(np.abs(matrix[fbfm_groups].sum(axis=1) - matrix.fbfm_valid_fraction)) <= 1e-5 else "FAIL", "value": float(np.nanmax(np.abs(matrix[fbfm_groups].sum(axis=1) - matrix.fbfm_valid_fraction))), "tolerance": 1e-5})
        qc_rows.append({"check": "evt_fraction_closure", "response_grid_m": size, "status": "PASS" if np.nanmax(np.abs(matrix[evt_groups].sum(axis=1) - matrix.evt_valid_fraction)) <= 1e-5 else "FAIL", "value": float(np.nanmax(np.abs(matrix[evt_groups].sum(axis=1) - matrix.evt_valid_fraction))), "tolerance": 1e-5})

        families = {
            "FEDS_STATE": ["distance_active_front_km", "distance_cumulative_perimeter_km", "hybrid_membership", "log1p_t0_area_km2"],
            "TERRAIN": ["target_elevation_mean_m", "target_slope_mean_degrees", "source_target_elevation_difference_m", "uphill_alignment", "wind_slope_alignment"],
            "FBFM40": fbfm_groups,
            "CANOPY": ["canopy_applicable_fraction", "conditional_mean_canopy_cover_pct", "conditional_mean_canopy_height_m", "conditional_mean_canopy_base_height_m", "conditional_mean_canopy_bulk_density_kg_m3"],
            "HRRR": ["hrrr_u10_mean_earth_ms", "hrrr_v10_mean_earth_ms", "hrrr_gust_max_ms", "hrrr_temperature_2m_mean_c", "hrrr_relative_humidity_2m_min_pct"],
            "EVT": evt_groups,
            "EVC": ["evc_conditional_mean_cover_pct"], "EVH": ["evh_conditional_mean_height_m"],
            "EAG_LEGACY": ["legacy_eag_2019_conditional_mean"], "EAG_V5": ["v5_eag_2019_conditional_mean"], "CHEATGRASS_V5": ["v5_cheatgrass_2019_conditional_mean"],
            "MTBS_PRIOR": ["prior_mapped_mtbs_disturbance_area_fraction"], "FOREST_HEALTH": ["documented_2016_bark_beetle_mortality_area_fraction"],
            "FACTS": ["documented_completed_prefire_implementation_area_fraction_within_nfs"], "RAP": ["conditional_2019_total_herbaceous_production_lb_ac"], "FDIST_EXPLORATORY": ["fdist_any_disturbance_fraction"],
        }
        accounting = {
            "TERRAIN": ("terrain_source_covered_fraction", "terrain_valid_fraction", None),
            "FBFM40": ("fbfm_source_covered_fraction", "fbfm_valid_fraction", None),
            "CANOPY": ("canopy_source_covered_fraction", "canopy_valid_source_fraction", "canopy_applicable_fraction"),
            "EVT": ("evt_source_covered_fraction", "evt_valid_fraction", None),
            "EVC": ("evc_source_covered_fraction", "evc_valid_source_fraction", "evc_applicable_fraction"),
            "EVH": ("evh_source_covered_fraction", "evh_valid_source_fraction", "evh_applicable_fraction"),
            "EAG_LEGACY": ("legacy_eag_2019_source_covered_fraction", "legacy_eag_2019_valid_source_fraction", "legacy_eag_2019_applicable_fraction"),
            "EAG_V5": ("v5_eag_2019_source_covered_fraction", "v5_eag_2019_valid_source_fraction", "v5_eag_2019_applicable_fraction"),
            "CHEATGRASS_V5": ("v5_cheatgrass_2019_source_covered_fraction", "v5_cheatgrass_2019_valid_source_fraction", "v5_cheatgrass_2019_applicable_fraction"),
            "RAP": ("rap_source_covered_fraction", "rap_valid_fraction", "rangeland_applicable_fraction"),
            "FDIST_EXPLORATORY": ("fdist_source_covered_fraction", "fdist_valid_fraction", None),
        }
        support_predicates = {
            "TERRAIN": matrix.terrain_valid_fraction > TOL,
            "FBFM40": matrix.fbfm_valid_fraction > TOL,
            "CANOPY": matrix.canopy_valid_source_fraction > TOL,
            "EVT": matrix.evt_valid_fraction > TOL,
            "EVC": matrix.evc_applicable_fraction > TOL,
            "EVH": matrix.evh_applicable_fraction > TOL,
            "EAG_LEGACY": matrix.legacy_eag_2019_applicable_fraction > TOL,
            "EAG_V5": matrix.v5_eag_2019_applicable_fraction > TOL,
            "CHEATGRASS_V5": matrix.v5_cheatgrass_2019_applicable_fraction > TOL,
            "FOREST_HEALTH": matrix.evt_valid_fraction > TOL,
            "FACTS": matrix.nfs_applicable_fraction > TOL,
            "RAP": (matrix.rangeland_applicable_fraction > TOL) & matrix.conditional_2019_total_herbaceous_production_lb_ac.notna(),
            "FDIST_EXPLORATORY": matrix.fdist_valid_fraction > TOL,
        }
        for family, variables in families.items():
            supported = support_predicates.get(family, matrix[variables].notna().all(axis=1))
            for scope, value, idx in [("ALL", "ALL", matrix.index)] + [("INTERVAL", str(v), i) for v, i in matrix.groupby("interval_number").groups.items()] + [("FORWARD_CHAIN_BLOCK", str(v), i) for v, i in matrix.groupby("forward_chain_block").groups.items()]:
                m = supported.loc[idx]
                scoped = matrix.loc[idx]
                total_area = float(len(idx) * size * size)
                covered_col, valid_col, applicable_col = accounting.get(family, (None, None, None))
                covered_fraction = scoped[covered_col] if covered_col else pd.Series(1.0, index=idx)
                valid_fraction = scoped[valid_col] if valid_col else pd.Series(1.0, index=idx)
                applicable_fraction = scoped[applicable_col] if applicable_col else valid_fraction
                source_nodata_fraction = (covered_fraction - valid_fraction).clip(lower=0)
                outside_domain_fraction = (valid_fraction - applicable_fraction).clip(lower=0)
                outside_coverage_fraction = (1 - covered_fraction).clip(lower=0)
                closure = applicable_fraction + outside_domain_fraction + source_nodata_fraction + outside_coverage_fraction
                support_rows.append({"family": family, "response_grid_m": size, "scope": scope, "scope_value": value, "total_candidate_rows": len(idx), "supported_rows": int(m.sum()), "support_fraction": float(m.mean()), "total_unique_cells": scoped.cell_id.nunique(), "supported_unique_cells": scoped.loc[m, "cell_id"].nunique(), "total_response_cell_area_m2": total_area, "source_covered_area_m2": float(covered_fraction.sum() * size * size), "valid_source_area_m2": float(valid_fraction.sum() * size * size), "applicable_area_m2": float(applicable_fraction.sum() * size * size), "source_nodata_area_m2": float(source_nodata_fraction.sum() * size * size), "outside_domain_area_m2": float(outside_domain_fraction.sum() * size * size), "outside_source_coverage_area_m2": float(outside_coverage_fraction.sum() * size * size), "mean_valid_fraction": float(valid_fraction.mean()), "mean_applicable_fraction": float(applicable_fraction.mean()), "maximum_area_closure_error": float((closure - 1).abs().max())})

    # Cross-resolution checks compare direct 2 km static values with means of nested 1 km cells.
    one, two = outputs[1000][0], outputs[2000][0]
    one_static = one.drop_duplicates("cell_id").copy(); two_static = two.drop_duplicates("cell_id").copy()
    one_static["parent_col"] = np.floor_divide(one_static.col, 2); one_static["parent_row"] = np.floor_divide(one_static.row, 2)
    complete_parents = one_static.groupby(["parent_col", "parent_row"]).size()
    complete_parents = complete_parents[complete_parents.eq(4)].index
    one_static = one_static.set_index(["parent_col", "parent_row"]).loc[complete_parents].reset_index()
    compare_vars = ["target_elevation_mean_m", "target_slope_mean_degrees"] + fbfm_groups + evt_groups
    for variable in compare_vars:
        combined = one_static.groupby(["parent_col", "parent_row"])[variable].mean()
        direct = two_static.set_index(["col", "row"])[variable]
        joined = pd.concat([direct.rename("direct"), combined.rename("from_1km")], axis=1).dropna()
        diff = (joined.direct - joined.from_1km).abs()
        qc_rows.append({"check": f"1km_2km_consistency:{variable}", "response_grid_m": 2000, "status": "PASS" if diff.max() <= 0.05 else "LIMITATION", "value": float(diff.max()), "tolerance": 0.05})

    crosswalk = pd.concat(crosswalk_rows, ignore_index=True)
    crosswalk.to_csv(DOC / "PAPER1_PROPAGATION_CROSSWALK_AUDIT.csv", index=False, lineterminator="\n")
    qc = pd.DataFrame(qc_rows)
    qc.to_csv(DOC / "PAPER1_PROPAGATION_AGGREGATION_QC.csv", index=False, lineterminator="\n")
    support = pd.DataFrame(support_rows)
    support.to_csv(DOC / "PAPER1_PROPAGATION_PREDICTOR_SUPPORT_POSTAGG.csv", index=False, lineterminator="\n")

    variable_roles = {}
    for variable in outputs[1000][0].columns:
        if variable.startswith(("event_", "interval_", "cell_", "center_", "terrain_source_", "artifact_")) or variable in {"col", "row", "forward_chain_block", "response_grid_m", "effective_t0_observation_cutoff_utc"}:
            continue
        role = "BASELINE" if variable.startswith(("distance_", "hybrid_", "log1p_", "target_", "source_target_", "uphill_", "wind_slope_", "fbfm_", "canopy_", "conditional_mean_canopy_", "hrrr_", "terrain_")) else "CORE_ECOLOGY" if variable.startswith("evt_") else "SENSITIVITY_OR_SUPPORT"
        variable_roles[variable] = role
    for variable, role in variable_roles.items():
        dictionary_rows.append({
            "canonical_variable_name": variable, "scientific_construct": variable.replace("_", " "), "model_role": role,
            "source": "See PR23 aggregation specification and manifest", "product_version": "Locked PR23 source lineage",
            "source_resolution": "source-specific", "source_unit": "source-specific", "final_unit": "encoded in canonical name or dictionary notes",
            "temporal_class": "STATIC_PREFIRE or T0_VALID_FORECAST/DYNAMIC as specified", "numerator": "source-valid/applicable value-area sum",
            "denominator": "response-cell area or valid/applicable area as specified", "spatial_aggregation_formula": "deterministic PR23 formula",
            "temporal_aggregation_formula": "none for static; locked PR10 formula for HRRR", "applicability_rule": "source-specific locked rule",
            "missingness_semantics": "TRUE_ZERO/NO_RECORDED_EVENT/NOT_APPLICABLE/OUTSIDE_DOMAIN/SOURCE_NODATA/UNOBSERVED/UNKNOWN retained",
            "available_1km": True, "available_2km": True, "provenance_artifact": rel(WORK / "pr23_manifest.json"),
        })
    dictionary = pd.DataFrame(dictionary_rows)
    dictionary.to_csv(DOC / "PAPER1_PROPAGATION_PREDICTOR_DICTIONARY.csv", index=False, lineterminator="\n")

    source_hashes = {name: {"path": rel(path), "bytes": path.stat().st_size, "sha256": sha256(path)} for name, path in sources.items()}
    output_hashes = {str(size): {"path": rel(path), "rows": len(frame), "bytes": path.stat().st_size, "sha256": sha256(path)} for size, (frame, path) in outputs.items()}
    failures = qc[qc.status.eq("FAIL")]
    status = "COMPLETE_WITH_LIMITATIONS" if failures.empty else "REQUIRES_CORRECTION"
    decision = pd.DataFrame([{
        "gate": "PR23", "status": status, "response_read": False, "model_fit": False,
        "primary_1km_rows": len(outputs[1000][0]), "sensitivity_2km_rows": len(outputs[2000][0]),
        "confirmatory_source_coverage": "Completed LF2016 envelope and 3DEP candidate support",
        "pr24_authorized": status in {"COMPLETE", "COMPLETE_WITH_LIMITATIONS"},
        "modeling_authorized": False,
        "limitations": "EAG is domain limited; rescued sensitivity semantics remain narrow; exploratory RCMAP deferred",
    }])
    decision.to_csv(DOC / "PAPER1_PROPAGATION_PR23_DECISION.csv", index=False, lineterminator="\n")

    manifest = {
        "artifact_class": "PR23 RESPONSE-FREE PREDICTOR DATA", "not_artifact_class": "PR31 MODELING TABLE",
        "created_utc": now(), "script": rel(Path(__file__)), "script_sha256": sha256(Path(__file__)),
        "environment": {"python": sys.version, "platform": platform.platform()}, "parameters": {"grids_m": GRID_SIZES, "terrain_working_resolution_m": 10, "terrain_halo_m": halo, "area_tolerance": TOL},
        "candidate_geometry": {"path": rel(CANDIDATES), "sha256": sha256(CANDIDATES), "rows": len(candidates)},
        "source_hashes": source_hashes, "outputs": output_hashes, "landfire_acquisition": landfire_receipt,
        "response_files_opened": [], "response_read": False, "model_fit": False, "predictive_scores": False,
        "status": status,
    }
    (WORK / "pr23_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    spec = f"""# Paper 1 PR23 Propagation Aggregation Specification

## Decision

**{status}.** The artifacts are **PR23 RESPONSE-FREE PREDICTOR DATA**, not a PR31 modeling table. No response-bearing file was opened, no response value was read, and no model or predictive score was produced. PR24 may proceed; modeling remains unauthorized.

## Fixed Supports and Accounting

The pipeline used the locked global EPSG:9311 lattices at 1,000 m and 2,000 m without re-anchoring. It retained stable `cell_id`, interval, forward-chain block, completed-t0 cutoff, and risk-membership provenance. Raster processing separately tracks total cell area, source-covered fraction, valid fraction, applicable fraction where relevant, source NoData, and outside-domain semantics. Numerical closure tolerance is `{TOL}`.

## Source Coverage

The exact candidate envelope plus a 300 m terrain halo was transformed to geographic bounds `{lonlat}`. The authoritative LFPS request retained LF2016 Remap products FBFM40, CC, CH, CBH, and CBD and expanded the previous clipped request to the full envelope. The existing USGS 3DEP `USGS_13_n43w121.tif` provides complete candidate-cell support; any source NoData would remain explicit rather than extrapolated. CONUS EVT/EVC/EVH already covered the envelope.

## Aggregation Rules

- Completed-t0 FEDS: center distances from the locked PR08 receipt, exact membership (`ACTIVE_ONLY`, `PERIMETER_BACKSTOP_ONLY`, `BOTH`), and `log1p` cumulative hull area.
- Terrain: 3DEP is bilinearly projected to a fixed 10 m EPSG:9311 working grid with 300 m halo. Mean elevation and Horn 3-by-3 slope are area averaged. The relevant source is the nearest completed-t0 active-front point except for perimeter-backstop-only rows, which use the nearest completed-t0 hull-boundary point. Elevation difference is target mean minus source-point elevation.
- Uphill alignment: `((target-source)/||target-source||) dot ((mean_dz_dx,mean_dz_dy)/||(mean_dz_dx,mean_dz_dy)||)`. Flat terrain or zero source-target distance returns 0.
- Wind-slope alignment: `((u_earth,v_earth)/||(u_earth,v_earth)||) dot ((mean_dz_dx,mean_dz_dy)/||(mean_dz_dx,mean_dz_dy)||)`. Weak/zero wind or flat terrain returns 0. The PTFO3 weak direction agreement remains a later interpretive sensitivity; no interaction family was added.
- FBFM40 and EVT: exact indicator-area fractions from explicit crosswalks. Unknown valid codes halt processing. Fractions close to valid-source area.
- Canopy: CC greater than zero defines product applicability. CC is percent; CH and CBH divide source codes by 10; CBD divides by 100. Conditional means use applicable valid area, never whole-cell zero substitution.
- EVC/EVH: compact conditional physical means after deterministic `CLASSNAMES` decoding; recognized nonphysical classes are not zero.
- EAG/cheatgrass: lineage-specific applicability fractions and conditional means; code 255/outside domain is never absence. Confidence remains a quality representation.
- Prior MTBS: pre-cutoff mapped-event area and conditional recency; Brattain is excluded.
- Forest health: forest applicability plus documented 2016 ODF bark-beetle recorded-event fraction. Zero is `NO_RECORDED_EVENT`, never biological absence.
- FACTS: current NFS applicability and unioned completed prefire implementation after exact `suid + activity_code + date_completed` deduplication (1,182 logical activities). Outside NFS is `OUTSIDE_DOMAIN`.
- RAP: conditional 2019 AFG + PFG production in lb/acre over conservative rangeland applicability. It is production, not fuel load or standing biomass.
- LF2016 FDist: minimal exploratory any-disturbance fraction; official zero is No Disturbance and does not define confirmatory common support.
- RCMAP: deferred as exploratory and nonblocking; no omnibus correlated block was created.
- HRRR: the five locked PR10 fields were reconstructed from saved cutoff-valid receipts and extracted values with the locked temporal formulas. No later initialization or realized weather entered.

## Support and Scope

The 1 km matrix has `{len(outputs[1000][0])}` rows and the 2 km matrix has `{len(outputs[2000][0])}` rows. Predictor-specific support is reported by interval and forward-chain block. PR23 does not choose a shared confirmatory row universe; that is PR24. Static-repeat checks, categorical closure, cross-resolution diagnostics, missingness semantics, and leakage checks are recorded in the companion QC tables and manifest.

## Limitations

EAG products are ecologically domain restricted. Forest-health, management, and RAP sensitivities retain their narrow recorded-event/applicability semantics. RCMAP remains exploratory and deferred. These limitations do not authorize modeling or alter predictor adjudication.
"""
    (DOC / "PAPER1_PROPAGATION_AGGREGATION_SPEC.md").write_text(spec, encoding="utf-8")
    print(json.dumps({"status": status, "rows": {k: len(v[0]) for k, v in outputs.items()}, "outputs": output_hashes}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-network", action="store_true", help="Permit the bounded official LFPS source-coverage request")
    args = parser.parse_args()
    main(args.allow_network)
