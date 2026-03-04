"""Shared render-time resampling policy by variable kind.

This module keeps tile extraction and loop WebP downscaling behavior aligned.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from rasterio.enums import Resampling

from ..models.registry import list_model_capabilities

logger = logging.getLogger(__name__)

_DISCRETE_KINDS = {"discrete", "indexed", "categorical"}
_VALUE_RENDER_MIN_MODEL_KM = 10.0
# First-pass rollout guard. Keep generic km/kind checks, but only allow GFS now.
_VALUE_RENDER_MODEL_ALLOWLIST = {"gfs"}
_MODEL_GRID_KM_FALLBACK: dict[str, float] = {
    "gfs": 25.0,
}
_warned_unknown_kind: set[tuple[str, str]] = set()
_unknown_kind_hits: dict[tuple[str, str], int] = {}


def _normalize_kind(kind: Any) -> str:
    return str(kind or "").strip().lower()


@lru_cache(maxsize=64)
def _lookup_kind_from_capabilities(model_id: str, var_key: str) -> str | None:
    entry = _lookup_variable_catalog_entry(model_id, var_key)
    if entry is None:
        return None

    kind = _normalize_kind(getattr(entry, "kind", None))
    return kind or None


@lru_cache(maxsize=64)
def _lookup_variable_catalog_entry(model_id: str, var_key: str) -> Any | None:
    capabilities = list_model_capabilities().get(model_id)
    if capabilities is None:
        return None

    catalog = getattr(capabilities, "variable_catalog", None)
    if not isinstance(catalog, Mapping):
        return None
    return catalog.get(var_key)


@lru_cache(maxsize=32)
def _lookup_model_grid_km(model_id: str) -> float | None:
    capabilities = list_model_capabilities().get(model_id)
    if capabilities is not None:
        grid_map = getattr(capabilities, "grid_meters_by_region", None)
        if isinstance(grid_map, Mapping) and grid_map:
            canonical_region = str(getattr(capabilities, "canonical_region", "") or "")
            if canonical_region and canonical_region in grid_map:
                try:
                    return float(grid_map[canonical_region]) / 1000.0
                except (TypeError, ValueError):
                    pass

            values_km: list[float] = []
            for value in grid_map.values():
                try:
                    parsed = float(value)
                except (TypeError, ValueError):
                    continue
                if parsed > 0:
                    values_km.append(parsed / 1000.0)
            if values_km:
                return min(values_km)

    fallback = _MODEL_GRID_KM_FALLBACK.get(model_id)
    if fallback is None:
        return None
    try:
        return float(fallback)
    except (TypeError, ValueError):
        return None


def variable_kind(model_id: str, var_key: str) -> str | None:
    model_norm = str(model_id or "").strip().lower()
    var_norm = str(var_key or "").strip().lower()
    if not model_norm or not var_norm:
        return None
    return _lookup_kind_from_capabilities(model_norm, var_norm)


def resampling_name_for_kind(
    *,
    model_id: str,
    var_key: str,
    kind: str | None = None,
) -> str:
    """Resolve render-time resampling name with bilinear fallback.

    Continuous/unknown -> bilinear
    Discrete/indexed/categorical -> nearest
    """
    model_norm = str(model_id or "").strip().lower()
    var_norm = str(var_key or "").strip().lower()
    resolved_kind = _normalize_kind(kind) or _normalize_kind(variable_kind(model_norm, var_norm))

    if resolved_kind in _DISCRETE_KINDS:
        return "nearest"
    if resolved_kind == "continuous":
        return "bilinear"

    key = (model_norm or "<unknown-model>", var_norm or "<unknown-var>")
    _unknown_kind_hits[key] = _unknown_kind_hits.get(key, 0) + 1
    if key not in _warned_unknown_kind:
        _warned_unknown_kind.add(key)
        logger.warning(
            "Unknown or missing variable kind for model=%s var=%s (kind=%r); "
            "defaulting resampling to bilinear (hits=%d)",
            model_norm,
            var_norm,
            resolved_kind or None,
            _unknown_kind_hits[key],
        )
    return "bilinear"


def variable_color_map_id(model_id: str, var_key: str) -> str | None:
    model_norm = str(model_id or "").strip().lower()
    var_norm = str(var_key or "").strip().lower()
    if not model_norm or not var_norm:
        return None

    entry = _lookup_variable_catalog_entry(model_norm, var_norm)
    if entry is None:
        return None
    color_map_id = getattr(entry, "color_map_id", None)
    if not isinstance(color_map_id, str):
        return None
    resolved = color_map_id.strip()
    return resolved or None


def model_grid_km(model_id: str) -> float | None:
    model_norm = str(model_id or "").strip().lower()
    if not model_norm:
        return None
    return _lookup_model_grid_km(model_norm)


def use_value_render_for_variable(
    *,
    model_id: str,
    var_key: str,
    kind: str | None = None,
) -> bool:
    model_norm = str(model_id or "").strip().lower()
    var_norm = str(var_key or "").strip().lower()
    if not model_norm or not var_norm:
        return False

    resolved_kind = _normalize_kind(kind) or _normalize_kind(variable_kind(model_norm, var_norm))
    if resolved_kind != "continuous":
        return False

    model_km = model_grid_km(model_norm)
    if model_km is None or model_km < _VALUE_RENDER_MIN_MODEL_KM:
        return False

    if model_norm not in _VALUE_RENDER_MODEL_ALLOWLIST:
        return False
    return True


def rio_tiler_resampling_kwargs(
    *,
    model_id: str,
    var_key: str,
    kind: str | None = None,
) -> dict[str, str]:
    name = resampling_name_for_kind(model_id=model_id, var_key=var_key, kind=kind)
    return {
        "resampling_method": name,
        "reproject_method": name,
    }


def rasterio_resampling_for_loop(
    *,
    model_id: str,
    var_key: str,
    kind: str | None = None,
) -> Resampling:
    name = resampling_name_for_kind(model_id=model_id, var_key=var_key, kind=kind)
    return Resampling.nearest if name == "nearest" else Resampling.bilinear
