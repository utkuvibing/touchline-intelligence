"""Fetching and caching StatsBomb Open Data files.

Files are downloaded once into a local cache and read from there afterwards, so a re-run costs
nothing and the exact bytes that produced a load can be inspected. The cache is git-ignored.

Only the selected competition-season is fetched, never the whole repository.

Data provided by StatsBomb: https://github.com/statsbomb/open-data
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

BASE_URL = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
DEFAULT_CACHE = Path("data/statsbomb")

# FIFA World Cup 2022. Fixed for WP0.3; the wider cohort defined in ADR 0004 arrives in M1.
WORLD_CUP_2022 = (43, 106)


class SourceError(RuntimeError):
    """A source file could not be retrieved."""


class StatsBombSource:
    """Read-through cache over the StatsBomb Open Data raw file URLs."""

    def __init__(self, cache_dir: Path = DEFAULT_CACHE, *, offline: bool = False) -> None:
        self.cache_dir = cache_dir
        self.offline = offline

    def _fetch(self, relative_path: str) -> Any:
        """Return parsed JSON for a path such as ``matches/43/106.json``."""
        cached = self.cache_dir / relative_path
        if cached.exists():
            return json.loads(cached.read_text(encoding="utf-8"))

        if self.offline:
            raise SourceError(f"{relative_path} is not cached and offline mode is set")

        url = f"{BASE_URL}/{relative_path}"
        try:
            # URL is built from a fixed constant host plus a caller-supplied relative path; no
            # user input reaches it.
            with urllib.request.urlopen(url, timeout=60) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise SourceError(f"could not fetch {url}: {exc}") from exc

        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(raw, encoding="utf-8")
        return json.loads(raw)

    def competitions(self) -> list[dict[str, Any]]:
        payload = self._fetch("competitions.json")
        assert isinstance(payload, list)
        return payload

    def matches(self, competition_id: int, season_id: int) -> list[dict[str, Any]]:
        payload = self._fetch(f"matches/{competition_id}/{season_id}.json")
        assert isinstance(payload, list)
        return payload

    def events(self, match_id: int) -> list[dict[str, Any]]:
        payload = self._fetch(f"events/{match_id}.json")
        assert isinstance(payload, list)
        return payload

    def prefetch_events(self, match_ids: list[int], *, workers: int = 8) -> None:
        """Warm the cache for many matches at once.

        Downloads dominate the wall-clock time of a load, and they are independent, so a small
        thread pool turns minutes into seconds. Kept modest to stay polite to the origin.
        """
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(self.events, match_ids))
