"""
Where run evidence actually lives on disk, for now.

This is a deliberate simplification: the architecture diagrams earlier
called for MinIO (S3-compatible object storage), but that requires its
own server running. For getting the pipeline genuinely working first,
everything writes to a local folder structure instead. The folder
layout below (one directory per correlation_id) is designed to move
to MinIO later with minimal rework -- swap these path-returning
functions for upload calls, and every node that uses them stays the same.
"""

import os
from pathlib import Path

EVIDENCE_ROOT = Path(os.environ.get("QA_FRAMEWORK_ROOT", ".")) / "evidence"


def run_evidence_dir(correlation_id: str) -> Path:
    """Every artifact for one run lives under evidence/<correlation_id>/."""
    d = EVIDENCE_ROOT / correlation_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def scripts_dir(correlation_id: str) -> Path:
    d = run_evidence_dir(correlation_id) / "scripts"
    d.mkdir(exist_ok=True)
    return d


def allure_results_dir(correlation_id: str) -> Path:
    d = run_evidence_dir(correlation_id) / "allure-results"
    d.mkdir(exist_ok=True)
    return d


def allure_report_dir(correlation_id: str) -> Path:
    d = run_evidence_dir(correlation_id) / "allure-report"
    return d  # created by the `allure generate` command itself, not here
