from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_render_provider_rejection_is_not_retried_without_quality(
    monkeypatch,
):
    from novelvideo.generators import nanobanana_grid
    import openai

    calls: list[dict] = []

    class FakeImages:
        async def generate(self, **kwargs):
            calls.append(kwargs)
            raise RuntimeError("Unsupported parameter: 'quality'")

    class FakeClient:
        def __init__(self, **_kwargs):
            self.images = FakeImages()

    class FakeUsageMeter:
        async def reserve_current_model_call_credit(self, **_kwargs):
            return "reservation"

        async def refund_model_call_credit_reservation(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(nanobanana_grid, "get_usage_meter", lambda: FakeUsageMeter())
    monkeypatch.setattr(nanobanana_grid, "_mark_paid_image_attempt_accepted", _noop_async)
    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)

    result = await nanobanana_grid._call_openai_image_api(
        api_key="test-key",
        model="gpt-image-2",
        prompt="a rainy street",
        image_config={
            "image_size": "4K",
            "quality": "max",
            "strict_quality": True,
        },
    )

    assert len(calls) == 1
    assert calls[0]["quality"] == "max"
    assert result[0] is None
    assert "quality" in result[2]


async def _noop_async(*_args, **_kwargs):
    return None


def test_render_billing_metadata_keeps_explicit_quality():
    from novelvideo.api.routes.generation import _render_regen_billing_metadata

    billing = _render_regen_billing_metadata(
        "gpt-image-2",
        "1x1_9-16",
        "max",
    )

    assert billing["pricing_params"]["quality"] == "max"
