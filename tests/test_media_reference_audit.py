from __future__ import annotations

from pathlib import Path
import hashlib
import os

from novelvideo.freezone.history import build_node_history_record


def test_runner_audit_hashes_ordered_reference_files_without_paths(tmp_path: Path):
    from PIL import Image

    from novelvideo.task_backend.runners.freezone import _reference_audit_from_payload

    first = tmp_path / "private-a.png"
    second = tmp_path / "private-b.png"
    Image.new("RGB", (10, 8), "red").save(first)
    Image.new("RGB", (5, 7), "blue").save(second)

    audit = _reference_audit_from_payload({
        "reference_paths": [str(first), str(second)],
        "request_schema": {"referenceFormat": "images", "endpoint": "images/generations"},
    })

    assert audit["reference_count"] == 2
    assert audit["reference_sha256"] == [
        hashlib.sha256(first.read_bytes()).hexdigest(),
        hashlib.sha256(second.read_bytes()).hexdigest(),
    ]
    assert audit["reference_dimensions"] == [
        {"width": 10, "height": 8},
        {"width": 5, "height": 7},
    ]
    assert audit["reference_protocol"] == "images"
    assert audit["request_path"] == "/images/generations"
    assert str(first) not in str(audit)


def test_history_record_keeps_redacted_reference_audit():
    audit = {
        "reference_count": 2,
        "reference_sha256": ["a" * 64, "b" * 64],
        "reference_protocol": "images",
        "request_path": "/images/edits",
        "provider_request_id": "request-123",
        "reference_urls": ["https://signed.example/token"],
    }

    record = build_node_history_record(
        task_type="freezone_gen",
        job_id="job-1",
        task_key="task-1",
        status="completed",
        media_type="image",
        reference_audit=audit,
    )

    assert record["reference_audit"] == {
        "reference_count": 2,
        "reference_sha256": ["a" * 64, "b" * 64],
        "reference_protocol": "images",
        "request_path": "/images/edits",
        "provider_request_id": "request-123",
    }
    assert "signed.example" not in str(record)


def test_history_reference_audit_rejects_unrecognized_protocol_and_paths():
    record = build_node_history_record(
        task_type="freezone_gen",
        job_id="job-2",
        task_key="task-2",
        status="completed",
        media_type="image",
        reference_audit={
            "reference_count": 1,
            "reference_sha256": ["c" * 64],
            "reference_protocol": "https://signed.example/token",
            "request_path": "https://signed.example/request",
            "provider_request_id": "https://signed.example/request-id",
        },
    )

    audit = record["reference_audit"]
    assert audit["reference_count"] == 1
    assert "reference_protocol" not in audit
    assert "request_path" not in audit
    assert "provider_request_id" not in audit


def test_scene_360_reference_audit_records_hash_dimensions_and_freshness(
    tmp_path: Path,
):
    import json
    import os

    from PIL import Image

    from novelvideo.director_world.scene_360_reference_audit import (
        SCENE_360_SPATIAL_CONTRACT_UNAVAILABLE,
        Scene360ReferenceAudit,
    )

    master = tmp_path / "master.png"
    reverse = tmp_path / "reverse.png"
    Image.new("RGB", (12, 8), "red").save(master)
    Image.new("RGB", (9, 7), "blue").save(reverse)
    overlap = tmp_path / "overlap.json"
    contract = tmp_path / "contract.json"
    inputs = {"master": str(master), "reverse": str(reverse)}
    overlap.write_text(json.dumps({"inputs": inputs, "pano_prompt_insert": "overlap"}))
    contract.write_text(json.dumps({
        "schema_version": "scene_spatial_contract_v8_topology_only_locks",
        "inputs": inputs,
        "pano_prompt_insert": "spatial lock",
    }))
    current = max(master.stat().st_mtime, reverse.stat().st_mtime) + 1
    os.utime(overlap, (current, current))
    os.utime(contract, (current + 1, current + 1))

    audit = Scene360ReferenceAudit.collect(
        master_path=master,
        reverse_path=reverse,
        overlap_analysis_path=overlap,
        spatial_contract_path=contract,
        prompt="scene rules\nspatial lock",
    )

    assert audit.reference_count == 2
    assert len(audit.input_sha256["master"]) == 64
    assert audit.input_dimensions == {
        "master": {"width": 12, "height": 8},
        "reverse": {"width": 9, "height": 7},
    }
    assert audit.overlap_analysis_status == "fresh"
    assert audit.contract_status == "fresh"
    assert audit.prompt_contract_marker is True
    assert audit.as_dict()["reference_count"] == 2
    assert SCENE_360_SPATIAL_CONTRACT_UNAVAILABLE == "SCENE_360_SPATIAL_CONTRACT_UNAVAILABLE"


