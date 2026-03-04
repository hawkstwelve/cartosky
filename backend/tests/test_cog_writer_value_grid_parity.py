from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import rasterio

from app.services.builder import cog_writer


def test_value_cog_matches_rgba_grid_for_gfs_conus(monkeypatch, tmp_path: Path) -> None:
    """Value COG base grid must match RGBA COG grid for the same model/region."""
    bbox, grid_m = cog_writer.get_grid_params("gfs", "conus")
    _, height, width = cog_writer.compute_transform_and_shape(bbox, grid_m)

    yy, xx = np.indices((height, width), dtype=np.float32)
    values = ((xx * 0.1) + (yy * 0.2)).astype(np.float32)
    values[0, 0] = np.nan

    rgba = np.zeros((4, height, width), dtype=np.uint8)
    rgba[0] = np.clip(xx, 0, 255).astype(np.uint8)
    rgba[1] = np.clip(yy, 0, 255).astype(np.uint8)
    rgba[2] = 128
    rgba[3] = 255
    rgba[:, 0, 0] = 0

    def fake_run_gdal(cmd: list[str]) -> None:
        del cmd

    def fake_translate(src: Path, dst: Path) -> None:
        shutil.copyfile(src, dst)

    monkeypatch.setattr(cog_writer, "_run_gdal", fake_run_gdal)
    monkeypatch.setattr(cog_writer, "_gtiff_to_cog", fake_translate)
    monkeypatch.setattr(cog_writer, "_gdal", lambda name: name)

    rgba_path = tmp_path / "fh001.rgba.cog.tif"
    val_path = tmp_path / "fh001.val.cog.tif"

    cog_writer.write_rgba_cog(rgba, rgba_path, model="gfs", region="conus", kind="continuous")
    cog_writer.write_value_cog(
        values,
        val_path,
        model="gfs",
        region="conus",
        downsample_factor=4,
    )

    with rasterio.open(rgba_path) as rgba_ds, rasterio.open(val_path) as val_ds:
        assert val_ds.width == rgba_ds.width
        assert val_ds.height == rgba_ds.height

        rgba_px_x = abs(float(rgba_ds.transform.a))
        rgba_px_y = abs(float(rgba_ds.transform.e))
        val_px_x = abs(float(val_ds.transform.a))
        val_px_y = abs(float(val_ds.transform.e))
        assert abs(val_px_x - rgba_px_x) < 1e-6
        assert abs(val_px_y - rgba_px_y) < 1e-6

        assert val_ds.dtypes[0] == "float32"
        assert val_ds.nodata is not None
        assert np.isnan(float(val_ds.nodata))
