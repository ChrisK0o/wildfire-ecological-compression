# Software environment

The accepted final model execution used Windows 11, CPython 3.12.13, and a Conda environment named `wildfire`. The complete observed package/version inventory is in `documentation/ENVIRONMENT_PACKAGES.csv`.

Core model stack: NumPy 2.5.1, SciPy 1.18.0, pandas 3.0.3, scikit-learn 1.9.0, and PyArrow 23.0.1.

The final environment observed Rasterio 1.5.0, GDAL 3.12.4, GeoPandas 1.1.4, Shapely 2.1.2, and PyProj 3.7.2. The project did not retain a complete channel/build lock, and exact geospatial package versions at the earliest predictor-generation step were not frozen. These versions describe the final environment, not authenticated versions for every historical preprocessing step. The original environment file was excluded because it contains a user-specific prefix and is not a complete lock.
