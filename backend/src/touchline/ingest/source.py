"""Fetching and caching StatsBomb Open Data files.

Files are downloaded once into a local cache and read from there afterwards, so a re-run costs
nothing and the exact bytes that produced a load can be inspected. The cache is git-ignored.

**The snapshot is pinned to a commit SHA, not to `master`.** Open Data is a live repository - the
pinned commit's own message is "Added 1647 new games, updated 1213 games" - so a load against
`master` would silently drift, and the measured counts recorded in ADR 0004 would stop meaning
anything. Pinning makes the ingestion reproducible and the counts checkable.

A provenance record (source SHA plus a SHA-256 for every file actually read) is written on each
load and committed, so a second machine can prove it received identical bytes.

Only the selected competition-season is fetched, never the whole repository.

Data provided by StatsBomb: https://github.com/statsbomb/open-data
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

# Pinned snapshot of statsbomb/open-data. Bumping this is a deliberate act: it invalidates every
# measured count in ADR 0004 and PLAN.md, which must be re-measured and updated in the same change.
SOURCE_COMMIT = "b0bc9f22dd77c206ddedc1d742893b3bbe64baec"
SOURCE_COMMIT_DATE = "2026-05-26"

BASE_URL = f"https://raw.githubusercontent.com/statsbomb/open-data/{SOURCE_COMMIT}/data"
DEFAULT_CACHE = Path("data/statsbomb")
PROVENANCE_DIR = Path("data/provenance")

# FIFA World Cup 2022. Fixed for WP0.3; the wider cohort defined in ADR 0004 arrives in M1.
WORLD_CUP_2022 = (43, 106)


class SourceError(RuntimeError):
    """A source file could not be retrieved."""


class StatsBombSource:
    """Read-through cache over the StatsBomb Open Data raw file URLs, at a pinned commit."""

    def __init__(self, cache_dir: Path | None = None, *, offline: bool = False) -> None:
        # The default cache is keyed by commit SHA, so switching snapshots cannot silently mix
        # files from two different versions of the repository. An explicit directory is used
        # as given - that is how tests point at the committed fixture set.
        self.cache_dir = cache_dir if cache_dir is not None else DEFAULT_CACHE / SOURCE_COMMIT[:12]
        self.offline = offline
        self._hashes: dict[str, str] = {}

    def _fetch(self, relative_path: str) -> Any:
        """Return parsed JSON for a path such as ``matches/43/106.json``."""
        cached = self.cache_dir / relative_path
        if cached.exists():
            raw = cached.read_text(encoding="utf-8")
        elif self.offline:
            raise SourceError(f"{relative_path} is not cached and offline mode is set")
        else:
            url = f"{BASE_URL}/{relative_path}"
            try:
                # URL is built from a fixed constant host and pinned commit plus a caller-supplied
                # relative path; no user input reaches it.
                with urllib.request.urlopen(url, timeout=60) as response:
                    raw = response.read().decode("utf-8")
            except urllib.error.URLError as exc:
                raise SourceError(f"could not fetch {url}: {exc}") from exc
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(raw, encoding="utf-8")

        self._hashes[relative_path] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
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

    def lineups(self, match_id: int) -> list[dict[str, Any]]:
        """Return the pinned squad-membership file for a match."""
        payload = self._fetch(f"lineups/{match_id}.json")
        assert isinstance(payload, list)
        return payload

    def prefetch_events(self, match_ids: list[int], *, workers: int = 8) -> None:
        """Warm the cache for many matches at once.

        Downloads dominate the wall-clock time of a load, and they are independent, so a small
        thread pool turns minutes into seconds. Kept modest to stay polite to the origin.
        """
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(self.events, match_ids))

    def prefetch_match_files(self, match_ids: list[int], *, workers: int = 8) -> None:
        """Warm the independent events and lineups files for each selected match."""
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(
                pool.map(
                    lambda match_id: (self.events(match_id), self.lineups(match_id)), match_ids
                )
            )

    def provenance(self) -> dict[str, Any]:
        """Everything needed to prove which bytes produced a load."""
        return {
            "source_repository": "https://github.com/statsbomb/open-data",
            "source_commit": SOURCE_COMMIT,
            "source_commit_date": SOURCE_COMMIT_DATE,
            "file_count": len(self._hashes),
            "files_sha256": dict(sorted(self._hashes.items())),
        }

    def write_provenance(self, name: str, directory: Path = PROVENANCE_DIR) -> Path:
        """Write the provenance record for the files read in this session.

        Committed, unlike the cache, so a reviewer on another machine can verify byte-for-byte
        that they read the same source as the counts in ADR 0004 were measured from.
        """
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.json"
        path.write_text(json.dumps(self.provenance(), indent=2) + "\n", encoding="utf-8")
        return path
