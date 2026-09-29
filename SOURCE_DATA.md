# Source data

Raw third-party source datasets are not redistributed. Frozen derived analysis tables and exact provenance records are included.

| Product | Version | Role in Paper 1 | Official source or persistent identifier | Exact local provenance evidence | Redistributed | Reason if not redistributed |
|---|---|---|---|---|---|---|
| Fire Event Data Suite Data Western US Archive | Zenodo dataset 1.0.0; generated with FireAtlas/FEDS 1.2.1; event 65371 | Completed-state fire geometry, eligibility, and response | https://doi.org/10.5281/zenodo.15261836 | Source provenance audit; derived event states in `data/figure_support/` | Raw: No; derived states: Yes | Large public archive |
| USGS 3DEP 1/3-arc-second bare-earth DEM, tile n43w121 | Exact tile authenticated; edition/vintage/year unresolved | Terrain predictors | https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/n43w121/USGS_13_n43w121.tif | Exact URL, size, and SHA-256 in source audit | No | Large public raster |
| LANDFIRE Remap FBFM40 | LF 2016 Remap, LF 2016 2.0.0, circa-2016 conditions | Fuel composition fractions | https://lfps.usgs.gov/arcgis/rest/directories/arcgisjobs/landfireproductservice_gpserver/j8c359d80f6244327b9327ec378f3430f/scratch/j8c359d80f6244327b9327ec378f3430f.zip | Exact job, archive, raster band, and hashes | No | Large third-party raster archive |
| LANDFIRE Remap Canopy Cover, Height, Base Height, and Bulk Density | LF 2016 Remap, LF 2016 2.0.0 | Canopy applicability and structure | Same authenticated USGS LANDFIRE Product Service AOI archive as FBFM40 | Exact product codes, bands, scales, and hashes | No | Large third-party raster archive |
| LANDFIRE Remap 2016 Existing Vegetation Type | LF 2016 2.0.0, circa-2016 conditions | Five EVT composition fractions | Exact original acquisition URL unresolved | Exact archive/raster/product and hashes in source audit | No | Full-CONUS third-party raster |
| NOAA/NCEP HRRR CONUS surface forecasts | September 2020 operational-era product; HRRRv3 historically supported but not encoded in retained GRIB metadata | Five t0-valid weather predictors | https://noaa-hrrr-bdp-pds.s3.amazonaws.com | Exact 226 objects and 1,582 message ranges/hashes documented | No | Large public weather archive |

## Preserved provenance limitations

1. HRRR release number is not embedded in retained GRIB metadata.
2. The 3DEP tile edition/vintage/year is unresolved beyond the official `/current/` path.
3. The original LF2016 EVT download endpoint/interface was not retained.
4. Exact package builds/channels and earliest geospatial-preprocessing package versions were not frozen.