def test_scene_360_builder_manifest_contains_contract_audit_and_prompt_marker(
    monkeypatch, tmp_path: Path
):
    import asyncio
    import json
    from types import SimpleNamespace

    from PIL import Image

    from novelvideo.director_world import scene_360_builder

    master = tmp_path / "master.png"
    reverse = tmp_path / "reverse.png"
    Image.new("RGB", (12, 8), "red").save(master)
    Image.new("RGB", (9, 7), "blue").save(reverse)
    overlap_dir = tmp_path / "overlap_continuation_test"
    overlap_dir.mkdir()
    overlap = overlap_dir / "overlap_continuation_analysis.json"
    inputs = {"master": str(master), "reverse": str(reverse)}
    overlap.write_text(json.dumps({"inputs": inputs, "pano_prompt_insert": "Join both sides"}))
    contract_dir = tmp_path / "scene_spatial_contract"
    contract_dir.mkdir()
    contract = contract_dir / "scene_spatial_contract.json"
    contract.write_text(json.dumps({
        "schema_version": scene_360_builder.SPATIAL_CONTRACT_SCHEMA_VERSION,
        "inputs": inputs,
        "pano_prompt_insert": "Keep the physical continuity lock.",
    }))
    current = max(master.stat().st_mtime, reverse.stat().st_mtime) + 1
    os.utime(overlap, (current, current))
    os.utime(contract, (current + 1, current + 1))
    monkeypatch.setattr(scene_360_builder, "load_env", lambda: None)
    monkeypatch.setattr(
        scene_360_builder,
        "_resolve_newapi_credentials",
        lambda *, model: ("test-key", "https://gateway.invalid/v1", model),
    )
    captured: dict[str, str] = {}

    async def fake_call(**kwargs):
        captured["prompt"] = kwargs["prompt"]
        kwargs["trace"].update({"request_id": "provider-req-1"})
        return master.read_bytes(), "", ""

    monkeypatch.setattr(scene_360_builder, "_call_newapi_image_api", fake_call)
    args = SimpleNamespace(
        quality="medium",
        image_size="2K",
        provider="newapi",
        output_dir=str(tmp_path / "generated"),
        scene_name="scene",
        scene_description="A small room",
        style="realistic",
        master=str(master),
        reverse_master=str(reverse),
        spatial_layout="",
        spatial_contract=str(contract),
        overlap_analysis=str(overlap),
        text_only=False,
        model="model-x",
        layer_mode="full_environment",
    )

    assert asyncio.run(scene_360_builder.run(args)) == 0
    manifest = json.loads(
        (tmp_path / "generated" / "scene_360_manifest.json").read_text()
    )
    audit = manifest["reference_audit"]
    assert "Keep the physical continuity lock." in captured["prompt"]
    assert audit["reference_count"] == 2
    assert audit["input_dimensions"]["master"] == {"width": 12, "height": 8}
    assert audit["overlap_analysis_status"] == "fresh"
    assert audit["contract_status"] == "fresh"
    assert audit["prompt_contract_marker"] is True
    assert audit["input_sha256"]["master"]
