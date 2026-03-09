from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

TELEMETRY_DB_PATH = Path(os.environ.get("TWM_TELEMETRY_DB_PATH", "./data/admin_telemetry.sqlite3"))

ALLOWED_PERF_EVENT_NAMES = {
    "viewer_first_frame",
    "frame_change",
    "loop_start",
    "scrub_latency",
    "variable_switch",
    "tile_fetch",
    "animation_stall",
}

ALLOWED_USAGE_EVENT_NAMES = {
    "model_selected",
    "variable_selected",
    "region_selected",
    "animation_play",
}

PERF_TARGETS_MS = {
    "viewer_first_frame": 1500.0,
    "frame_change": 250.0,
    "loop_start": 1000.0,
    "scrub_latency": 150.0,
    "variable_switch": 600.0,
    "tile_fetch": 800.0,
    "animation_stall": 750.0,
}

_db_init_lock = threading.Lock()
_db_initialized = False


def _ensure_parent_dir(path: Path) -> None:
    parent = path.parent
    if str(parent) and str(parent) != ".":
        parent.mkdir(parents=True, exist_ok=True)


def _connect() -> sqlite3.Connection:
    _ensure_parent_dir(TELEMETRY_DB_PATH)
    conn = sqlite3.connect(TELEMETRY_DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    global _db_initialized
    if _db_initialized:
        return
    with _db_init_lock:
        if _db_initialized:
            return
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS perf_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                member_id INTEGER,
                event_name TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                model_id TEXT,
                variable_id TEXT,
                run_id TEXT,
                region_id TEXT,
                forecast_hour INTEGER,
                device_type TEXT,
                viewport_bucket TEXT,
                page TEXT,
                meta_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_perf_events_event_created
                ON perf_events(event_name, created_at);
            CREATE INDEX IF NOT EXISTS idx_perf_events_created
                ON perf_events(created_at);
            CREATE INDEX IF NOT EXISTS idx_perf_events_model_var_created
                ON perf_events(model_id, variable_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_perf_events_device_created
                ON perf_events(device_type, created_at);

            CREATE TABLE IF NOT EXISTS usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                member_id INTEGER,
                event_name TEXT NOT NULL,
                model_id TEXT,
                variable_id TEXT,
                run_id TEXT,
                region_id TEXT,
                forecast_hour INTEGER,
                device_type TEXT,
                viewport_bucket TEXT,
                page TEXT,
                meta_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_usage_events_event_created
                ON usage_events(event_name, created_at);
            CREATE INDEX IF NOT EXISTS idx_usage_events_created
                ON usage_events(created_at);

            CREATE TABLE IF NOT EXISTS synthetic_perf_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER NOT NULL,
                commit_sha TEXT,
                branch TEXT,
                environment TEXT,
                scenario TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value_ms REAL NOT NULL,
                threshold_ms REAL,
                status TEXT NOT NULL,
                details_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_synthetic_perf_runs_metric_created
                ON synthetic_perf_runs(metric_name, created_at);
            """
        )
        _db_initialized = True


def _normalize_text(value: Any, *, max_length: int = 120) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_length]


def _normalize_forecast_hour(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _serialize_meta(value: Any) -> str | None:
    if value is None:
        return None
    try:
        encoded = json.dumps(value, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        return None
    return encoded[:4000]


def record_perf_event(payload: dict[str, Any], *, member_id: int | None = None) -> None:
    event_name = _normalize_text(payload.get("event_name") or payload.get("name"), max_length=64)
    if event_name not in ALLOWED_PERF_EVENT_NAMES:
        raise ValueError("Unsupported performance event")

    duration_ms = float(payload.get("duration_ms"))
    if duration_ms < 0 or duration_ms > 600000:
        raise ValueError("Invalid performance duration")

    created_at = int(time.time())
    session_id = _normalize_text(payload.get("session_id"), max_length=128) or "anonymous"

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO perf_events (
                created_at,
                session_id,
                member_id,
                event_name,
                duration_ms,
                model_id,
                variable_id,
                run_id,
                region_id,
                forecast_hour,
                device_type,
                viewport_bucket,
                page,
                meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                session_id,
                member_id,
                event_name,
                duration_ms,
                _normalize_text(payload.get("model_id"), max_length=32),
                _normalize_text(payload.get("variable_id"), max_length=64),
                _normalize_text(payload.get("run_id"), max_length=32),
                _normalize_text(payload.get("region_id"), max_length=32),
                _normalize_forecast_hour(payload.get("forecast_hour")),
                _normalize_text(payload.get("device_type"), max_length=24),
                _normalize_text(payload.get("viewport_bucket"), max_length=24),
                _normalize_text(payload.get("page"), max_length=120),
                _serialize_meta(payload.get("meta")),
            ),
        )


def record_usage_event(payload: dict[str, Any], *, member_id: int | None = None) -> None:
    event_name = _normalize_text(payload.get("event_name") or payload.get("name"), max_length=64)
    if event_name not in ALLOWED_USAGE_EVENT_NAMES:
        raise ValueError("Unsupported usage event")

    created_at = int(time.time())
    session_id = _normalize_text(payload.get("session_id"), max_length=128) or "anonymous"

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO usage_events (
                created_at,
                session_id,
                member_id,
                event_name,
                model_id,
                variable_id,
                run_id,
                region_id,
                forecast_hour,
                device_type,
                viewport_bucket,
                page,
                meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                session_id,
                member_id,
                event_name,
                _normalize_text(payload.get("model_id"), max_length=32),
                _normalize_text(payload.get("variable_id"), max_length=64),
                _normalize_text(payload.get("run_id"), max_length=32),
                _normalize_text(payload.get("region_id"), max_length=32),
                _normalize_forecast_hour(payload.get("forecast_hour")),
                _normalize_text(payload.get("device_type"), max_length=24),
                _normalize_text(payload.get("viewport_bucket"), max_length=24),
                _normalize_text(payload.get("page"), max_length=120),
                _serialize_meta(payload.get("meta")),
            ),
        )


def _compute_percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    position = max(0.0, min(1.0, percentile)) * (len(ordered) - 1)
    lower_index = int(position)
    upper_index = min(len(ordered) - 1, lower_index + 1)
    weight = position - lower_index
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * weight


def _build_perf_filters(
    *,
    since_ts: int,
    metric: str | None = None,
    device_type: str | None = None,
    model_id: str | None = None,
    variable_id: str | None = None,
) -> tuple[str, list[Any]]:
    clauses = ["created_at >= ?"]
    params: list[Any] = [since_ts]
    if metric:
        clauses.append("event_name = ?")
        params.append(metric)
    if device_type:
        clauses.append("device_type = ?")
        params.append(device_type)
    if model_id:
        clauses.append("model_id = ?")
        params.append(model_id)
    if variable_id:
        clauses.append("variable_id = ?")
        params.append(variable_id)
    return " WHERE " + " AND ".join(clauses), params


def _metric_summary(values: Iterable[float], *, target_ms: float | None = None) -> dict[str, Any]:
    samples = [float(value) for value in values]
    if not samples:
        return {
            "count": 0,
            "avg_ms": None,
            "min_ms": None,
            "max_ms": None,
            "p50_ms": None,
            "p95_ms": None,
            "target_ms": target_ms,
        }
    avg_ms = sum(samples) / len(samples)
    return {
        "count": len(samples),
        "avg_ms": round(avg_ms, 1),
        "min_ms": round(min(samples), 1),
        "max_ms": round(max(samples), 1),
        "p50_ms": round(_compute_percentile(samples, 0.50) or 0.0, 1),
        "p95_ms": round(_compute_percentile(samples, 0.95) or 0.0, 1),
        "target_ms": target_ms,
    }


def get_perf_summary(
    *,
    since_ts: int,
    device_type: str | None = None,
    model_id: str | None = None,
    variable_id: str | None = None,
) -> dict[str, Any]:
    where_sql, params = _build_perf_filters(
        since_ts=since_ts,
        device_type=device_type,
        model_id=model_id,
        variable_id=variable_id,
    )
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT event_name, duration_ms
            FROM perf_events
            {where_sql}
            ORDER BY created_at ASC
            """,
            params,
        ).fetchall()

    values_by_metric: dict[str, list[float]] = {name: [] for name in ALLOWED_PERF_EVENT_NAMES}
    for row in rows:
        values_by_metric[str(row["event_name"])].append(float(row["duration_ms"]))

    return {
        "metrics": {
            metric_name: _metric_summary(values, target_ms=PERF_TARGETS_MS.get(metric_name))
            for metric_name, values in sorted(values_by_metric.items())
        }
    }


def get_perf_timeseries(
    *,
    since_ts: int,
    metric: str,
    bucket: str,
    device_type: str | None = None,
    model_id: str | None = None,
    variable_id: str | None = None,
) -> list[dict[str, Any]]:
    if metric not in ALLOWED_PERF_EVENT_NAMES:
        raise ValueError("Unsupported performance metric")
    if bucket not in {"hour", "day"}:
        raise ValueError("Unsupported timeseries bucket")

    bucket_expr = "%Y-%m-%dT%H:00:00Z" if bucket == "hour" else "%Y-%m-%dT00:00:00Z"
    where_sql, params = _build_perf_filters(
        since_ts=since_ts,
        metric=metric,
        device_type=device_type,
        model_id=model_id,
        variable_id=variable_id,
    )
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT strftime('{bucket_expr}', created_at, 'unixepoch') AS bucket_start,
                   duration_ms
            FROM perf_events
            {where_sql}
            ORDER BY created_at ASC
            """,
            params,
        ).fetchall()

    buckets: dict[str, list[float]] = {}
    for row in rows:
        key = str(row["bucket_start"])
        buckets.setdefault(key, []).append(float(row["duration_ms"]))

    return [
        {
            "bucket_start": bucket_start,
            **_metric_summary(values, target_ms=PERF_TARGETS_MS.get(metric)),
        }
        for bucket_start, values in sorted(buckets.items())
    ]


def get_perf_breakdown(
    *,
    since_ts: int,
    metric: str,
    breakdown_by: str,
    limit: int = 8,
    device_type: str | None = None,
    model_id: str | None = None,
    variable_id: str | None = None,
) -> list[dict[str, Any]]:
    if metric not in ALLOWED_PERF_EVENT_NAMES:
        raise ValueError("Unsupported performance metric")
    column_by_breakdown = {
        "model": "model_id",
        "variable": "variable_id",
        "device": "device_type",
    }
    column = column_by_breakdown.get(breakdown_by)
    if column is None:
        raise ValueError("Unsupported breakdown")

    where_sql, params = _build_perf_filters(
        since_ts=since_ts,
        metric=metric,
        device_type=device_type,
        model_id=model_id,
        variable_id=variable_id,
    )
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT COALESCE({column}, 'unknown') AS bucket_key,
                   duration_ms
            FROM perf_events
            {where_sql}
            ORDER BY created_at ASC
            """,
            params,
        ).fetchall()

    values_by_bucket: dict[str, list[float]] = {}
    for row in rows:
        key = str(row["bucket_key"] or "unknown")
        values_by_bucket.setdefault(key, []).append(float(row["duration_ms"]))

    ranked = sorted(
        values_by_bucket.items(),
        key=lambda item: (len(item[1]), item[0]),
        reverse=True,
    )[: max(1, limit)]

    return [
        {
            "key": key,
            **_metric_summary(values, target_ms=PERF_TARGETS_MS.get(metric)),
        }
        for key, values in ranked
    ]


def get_usage_summary(*, since_ts: int) -> dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT event_name, COUNT(*) AS total
            FROM usage_events
            WHERE created_at >= ?
            GROUP BY event_name
            ORDER BY total DESC, event_name ASC
            """,
            (since_ts,),
        ).fetchall()
    return {
        "events": [
            {
                "event_name": str(row["event_name"]),
                "count": int(row["total"]),
            }
            for row in rows
        ]
    }
