from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_asset_generation_schemas_accept_explicit_global_image_parameters() -> None:
    from novelvideo.api.schemas import (
        IdentityImageGenRequest,
        PortraitGenRequest,
        PropReferenceGenerateRequest,
        SceneReferenceGenerateRequest,
    )

    requests = (
        PortraitGenRequest(image_size="4K", quality="xhigh"),
        IdentityImageGenRequest(image_size="4K", quality="xhigh"),
        PropReferenceGenerateRequest(image_size="4K", quality="xhigh"),
        SceneReferenceGenerateRequest(image_size="4K", quality="xhigh"),
    )

    assert all(request.image_size == "4K" for request in requests)
    assert all(request.quality == "xhigh" for request in requests)


class _QueuedBackend:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def enqueue_project_task(self, ctx, **kwargs):
        self.calls.append({"ctx": ctx, **kwargs})
        return SimpleNamespace(
            task_state=SimpleNamespace(task_id="task-1"),
            backend="test",
            queue="default",
        )


@pytest.mark.asyncio
async def test_character_portrait_route_carries_parameters_into_task_and_billing(
    monkeypatch, tmp_path
):
    from novelvideo.api.routes import characters
    from novelvideo.api.schemas import PortraitGenRequest

    ctx = SimpleNamespace(project_id="project-demo")
    backend = _QueuedBackend()

    async def fake_resolve_project(*_args, **_kwargs):
        return ctx, "admin", "demo", tmp_path, str(tmp_path), None

    def billing(model, *, image_role="character", image_size=None, quality=None):
        return {
            "pricing_model": model,
            "pricing_params": {"size": image_size, "quality": quality},
        }

    monkeypatch.setattr(
        characters,
        "_resolve_character_project",
        fake_resolve_project,
    )
    monkeypatch.setattr(characters, "load_project_config", lambda *_args: {})
    monkeypatch.setattr(characters, "_character_image_billing_metadata", billing)
    monkeypatch.setattr(characters, "get_task_backend", lambda: backend)

    await characters.generate_single_portrait_async(
        project="demo",
        name="Ada",
        body=PortraitGenRequest(
            model="gpt-image-2",
            image_size="4K",
            quality="xhigh",
        ),
        user={"username": "admin"},
    )

    payload = backend.calls[0]["payload"]
    assert payload["image_size"] == "4K"
    assert payload["quality"] == "xhigh"
    assert payload["billing"]["pricing_params"] == {"size": "4K", "quality": "xhigh"}


@pytest.mark.asyncio
async def test_identity_image_route_carries_parameters_into_task_and_billing(
    monkeypatch, tmp_path
):
    from novelvideo.api.routes import characters
    from novelvideo.api.schemas import IdentityImageGenRequest

    ctx = SimpleNamespace(project_id="project-demo")
    backend = _QueuedBackend()
    identity = SimpleNamespace(identity_id="Ada_Adult", identity_name="Adult")
    character = SimpleNamespace(name="Ada", identities=[identity])
    store = SimpleNamespace(get_character=lambda _name: character)

    async def fake_resolve_project(*_args, **_kwargs):
        return ctx, "admin", "demo", tmp_path, str(tmp_path), store

    def billing(model, *, image_role="character", image_size=None, quality=None):
        return {"pricing_params": {"size": image_size, "quality": quality}}

    monkeypatch.setattr(characters, "_resolve_character_project", fake_resolve_project)
    monkeypatch.setattr(characters, "_asset_url", lambda *_args, **_kwargs: "/asset.png")
    monkeypatch.setattr(characters, "load_project_config", lambda *_args: {})
    monkeypatch.setattr(characters, "_character_image_billing_metadata", billing)
    monkeypatch.setattr(characters, "get_task_backend", lambda: backend)

    await characters.generate_identity_image_async(
        project="demo",
        name="Ada",
        identity_id="Ada_Adult",
        body=IdentityImageGenRequest(
            model="gpt-image-2",
            image_size="4K",
            quality="xhigh",
        ),
        user={"username": "admin"},
    )

    payload = backend.calls[0]["payload"]
    assert payload["image_size"] == "4K"
    assert payload["quality"] == "xhigh"
    assert payload["billing"]["pricing_params"] == {"size": "4K", "quality": "xhigh"}


