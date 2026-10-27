"""Freshness and redacted evidence for dual-reference 360 generation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SPATIAL_CONTRACT_SCHEMA_VERSION = "scene_spatial_contract_v8_topology_only_locks"
SCENE_360_SPATIAL_CONTRACT_UNAVAILABLE = "SCENE_360_SPATIAL_CONTRACT_UNAVAILABLE"


class Scene360SpatialContractUnavailable(RuntimeError):
    error_code = SCENE_360_SPATIAL_CONTRACT_UNAVAILABLE


@dataclass(frozen=True)
class Scene360ReferenceAudit:
    reference_count: int
    input_sha256: dict[str, str]
    input_dimensions: dict[str, dict[str, int]]
    overlap_analysis_status: str
    contract_status: str
    prompt_contract_marker: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def has_fresh_contract(self) -> bool:
        return self.overlap_analysis_status == "fresh" and self.contract_status == "fresh"

    @classmethod
    def collect(
        cls,
        *,
        master_path: str | Path,
        reverse_path: str | Path,
        overlap_analysis_path: str | Path,
        spatial_contract_path: str | Path,
        prompt: str = "",
    ) -> "Scene360ReferenceAudit":
        references = {"master": Path(master_path), "reverse": Path(reverse_path)}
        latest_reference_mtime = max(path.stat().st_mtime for path in references.values())
        hashes: dict[str, str] = {}
        dimensions: dict[str, dict[str, int]] = {}
        from PIL import Image

        for name, path in references.items():
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            with Image.open(path) as image:
                dimensions[name] = {"width": int(image.width), "height": int(image.height)}

        overlap_path = Path(overlap_analysis_path)
        overlap_status = _analysis_status(
            overlap_path,
            reference_paths=references,
            latest_reference_mtime=latest_reference_mtime,
        )
        contract_status, contract_insert = _contract_status(
            Path(spatial_contract_path),
            reference_paths=references,
            overlap_path=overlap_path,
            latest_reference_mtime=latest_reference_mtime,
        )
        return cls(
            reference_count=2,
            input_sha256=hashes,
            input_dimensions=dimensions,
            overlap_analysis_status=overlap_status,
            contract_status=contract_status,
            prompt_contract_marker=bool(contract_insert and contract_insert in prompt),
        )


def _inputs_match(data: dict[str, Any], reference_paths: dict[str, Path]) -> bool:
    inputs = data.get("inputs")
    if not isinstance(inputs, dict):
        return False
    return all(
        isinstance(inputs.get(name), str)
        and Path(inputs[name]).expanduser().resolve() == path.expanduser().resolve()
        for name, path in reference_paths.items()
    )


def _analysis_status(
    path: Path,
    *,
    reference_paths: dict[str, Path],
    latest_reference_mtime: float,
) -> str:
    if not path.is_file():
        return "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "invalid"
    if not isinstance(data, dict) or not _inputs_match(data, reference_paths):
        return "invalid"
    return "fresh" if path.stat().st_mtime >= latest_reference_mtime else "stale"


def _contract_status(
    path: Path,
    *,
    reference_paths: dict[str, Path],
    overlap_path: Path,
    latest_reference_mtime: float,
) -> tuple[str, str]:
    if not path.is_file():
        return "missing", ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "invalid", ""
    prompt_insert = data.get("pano_prompt_insert")
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != SPATIAL_CONTRACT_SCHEMA_VERSION
        or not _inputs_match(data, reference_paths)
        or not isinstance(prompt_insert, str)
        or not prompt_insert.strip()
    ):
        return "invalid", ""
    if path.stat().st_mtime < latest_reference_mtime:
        return "stale", ""
    if not overlap_path.is_file() or path.stat().st_mtime < overlap_path.stat().st_mtime:
        return "stale", ""
    return "fresh", prompt_insert.strip()
