from __future__ import annotations

from typing import Sequence

KUCHERA_DEFAULT_LEVELS_HPA: tuple[int, ...] = (925, 850, 700, 600, 500)
KUCHERA_DEFAULT_REQUIRE_RH = True
KUCHERA_DEFAULT_MIN_LEVELS = 4


def kuchera_hint_overrides(
    *,
    levels_hpa: Sequence[int] | None = None,
    require_rh: bool = KUCHERA_DEFAULT_REQUIRE_RH,
    min_levels: int = KUCHERA_DEFAULT_MIN_LEVELS,
) -> dict[str, str]:
    resolved_levels = tuple(int(level) for level in (levels_hpa or KUCHERA_DEFAULT_LEVELS_HPA))
    safe_levels = [level for level in resolved_levels if level > 0]
    if not safe_levels:
        safe_levels = list(KUCHERA_DEFAULT_LEVELS_HPA)
    safe_min_levels = max(1, int(min_levels))
    return {
        "kuchera_levels_hpa": ",".join(str(level) for level in safe_levels),
        "kuchera_require_rh": "true" if require_rh else "false",
        "kuchera_min_levels": str(safe_min_levels),
    }
