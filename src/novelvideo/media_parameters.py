"""Product-wide media generation parameter contracts."""

from __future__ import annotations

from typing import Literal, TypeVar

ImageSize = Literal["1K", "2K", "4K"]
ImageQuality = Literal["auto", "low", "medium", "high", "xhigh", "max"]
VideoGenerationResolution = Literal["720p", "768p", "1080p", "2k", "4k"]

IMAGE_SIZE_OPTIONS: tuple[ImageSize, ...] = ("1K", "2K", "4K")
IMAGE_QUALITY_OPTIONS: tuple[ImageQuality, ...] = (
    "auto",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)
VIDEO_GENERATION_RESOLUTION_OPTIONS: tuple[VideoGenerationResolution, ...] = (
    "720p",
    "768p",
    "1080p",
    "2k",
    "4k",
)

_Parameter = TypeVar("_Parameter", bound=str)


def _validate(value: str, options: tuple[_Parameter, ...], label: str) -> str:
    if value in options:
        return value
    choices = ", ".join(options)
    raise ValueError(f"{label} must be one of: {choices}")


def validate_image_size(value: str) -> str:
    """Validate a product image-size tier without changing its spelling."""
    return _validate(value, IMAGE_SIZE_OPTIONS, "image_size")


def validate_image_quality(value: str) -> str:
    """Validate a product image-quality tier without changing its spelling."""
    return _validate(value, IMAGE_QUALITY_OPTIONS, "quality")


def validate_video_generation_resolution(value: str) -> str:
    """Validate a generated-video resolution without changing its spelling."""
    return _validate(value, VIDEO_GENERATION_RESOLUTION_OPTIONS, "resolution")


def resolve_asset_image_parameters(
    *,
    requested_size: str | None,
    requested_quality: str | None,
    stored_size: str | None,
    stored_quality: str | None,
    default_size: str,
    default_quality: str,
) -> tuple[str, str]:
    """Resolve explicit asset parameters before stored and legacy defaults."""
    if requested_size is not None:
        image_size = validate_image_size(requested_size)
    else:
        try:
            image_size = validate_image_size(str(stored_size or ""))
        except ValueError:
            image_size = default_size
    if requested_quality is not None:
        image_quality = validate_image_quality(requested_quality)
    else:
        try:
            image_quality = validate_image_quality(str(stored_quality or ""))
        except ValueError:
            image_quality = default_quality
    return image_size, image_quality