@pytest.mark.asyncio
async def test_direct_character_portrait_forwards_parameters_to_generator(
    monkeypatch, tmp_path
):
    from novelvideo.api.routes import characters
    from novelvideo.api.schemas import PortraitGenRequest

    character = SimpleNamespace(name="Ada", face_prompt="sharp eyes")
    store = SimpleNamespace(
        get_character=lambda _name: character,
        touch_character_asset=lambda *_args: _async_result(None),
    )
    captured: dict = {}
    source = tmp_path / "source.png"
    source.write_bytes(b"png")

    async def fake_resolve_project(*_args, **_kwargs):
        return None, "admin", "demo", tmp_path, str(tmp_path), store

    async def fake_generate(**kwargs):
        captured.update(kwargs)
        return [str(source)]

    monkeypatch.setattr(characters, "_resolve_character_project", fake_resolve_project)
    monkeypatch.setattr(characters, "_asset_url", lambda *_args, **_kwargs: "/asset.png")
    monkeypatch.setattr(characters, "load_project_config", lambda *_args: {})
    monkeypatch.setattr(characters, "load_project_config_file", lambda *_args: {})
    monkeypatch.setattr(characters, "_resolve_character_image_model", lambda *_args: "gpt-image-2")
    monkeypatch.setattr("novelvideo.generators.image_generator.generate_character_reference_unified", fake_generate)

    result = await characters.generate_single_portrait(
        project="demo",
        name="Ada",
        body=PortraitGenRequest(image_size="4K", quality="xhigh"),
        user={"username": "admin"},
    )

    assert result["ok"] is True
    assert captured["image_size"] == "4K"
    assert captured["quality"] == "xhigh"


def test_asset_generation_parameters_keep_legacy_portrait_size_when_omitted(
    monkeypatch,
):
    from novelvideo.api.routes import characters

    monkeypatch.setattr(characters, "load_project_config_file", lambda *_args: {})

    image_size, quality = characters._asset_generation_parameters(
        "admin",
        "demo",
        requested_size=None,
        requested_quality=None,
        default_size="0.5K",
        default_quality="medium",
    )

    assert (image_size, quality) == ("0.5K", "medium")


@pytest.mark.asyncio
async def test_scene_reference_route_carries_parameters_into_task_and_billing(
    monkeypatch, tmp_path
):
    from novelvideo.api.routes import scenes
    from novelvideo.api.schemas import SceneReferenceGenerateRequest

    ctx = SimpleNamespace(project_id="project-demo")
    backend = _QueuedBackend()
    store = SimpleNamespace(
        get_scene=lambda _name: _async_result(SimpleNamespace(name="Hall"))
    )

    async def fake_resolve_project(*_args, **_kwargs):
        return ctx, "admin", "demo", tmp_path, str(tmp_path), store

    def billing(model, *, image_size=None, quality=None):
        return {"pricing_params": {"size": image_size, "quality": quality}}

    monkeypatch.setattr(scenes, "_resolve_scene_project", fake_resolve_project)
    monkeypatch.setattr(scenes, "_project_style", lambda *_args: "project-style")
    monkeypatch.setattr(scenes, "_scene_reference_billing_metadata", billing)
    monkeypatch.setattr(scenes, "get_task_backend", lambda: backend)

    await scenes.generate_scene_master(
        project="demo",
        name="Hall",
        body=SceneReferenceGenerateRequest(
            model="gpt-image-2",
            image_size="4K",
            quality="xhigh",
        ),
        user={"username": "admin"},
    )

    payload = backend.calls[0]["payload"]
    assert payload["image_size"] == "4K"
    assert payload["quality"] == "xhigh"
    assert payload["billing"]["pricing_params"] == {"size": "4K", "quality": "xhigh"}


async def _async_result(value):
    return value


