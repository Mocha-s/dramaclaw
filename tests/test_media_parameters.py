from __future__ import annotations

import importlib
import importlib.util
from typing import get_args

import pytest


def _media_parameters():
    spec = importlib.util.find_spec("novelvideo.media_parameters")
    assert spec is not None, "global media parameter contract module is missing"
    return importlib.import_module("novelvideo.media_parameters")


def test_global_media_parameter_contract_has_exact_product_values() -> None:
    params = _media_parameters()

    assert params.IMAGE_SIZE_OPTIONS == ("1K", "2K", "4K")
    assert params.IMAGE_QUALITY_OPTIONS == (
        "auto",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    )
    assert params.VIDEO_GENERATION_RESOLUTION_OPTIONS == (
        "720p",
        "768p",
        "1080p",
        "2k",
        "4k",
    )


@pytest.mark.parametrize(
    ("alias_name", "expected"),
    [
        ("ImageSize", ("1K", "2K", "4K")),
        ("ImageQuality", ("auto", "low", "medium", "high", "xhigh", "max")),
        (
            "VideoGenerationResolution",
            ("720p", "768p", "1080p", "2k", "4k"),
        ),
    ],
)
def test_literal_aliases_match_the_public_values(
    alias_name: str, expected: tuple[str, ...]
) -> None:
    params = _media_parameters()

    assert get_args(getattr(params, alias_name)) == expected


@pytest.mark.parametrize(
    ("validator_name", "values"),
    [
        ("validate_image_size", ("1K", "2K", "4K")),
        ("validate_image_quality", ("auto", "low", "medium", "high", "xhigh", "max")),
        (
            "validate_video_generation_resolution",
            ("720p", "768p", "1080p", "2k", "4k"),
        ),
    ],
)
def test_validators_preserve_each_canonical_value(
    validator_name: str, values: tuple[str, ...]
) -> None:
    params = _media_parameters()
    validator = getattr(params, validator_name)

    for value in values:
        assert validator(value) == value


@pytest.mark.parametrize(
    ("validator_name", "invalid_value"),
    [
        ("validate_image_size", "8K"),
        ("validate_image_quality", "draft"),
        ("validate_video_generation_resolution", "480p"),
    ],
)
def test_validators_reject_values_outside_the_global_contract(
    validator_name: str, invalid_value: str
) -> None:
    params = _media_parameters()
    validator = getattr(params, validator_name)

    with pytest.raises(ValueError, match="must be one of"):
        validator(invalid_value)


def test_asset_parameter_resolution_prefers_explicit_then_stored_then_legacy():
    params = _media_parameters()
    resolve = params.resolve_asset_image_parameters
    defaults = {"default_size": "1K", "default_quality": "medium"}

    assert resolve(
        requested_size="4K",
        requested_quality="xhigh",
        stored_size="2K",
        stored_quality="low",
        **defaults,
    ) == ("4K", "xhigh")
    assert resolve(
        requested_size=None,
        requested_quality=None,
        stored_size="2K",
        stored_quality="high",
        **defaults,
    ) == ("2K", "high")
    assert resolve(
        requested_size=None,
        requested_quality=None,
        stored_size=None,
        stored_quality=None,
        **defaults,
    ) == ("1K", "medium")


def test_asset_parameter_resolution_rejects_invalid_explicit_values():
    params = _media_parameters()

    with pytest.raises(ValueError, match="image_size"):
        params.resolve_asset_image_parameters(
            requested_size="8K",
            requested_quality=None,
            stored_size=None,
            stored_quality=None,
            default_size="1K",
            default_quality="medium",
        )
