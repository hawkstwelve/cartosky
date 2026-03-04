"""Build-time colorization: float32 data → 4-band RGBA uint8 array.

This replaces the V2 two-step process:
  1. encode_to_byte_and_alpha() → 2-band COG (byte index + alpha)
  2. get_lut() at serve time → maps byte index to RGBA

V3 merges both into a single build-time function: float_to_rgba().
The tile server never touches colormaps — it reads RGBA and returns PNG.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np

from ..colormaps import (
    build_continuous_lut,
    build_continuous_lut_from_stops,
    build_discrete_lut,
    get_color_map_spec,
)

_BAYER4 = np.array(
    [
        [0, 8, 2, 10],
        [12, 4, 14, 6],
        [3, 11, 1, 9],
        [15, 7, 13, 5],
    ],
    dtype=np.float32,
)


def float_to_rgba(
    data: np.ndarray,
    color_map_id: str,
    *,
    meta_var_key: str | None = None,
    spec_override: dict[str, Any] | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Convert a 2-D float32 array to a 4-band RGBA uint8 array.

    Parameters
    ----------
    data : np.ndarray
        2-D array (H, W) of float values.  NaN = nodata.
    color_map_id : str
        Palette identifier used to resolve color/range/level definitions.
        Transitional path still supports legacy var-keyed palette IDs.
    meta_var_key : str, optional
        Variable key to emit in sidecar metadata. Defaults to color_map_id.
    spec_override : dict, optional
        If provided, used instead of the resolved palette spec. Useful for
        testing or for variables whose spec hasn't been registered yet.

    Returns
    -------
    rgba : np.ndarray
        Shape (4, H, W), dtype uint8.  Band order: R, G, B, A.
        Alpha = 0 for nodata/transparent pixels, 255 for valid.
    meta : dict
        Sidecar metadata for the frame JSON (legend info, units, etc.).
    """
    if data.ndim != 2:
        raise ValueError(f"data must be 2-D, got shape {data.shape}")

    var_key = meta_var_key or color_map_id
    spec = spec_override if spec_override is not None else get_color_map_spec(color_map_id)
    if spec is None:
        raise KeyError(f"Unknown color_map_id: {color_map_id!r}")

    kind = spec.get("type")
    if kind == "continuous":
        rgba, meta = _colorize_continuous(data, var_key, spec)
    elif kind == "discrete":
        rgba, meta = _colorize_discrete(data, var_key, spec)
    elif kind == "indexed":
        rgba, meta = _colorize_indexed(data, var_key, spec)
    else:
        raise ValueError(f"Unsupported spec type for {var_key!r}: {kind!r}")

    return rgba, meta


# ---------------------------------------------------------------------------
# Continuous: float → scale 0–255 → LUT → RGBA
# ---------------------------------------------------------------------------


def _continuous_dither_strength() -> float:
    raw = os.getenv("TWF_V3_CONTINUOUS_DITHER_STRENGTH", "0.20").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.20


def _representative_continuous_step(spec: dict[str, Any]) -> float | None:
    levels_raw = spec.get("levels")
    if isinstance(levels_raw, (list, tuple)) and len(levels_raw) >= 2:
        levels = np.asarray(levels_raw, dtype=np.float32)
        diffs = np.diff(levels)
        valid = diffs[np.isfinite(diffs) & (diffs > 0)]
        if valid.size > 0:
            return float(np.median(valid))

    stops_raw = (
        spec.get("stops")
        or spec.get("color_anchors")
        or spec.get("anchors")
        or spec.get("legend_stops")
    )
    if not isinstance(stops_raw, (list, tuple)) or len(stops_raw) < 2:
        return None

    stop_values: list[float] = []
    for item in stops_raw:
        if not isinstance(item, (list, tuple)) or not item:
            continue
        try:
            stop_values.append(float(item[0]))
        except (TypeError, ValueError):
            continue

    if len(stop_values) < 2:
        return None

    vals = np.sort(np.asarray(stop_values, dtype=np.float32))
    diffs = np.diff(vals)
    valid = diffs[np.isfinite(diffs) & (diffs > 0)]
    if valid.size == 0:
        return None
    return float(np.median(valid))


def _ordered_bayer_noise(height: int, width: int) -> np.ndarray:
    yy = np.arange(height, dtype=np.int32)[:, None] & 3
    xx = np.arange(width, dtype=np.int32)[None, :] & 3
    bayer = _BAYER4[yy, xx]
    return (bayer / 16.0) - 0.5


