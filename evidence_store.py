"""
Where run evidence actually lives on disk, for now.

This is a deliberate simplification: the architecture diagrams earlier
called for MinIO (S3-compatible object storage), but that requires its
own server running. For getting the pipeline genuinely working first,
everything writes to a local folder structure instead. The folder
layout below (one directory per run) is designed to move to MinIO
later with minimal rework -- swap these path-returning functions for
upload calls, and every node that uses them stays the same.

Folder naming: evidence/<slug>_<first 8 chars of run_id>/, e.g.
evidence/product-search-api-e-commerce-store_84894d5c/. The slug is made
from the requirement's Title (see make_slug) so a folder is recognisable
at a glance; the run_id prefix keeps it unique and greppable. Runs that
started before slugs existed keep their old bare-run_id folder name --
find_run_dir() knows about both layouts.
"""

import os
import re
from pathlib import Path

EVIDENCE_ROOT = Path(os.environ.get("QA_FRAMEWORK_ROOT", ".")) / "evidence"

SLUG_MAX_LEN = 40
RUN_ID_PREFIX_LEN = 8


def make_slug(title: str, max_len: int = SLUG_MAX_LEN) -> str:
    """
    'Product Search API - E-commerce Store' -> 'product-search-api-e-commerce-store'.

    Lowercase, whitespace becomes hyphens, anything that isn't a-z, 0-9
    or a hyphen is dropped, runs of hyphens collapse to one, and the
    result is capped at max_len. Falls back to "run" if nothing usable
    is left (empty title, or a title with no ASCII letters/digits).
    """
    slug = re.sub(r"\s+", "-", (title or "").strip().lower())
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:max_len].strip("-") or "run"


def find_run_dir(run_id: str) -> Path | None:
    """
    Finds an existing run's evidence folder from its run_id -- or just
    the first 8 characters of it. Matches the current <slug>_<id8>
    layout and the older layout where the folder was the bare run_id.
    Returns None if there isn't one. Never creates anything.
    """
    if len(run_id) < RUN_ID_PREFIX_LEN or not EVIDENCE_ROOT.is_dir():
        return None
    prefix = run_id[:RUN_ID_PREFIX_LEN]
    matches = sorted(
        p for p in EVIDENCE_ROOT.iterdir()
        if p.is_dir() and (p.name.endswith(f"_{prefix}") or p.name.startswith(f"{prefix}-"))
    )
    if len(matches) > 1:
        raise RuntimeError(
            f"More than one evidence folder matches run id {prefix}: "
            f"{[m.name for m in matches]} -- use the full run_id or remove the extras."
        )
    return matches[0] if matches else None


def run_evidence_dir(run_id: str, slug: str | None = None) -> Path:
    """
    Every artifact for one run lives under evidence/<slug>_<run_id[:8]>/.

    A folder that already exists for this run always wins, so a run keeps
    one folder for its whole life no matter who asks for it (and older
    runs keep their bare-run_id folder). `slug` only matters the first
    time the folder is created; with no slug the old bare-run_id name is
    used.
    """
    d = find_run_dir(run_id)
    if d is None:
        name = f"{slug}_{run_id[:RUN_ID_PREFIX_LEN]}" if slug else run_id
        d = EVIDENCE_ROOT / name
        d.mkdir(parents=True, exist_ok=True)
    return d


def scripts_dir(correlation_id: str, slug: str | None = None) -> Path:
    d = run_evidence_dir(correlation_id, slug) / "scripts"
    d.mkdir(exist_ok=True)
    return d


def allure_results_dir(correlation_id: str, slug: str | None = None) -> Path:
    d = run_evidence_dir(correlation_id, slug) / "allure-results"
    d.mkdir(exist_ok=True)
    return d


def allure_report_dir(correlation_id: str, slug: str | None = None) -> Path:
    d = run_evidence_dir(correlation_id, slug) / "allure-report"
    return d  # created by the `allure generate` command itself, not here
