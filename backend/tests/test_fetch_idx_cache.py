from __future__ import annotations

import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.builder import fetch as fetch_module


def _install_fake_herbie(monkeypatch: pytest.MonkeyPatch, herbie_cls: type) -> None:
    fake_core = types.ModuleType("herbie.core")
    fake_core.Herbie = herbie_cls
    fake_pkg = types.ModuleType("herbie")
    fake_pkg.core = fake_core
    monkeypatch.setitem(sys.modules, "herbie", fake_pkg)
    monkeypatch.setitem(sys.modules, "herbie.core", fake_core)


def test_no_idx_negative_cache_skips_repeated_herbie_calls_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeHerbie:
        calls = 0

        def __init__(self, *args, **kwargs):
            del args, kwargs
            type(self).calls += 1
            self.idx = None

    _install_fake_herbie(monkeypatch, _FakeHerbie)
    fetch_module.reset_herbie_runtime_caches_for_tests()

    clock = {"now": 1000.0}
    monkeypatch.setattr(fetch_module.time, "monotonic", lambda: float(clock["now"]))
    monkeypatch.setenv("TWF_HERBIE_PRIORITY", "aws")
    monkeypatch.setenv("TWF_HERBIE_SUBSET_RETRIES", "2")
    monkeypatch.setenv("TWF_HERBIE_IDX_NEGATIVE_CACHE_INITIAL_TTL_SECONDS", "60")
    monkeypatch.setenv("TWF_HERBIE_IDX_NEGATIVE_CACHE_MAX_TTL_SECONDS", "300")

    kwargs = dict(
        model_id="hrrr",
        product="sfc",
        search_pattern=":TMP:2 m above ground:",
        run_date=datetime(2026, 3, 5, 17, 0),
        fh=13,
        herbie_kwargs={"priority": "aws"},
    )

    with pytest.raises(fetch_module.HerbieTransientUnavailableError):
        fetch_module.fetch_variable(**kwargs)
    assert _FakeHerbie.calls == 1

    with pytest.raises(fetch_module.HerbieTransientUnavailableError):
        fetch_module.fetch_variable(**kwargs)
    assert _FakeHerbie.calls == 1

    clock["now"] += 61.0
    with pytest.raises(fetch_module.HerbieTransientUnavailableError):
        fetch_module.fetch_variable(**kwargs)
    assert _FakeHerbie.calls == 2


def test_inventory_cache_dedupes_inflight_idx_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    index_df = pd.DataFrame(
        [
            {
                "search_this": ":TMP:850 mb:",
                "start_byte": 0,
                "end_byte": 100,
            }
        ]
    )

    class _FakeHerbie:
        init_calls = 0
        idx_df_calls = 0
        _lock = threading.Lock()

        def __init__(self, *args, **kwargs):
            del args, kwargs
            type(self).init_calls += 1
            self.idx = "https://nomads.example/hrrr.t17z.wrfprsf13.grib2.idx"

        @property
        def index_as_dataframe(self):
            with type(self)._lock:
                type(self).idx_df_calls += 1
            time.sleep(0.1)
            return index_df

    _install_fake_herbie(monkeypatch, _FakeHerbie)
    fetch_module.reset_herbie_runtime_caches_for_tests()
    monkeypatch.setenv("TWF_HERBIE_PRIORITY", "aws")
    monkeypatch.setenv("TWF_HERBIE_INVENTORY_CACHE_TTL_SECONDS", "600")

    def _fetch_lines() -> list[str]:
        return fetch_module.inventory_lines_for_pattern(
            model_id="hrrr",
            product="prs",
            run_date=datetime(2026, 3, 5, 17, 0),
            fh=13,
            search_pattern=":TMP:850 mb:",
            herbie_kwargs={"priority": "aws"},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        left_future = pool.submit(_fetch_lines)
        right_future = pool.submit(_fetch_lines)
        left = left_future.result()
        right = right_future.result()

    assert left == [":TMP:850 mb:"]
    assert right == [":TMP:850 mb:"]
    assert _FakeHerbie.init_calls == 2
    assert _FakeHerbie.idx_df_calls == 1
