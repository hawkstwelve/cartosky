from __future__ import annotations

import numpy as np

from app.services.builder import colorize


def _continuous_spec_with_stops() -> dict:
    return {
        "type": "continuous",
        "range": [0.0, 4.0],
        "anchors": [
            (0.0, "#000000"),
            (1.0, "#404040"),
            (2.0, "#808080"),
            (3.0, "#b0b0b0"),
            (4.0, "#ffffff"),
        ],
        "units": "x",
    }


def test_continuous_dither_disabled_env_is_noop_for_colorize(monkeypatch) -> None:
    data = np.array(
        [
            [0.0, 1.0, 2.0, 3.0],
            [0.5, 1.5, 2.5, 3.5],
        ],
        dtype=np.float32,
    )
    spec = _continuous_spec_with_stops()

    monkeypatch.setenv("TWF_V3_CONTINUOUS_DITHER_STRENGTH", "0")
    rgba_zero, _ = colorize._colorize_continuous(data, "tmp2m", spec)

    monkeypatch.setenv("TWF_V3_CONTINUOUS_DITHER_STRENGTH", "-1")
    rgba_negative, _ = colorize._colorize_continuous(data, "tmp2m", spec)

    assert np.array_equal(rgba_zero, rgba_negative)


def test_continuous_dither_preserves_nan_locations() -> None:
    data = np.array(
        [
            [0.0, np.nan, 2.0],
            [1.0, 3.0, np.nan],
        ],
        dtype=np.float32,
    )
    spec = _continuous_spec_with_stops()

    out = colorize._apply_continuous_ordered_dither(data, spec, strength=0.2)
    assert np.array_equal(np.isnan(out), np.isnan(data))


def test_continuous_dither_bound_is_within_half_bin_strength() -> None:
    data = np.array(
        [
            [0.25, 0.75, 1.25, 1.75],
            [2.25, 2.75, 3.25, 3.75],
        ],
        dtype=np.float32,
    )
    spec = _continuous_spec_with_stops()
    strength = 0.2
    step = colorize._representative_continuous_step(spec)
    assert step is not None

    out = colorize._apply_continuous_ordered_dither(data, spec, strength=strength)
    delta = out - data
    bound = 0.5 * strength * step

    assert np.all(np.abs(delta) <= (bound + 1e-6))


def test_continuous_dither_is_deterministic() -> None:
    data = np.array(
        [
            [0.2, 0.4, 0.6, 0.8],
            [1.0, 1.2, 1.4, 1.6],
            [1.8, 2.0, 2.2, 2.4],
            [2.6, 2.8, 3.0, 3.2],
        ],
        dtype=np.float32,
    )
    spec = _continuous_spec_with_stops()

    first = colorize._apply_continuous_ordered_dither(data, spec, strength=0.2)
    second = colorize._apply_continuous_ordered_dither(data, spec, strength=0.2)
    assert np.array_equal(first, second)