def _apply_continuous_ordered_dither(
    data: np.ndarray,
    spec: dict[str, Any],
    *,
    strength: float | None = None,
) -> np.ndarray:
    data_f32 = np.asarray(data, dtype=np.float32)
    resolved_strength = _continuous_dither_strength() if strength is None else float(strength)
    if resolved_strength <= 0:
        return data_f32

    step = _representative_continuous_step(spec)
    if step is None or not np.isfinite(step) or step <= 0:
        return data_f32

    finite_mask = np.isfinite(data_f32)
    if not finite_mask.any():
        return data_f32

    noise = _ordered_bayer_noise(data_f32.shape[0], data_f32.shape[1]).astype(np.float32, copy=False)
    amplitude = np.float32(resolved_strength * step)
    dithered = np.where(
        finite_mask,
        data_f32 + (noise * amplitude),
        data_f32,
    ).astype(np.float32, copy=False)
    return dithered


def _colorize_continuous(
    data: np.ndarray,
    var_key: str,
    spec: dict[str, Any],
) -> tuple[np.ndarray, dict[str, Any]]:
    range_vals = spec.get("range")
    if not range_vals or len(range_vals) != 2:
        raise ValueError(f"Continuous spec for {var_key!r} must include range (min, max)")
    range_min, range_max = float(range_vals[0]), float(range_vals[1])
    if range_max == range_min:
        raise ValueError(f"Continuous spec for {var_key!r} has zero-width range")

    anchors = spec.get("color_anchors") or spec.get("anchors")
    if anchors:
        # Build 256-entry LUT directly from value→color anchors.
        lut = build_continuous_lut_from_stops(
            [(float(value), str(color)) for value, color in anchors],
            n=256,
            range_vals=(range_min, range_max),
        )
    else:
        colors: list[str] | None = spec.get("colors")
        if not colors:
            raise ValueError(
                f"Continuous spec for {var_key!r} must include either "
                f"'color_anchors'/'anchors' or 'colors'"
            )
        # Build 256-entry RGBA LUT from evenly spaced color ramp stops.
        lut = build_continuous_lut(colors, n=256)  # (256, 4) uint8

    quantize_data = _apply_continuous_ordered_dither(data, spec)

    # Scale float values → 0–255 index
    finite_mask = np.isfinite(quantize_data)
    scale = np.where(finite_mask, (quantize_data - range_min) / (range_max - range_min), 0.0)
    indices = np.clip(np.rint(scale * 255.0), 0, 255).astype(np.uint8)

    # LUT lookup: (H, W) indices → (H, W, 4) RGBA
    rgba_hwc = lut[indices]  # advanced indexing

    # Zero out alpha for nodata pixels
    rgba_hwc[~finite_mask, 3] = 0

    transparent_below_min = spec.get("transparent_below_min")
    if transparent_below_min is not None:
        try:
            min_visible = float(transparent_below_min)
            rgba_hwc[finite_mask & (data < min_visible), 3] = 0
        except (TypeError, ValueError):
            pass

    # Transpose to band-first (4, H, W) for rasterio
    rgba = np.transpose(rgba_hwc, (2, 0, 1)).copy()

    meta = _build_meta(var_key, spec, data, finite_mask)
    return rgba, meta


# ---------------------------------------------------------------------------
# Discrete: float → bin via np.digitize → LUT → RGBA
# ---------------------------------------------------------------------------


def _colorize_discrete(
    data: np.ndarray,
    var_key: str,
    spec: dict[str, Any],
) -> tuple[np.ndarray, dict[str, Any]]:
    levels: list[float] | None = spec.get("levels")
    colors: list[str] | None = spec.get("colors")
    if not levels or not colors:
        raise ValueError(f"Discrete spec for {var_key!r} must include levels and colors")
    if len(levels) < 2:
        raise ValueError(
            f"Discrete spec for {var_key!r} must have at least 2 levels, got {len(levels)}"
        )

    # Build LUT: one RGBA entry per color
    lut = build_discrete_lut(colors)  # (256, 4) uint8

    finite_mask = np.isfinite(data)

    # Digitize: assign each value to a bin index.
    # np.digitize with right=False: bin i covers [levels[i], levels[i+1]).
    # Subtract 1 so first bin maps to color index 0.
    safe_vals = np.where(finite_mask, data, levels[0])
    bins = np.digitize(safe_vals, levels, right=False) - 1
    bins = np.clip(bins, 0, len(colors) - 1).astype(np.uint8)

    # LUT lookup
    rgba_hwc = lut[bins]  # (H, W, 4)

    # Alpha: transparent for nodata; optionally transparent below first level.
    # spec["transparent_below_min"] (default True) controls whether values
    # below levels[0] are made transparent or mapped to the first color.
    transparent_below_min = spec.get("transparent_below_min", True)
    if transparent_below_min:
        valid_mask = finite_mask & (data >= levels[0])
    else:
        valid_mask = finite_mask
    rgba_hwc[~valid_mask, 3] = 0

    # Band-first
    rgba = np.transpose(rgba_hwc, (2, 0, 1)).copy()

    meta = _build_meta(var_key, spec, data, finite_mask)
    return rgba, meta