@pytest.mark.asyncio
async def test_prop_reference_route_carries_parameters_into_task_and_billing(
    monkeypatch, tmp_path
):
    from novelvideo.api.routes import model_credits, props
    from novelvideo.api.schemas import PropReferenceGenerateRequest
    from novelvideo.generators import nanobanana_prop

    ctx = SimpleNamespace(project_id="project-demo")
    backend = _QueuedBackend()
    prop = SimpleNamespace(name="Sword", visual_prompt="steel blade", description="")
    store = SimpleNamespace(get_prop=lambda _name: _async_result(prop))
    resolved = SimpleNamespace(
        ctx=ctx,
        username="admin",
        project_name="demo",
        output_dir=str(tmp_path),
    )
    billing_calls: list[dict] = []

    async def fake_store(*_args, **_kwargs):
        return store

    async def fake_resolve(*_args, **_kwargs):
        return resolved

    def fixed_billing(_kind, *, model, image_size=None, quality=None):
        billing_calls.append({"size": image_size, "quality": quality})
        return {"size": image_size, "quality": quality}

    monkeypatch.setattr(props, "resolve_project_scope", fake_resolve)
    monkeypatch.setattr(props, "make_sqlite_store_for_context", fake_store)
    monkeypatch.setattr(props, "_project_style", lambda *_args: "project-style")
    monkeypatch.setattr(props, "get_task_backend", lambda: backend)
    monkeypatch.setattr(nanobanana_prop, "_prop_reference_image_source", lambda _model: (None, "gpt-image-2"))
    monkeypatch.setattr(nanobanana_prop, "resolve_prop_reference_image_model", lambda: "gpt-image-2")
    monkeypatch.setattr(model_credits, "_fixed_image_billing_params", fixed_billing)

    await props.generate_prop_reference(
        project="demo",
        name="Sword",
        body=PropReferenceGenerateRequest(
            model="gpt-image-2",
            image_size="4K",
            quality="xhigh",
        ),
        user={"username": "admin"},
    )

    payload = backend.calls[0]["payload"]
    assert payload["image_size"] == "4K"
    assert payload["quality"] == "xhigh"
    assert billing_calls == [{"size": "4K", "quality": "xhigh"}]


@pytest.mark.asyncio
async def test_character_portrait_runner_forwards_size_and_quality(monkeypatch, tmp_path):
    from novelvideo.task_backend.runners import character_image

    captured: dict = {}
    source = tmp_path / "generated.png"
    source.write_bytes(b"png")

    async def fake_generate(**kwargs):
        captured.update(kwargs)
        return [str(source)]

    monkeypatch.setattr(
        "novelvideo.generators.generate_character_reference_unified",
        fake_generate,
    )
    character = SimpleNamespace(name="Ada", face_prompt="sharp eyes")

    result = await character_image._generate_character_portrait(
        character=character,
        ethnicity="Chinese",
        state_dir=str(tmp_path),
        output_dir=tmp_path,
        style="realistic",
        model="gpt-image-2",
        image_size="4K",
        quality="xhigh",
        task_type="character_portrait",
        scope="character:Ada:portrait",
        update=lambda *_args: None,
    )

    assert result.exists()
    assert captured["image_size"] == "4K"
    assert captured["quality"] == "xhigh"


