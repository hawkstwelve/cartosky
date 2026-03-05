from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.builder import pipeline as pipeline_module


class _Plugin:
    id = "hrrr"

    def normalize_var_id(self, var_key: str) -> str:
        return str(var_key)


def test_build_frame_readiness_gate_short_circuits_derived_fetch(monkeypatch, tmp_path: Path) -> None:
    plugin = _Plugin()
    var_spec_model = SimpleNamespace(
        derived=True,
        derive="snowfall_kuchera_total_cumulative",
        selectors=SimpleNamespace(
            hints={
                "kuchera_apcp_product": "sfc",
                "kuchera_profile_product": "prs",
            }
        ),
    )
    var_capability = SimpleNamespace(
        color_map_id="snow_continuous",
        kind="continuous",
        derive_strategy_id="snowfall_kuchera_total_cumulative",
    )

    readiness_calls: list[str] = []
    derive_called = {"value": False}

    monkeypatch.setattr(pipeline_module, "_resolve_model_var_spec", lambda *args, **kwargs: var_spec_model)
    monkeypatch.setattr(pipeline_module, "_resolve_model_var_capability", lambda *args, **kwargs: var_capability)
    monkeypatch.setattr(
        pipeline_module,
        "get_color_map_spec",
        lambda color_map_id: {"id": color_map_id, "type": "continuous", "units": "in", "range": [0.0, 10.0], "colors": ["#000", "#fff"]},
    )

    def _fake_product_ready(*, model_id, product, run_date, fh, herbie_kwargs=None):
        del model_id, run_date, fh, herbie_kwargs
        readiness_calls.append(str(product))
        return str(product) != "sfc"

    monkeypatch.setattr(pipeline_module, "product_hour_has_any_idx", _fake_product_ready)

    def _fake_derive_variable(**kwargs):
        del kwargs
        derive_called["value"] = True
        raise AssertionError("derive_variable should not run when readiness gate fails")

    monkeypatch.setattr(pipeline_module, "derive_variable", _fake_derive_variable)

    result = pipeline_module.build_frame(
        model="hrrr",
        region="conus",
        var_id="snowfall_kuchera_total",
        fh=13,
        run_date=datetime(2026, 3, 5, 17, 0),
        data_root=tmp_path,
        product="sfc",
        model_plugin=plugin,
    )

    assert result is None
    assert derive_called["value"] is False
    assert readiness_calls == ["sfc", "prs"]