# ---------------------------------------------------------------------------
# Indexed: pre-computed palette index → LUT → RGBA
# Used for composite products (radar_ptype, precip_ptype) where the derive
# step produces an integer palette index, NOT a physical value to be binned.
# ---------------------------------------------------------------------------


def _colorize_indexed(
    data: np.ndarray,
    var_key: str,
    spec: dict[str, Any],
) -> tuple[np.ndarray, dict[str, Any]]:
    colors: list[str] | None = spec.get("colors")
    if not colors:
        raise ValueError(f"Indexed spec for {var_key!r} must include colors")

    # Build LUT: one RGBA entry per color (up to 256)
    lut = build_discrete_lut(colors)  # (256, 4) uint8

    finite_mask = np.isfinite(data)

    # Direct index lookup: clip(round(data), 0, len(colors)-1)
    max_idx = len(colors) - 1
    indices_i32 = np.zeros(data.shape, dtype=np.int32)
    if finite_mask.any():
        rounded = np.rint(data[finite_mask]).astype(np.int32)
        indices_i32[finite_mask] = np.clip(rounded, 0, max_idx)
    indices = indices_i32.astype(np.uint8)

    # LUT lookup
    rgba_hwc = lut[indices]  # (H, W, 4)

    # Alpha: NaN → 0.  Optionally index 0 → transparent (common for
    # "no precipitation" or "no echo" sentinel values).
    transparent_zero = spec.get("transparent_zero", False)
    if transparent_zero:
        valid_mask = finite_mask & (indices > 0)
    else:
        valid_mask = finite_mask
    rgba_hwc[~valid_mask, 3] = 0

    # Band-first
    rgba = np.transpose(rgba_hwc, (2, 0, 1)).copy()

    meta = _build_meta(var_key, spec, data, finite_mask)
    return rgba, meta


# ---------------------------------------------------------------------------
# Sidecar metadata builder
# ---------------------------------------------------------------------------

_META_PASSTHROUGH_KEYS = (
    "display_name",
    "legend_title",
    "legend_stops",
    "ptype_order",
    "ptype_breaks",
    "ptype_levels",
    "bins_per_ptype",
)


def _build_meta(
    var_key: str,
    spec: dict[str, Any],
    data: np.ndarray,
    finite_mask: np.ndarray,
) -> dict[str, Any]:
    """Build sidecar JSON metadata for the frame."""
    kind = spec["type"]  # "continuous" | "discrete" | "indexed"

    meta: dict[str, Any] = {
        "var_key": var_key,
        "kind": kind,
        "units": spec.get("units"),
    }

    if kind == "continuous":
        range_vals = spec["range"]
        meta["range"] = [float(range_vals[0]), float(range_vals[1])]
        meta["colors"] = list(spec.get("colors", []))
        anchors = spec.get("color_anchors") or spec.get("anchors")
        if anchors:
            meta["legend_stops"] = [[float(value), color] for value, color in anchors]
    elif kind in ("discrete", "indexed"):
        if "levels" in spec:
            meta["levels"] = list(spec["levels"])
        meta["colors"] = list(spec.get("colors", []))

    # Data statistics (for sidecar JSON / validation)
    if finite_mask.any():
        valid = data[finite_mask]
        meta["min"] = float(np.nanmin(valid))
        meta["max"] = float(np.nanmax(valid))
    else:
        meta["min"] = None
        meta["max"] = None

    # Forward optional display/legend fields unchanged
    for key in _META_PASSTHROUGH_KEYS:
        if key in spec:
            val = spec[key]
            if isinstance(val, (list, tuple)):
                meta[key] = [list(item) if isinstance(item, (list, tuple)) else item for item in val]
            elif isinstance(val, dict):
                meta[key] = {
                    str(k): list(v) if isinstance(v, (list, tuple)) else v
                    for k, v in val.items()
                }
            else:
                meta[key] = val

    # Include range for discrete/indexed vars that have one (e.g. precip_ptype)
    if kind in ("discrete", "indexed") and "range" in spec:
        range_vals = spec["range"]
        if isinstance(range_vals, (list, tuple)) and len(range_vals) == 2:
            meta["range"] = [float(range_vals[0]), float(range_vals[1])]

    return meta