@pytest.mark.asyncio
async def test_character_generator_entrypoint_forwards_parameters_to_provider_model(
    monkeypatch, tmp_path
):
    from novelvideo.generators import image_generator
    from novelvideo.generators import nanobanana_character

    captured: dict = {}

    class FakeGenerator:
        def __init__(self, **_kwargs):
            pass

        async def generate_character_portrait(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(success=True, reference_paths=[str(tmp_path / "portrait.png")])

    monkeypatch.setattr(nanobanana_character, "NanoBananaCharacterGenerator", FakeGenerator)

    paths = await image_generator.generate_character_reference_unified(
        character_name="Ada",
        appearance_prompt="sharp eyes",
        output_dir=str(tmp_path),
        model="nanobanana",
        image_size="4K",
        quality="xhigh",
    )

    assert paths == [str(tmp_path / "portrait.png")]
    assert captured["image_size"] == "4K"
    assert captured["quality"] == "xhigh"


@pytest.mark.asyncio
async def test_character_openai_adapter_sends_explicit_global_parameters(monkeypatch):
    from novelvideo.generators import nanobanana_character

    captured: dict = {}

    async def fake_openai(**kwargs):
        captured.update(kwargs)
        return b"png", "", ""

    monkeypatch.setattr(nanobanana_character, "_call_openai_image_api", fake_openai)
    generator = object.__new__(nanobanana_character.NanoBananaCharacterGenerator)
    generator.egress_context = None
    generator.provider = "openai"
    generator.model = "gpt-image-2"
    generator.api_key = "test-key"
    generator.openai_image_quality = "medium"
    generator.base_url = ""

    result = await generator._generate_single_image(
        client=None,
        prompt="portrait",
        image_size="4K",
        quality="xhigh",
    )

    assert result == b"png"
    assert captured["image_config"]["image_size"] == "4K"
    assert captured["image_config"]["quality"] == "xhigh"


@pytest.mark.asyncio
async def test_character_portrait_generator_accepts_and_forwards_asset_settings(
    monkeypatch, tmp_path
):
    from novelvideo.generators import nanobanana_character

    captured: dict = {}
    generator = object.__new__(nanobanana_character.NanoBananaCharacterGenerator)
    generator.provider = "openai"
    generator.model = "gpt-image-2"
    generator.api_key = "test-key"
    generator.egress_context = None
    generator._generate_character_tag = lambda _name: "Ada"
    generator._build_character_prompt = lambda **_kwargs: "portrait prompt"

    async def fake_generate_single_image(**kwargs):
        captured.update(kwargs)
        return b"png"

    monkeypatch.setattr(nanobanana_character, "get_style_preset", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(generator, "_generate_single_image", fake_generate_single_image)

    result = await generator.generate_character_portrait(
        character_name="Ada",
        character_prompt="sharp eyes",
        output_dir=str(tmp_path),
        style="realistic",
        image_size="4K",
        quality="xhigh",
    )

    assert result.success
    assert captured["image_size"] == "4K"
    assert captured["quality"] == "xhigh"


@pytest.mark.asyncio
async def test_prop_openai_request_forwards_explicit_size_and_quality(monkeypatch, tmp_path):
    from novelvideo.generators import nanobanana_prop

    captured: dict = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return b"png", "", ""

    monkeypatch.setattr(nanobanana_prop, "_call_openai_image_api", fake_call)

    result = await nanobanana_prop._generate_via_openai(
        prompt="prop",
        output_path=str(tmp_path / "prop.png"),
        api_key="test-key",
        model="gpt-image-2",
        image_size="4K",
        quality="xhigh",
    )

    assert result is not None
    assert captured["image_config"]["image_size"] == "4K"
    assert captured["image_config"]["quality"] == "xhigh"


@pytest.mark.asyncio
async def test_prop_openai_rejection_is_visible_without_retry(monkeypatch, tmp_path):
    from novelvideo.generators import nanobanana_prop

    attempts = 0

    async def reject_request(**_kwargs):
        nonlocal attempts
        attempts += 1
        return None, "", "Unsupported parameter: quality"

    monkeypatch.setattr(nanobanana_prop, "_call_openai_image_api", reject_request)

    with pytest.raises(RuntimeError, match="Unsupported parameter: quality"):
        await nanobanana_prop._generate_via_openai(
            prompt="prop",
            output_path=str(tmp_path / "prop.png"),
            api_key="test-key",
            model="gpt-image-2",
            image_size="4K",
            quality="xhigh",
        )

    assert attempts == 1


def test_scene_reference_config_preserves_explicit_size_and_quality() -> None:
    from novelvideo.generators.scene_reference_images import _scene_image_config

    assert _scene_image_config(
        "gpt-image-2", image_size="4K", quality="xhigh"
    ) == {
        "aspect_ratio": "16:9",
        "image_size": "4K",
        "quality": "xhigh",
        "output_format": "png",
    }


def test_fixed_asset_billing_params_use_explicit_size_and_quality(monkeypatch) -> None:
    from novelvideo.api.routes import model_credits

    assert model_credits._fixed_image_billing_params(
        "prop_reference",
        model="gpt-image-2",
        image_size="4K",
        quality="xhigh",
    ) == {"size": "4K", "quality": "xhigh"}


def test_character_image_billing_uses_explicit_global_values_without_catalog_gate(
    monkeypatch,
):
    from novelvideo.api.routes import model_credits

    monkeypatch.setattr(model_credits, "_image_model_supports_quality", lambda _model: False)
    assert model_credits._image_selection_billing_params(
        model="catalog-omits-quality",
        image_role="character",
        image_size="4K",
        quality="xhigh",
    ) == {"size": "4K", "quality": "xhigh"}


def test_provider_quality_normalizers_preserve_all_global_values():
    from novelvideo.generators.nanobanana_grid import (
        _normalize_newapi_image_quality,
        normalize_openai_quality,
    )

    expected = ["auto", "low", "medium", "high", "xhigh", "max"]
    assert [normalize_openai_quality(value) for value in expected] == expected
    assert [_normalize_newapi_image_quality(value) for value in expected] == expected
