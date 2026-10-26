import base64
import importlib
import logging
from types import SimpleNamespace

import pytest

from novelvideo.shared.billing_errors import BillingError, InsufficientCreditsError

pytestmark = pytest.mark.m04


class _ForeignBillingError(BillingError):
    def __init__(self, **_kwargs) -> None:
        super().__init__("foreign billing error")


def _isolate_settings_db(monkeypatch, tmp_path):
    import novelvideo.config as config

    state_dir = str(tmp_path / "state")
    monkeypatch.delenv("MODEL_GATEWAY_MODE", raising=False)
    monkeypatch.setenv("NOVELVIDEO_STATE_DIR", state_dir)
    monkeypatch.setattr(config, "STATE_DIR", state_dir)


@pytest.fixture(autouse=True)
def _isolated_model_gateway(monkeypatch, tmp_path):
    monkeypatch.delenv("NEWAPI_IMAGE_EDIT_REFERENCE_FORMAT", raising=False)
    _isolate_settings_db(monkeypatch, tmp_path)
    # This module tests low-level environment-driven gateway adapters. CE
    # database precedence is covered in test_model_gateway_settings.py.
    monkeypatch.setenv("ST_CONTROL_PLANE_DSN", "postgresql://test-control-plane")


def _patch_scene_newapi_gateway(
    monkeypatch,
    *,
    api_key: str = "newapi-token",
    base_url: str = "http://newapi.test/v1",
) -> None:
    import novelvideo.config as config

    monkeypatch.setattr(
        config,
        "get_effective_newapi_gateway_config",
        lambda **_kwargs: SimpleNamespace(
            api_key=api_key,
            base_url=base_url,
            model="",
        ),
    )


def test_dc_image_2_selection_maps_to_newapi_gpt_image2(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("NEWAPI_API_KEY", "newapi-token")
    monkeypatch.setenv("NEWAPI_BASE_URL", "http://newapi.test/v1")
    monkeypatch.setenv("NEWAPI_IMAGE_MODEL", "LingShan-G2")
    monkeypatch.setenv("DEFAULT_CHARACTER_IMAGE_SELECTION", "gpt-image-2")

    import novelvideo.config as config

    config = importlib.reload(config)

    assert config.character_image_selection_options()["gpt-image-2"] == "LingShan-G2"
    assert config.get_character_image_selection() == "gpt-image-2"

    image_config = config.get_grid_generation_config(selection_override="gpt-image-2")
    assert image_config["provider"] == "newapi"
    assert image_config["api_key"] == "newapi-token"
    assert image_config["base_url"] == "http://newapi.test/v1"
    assert image_config["model"] == "LingShan-G2"


def test_dc_banana_2_selection_maps_to_newapi_nanobanana2(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("NEWAPI_API_KEY", "newapi-token")
    monkeypatch.setenv("NEWAPI_BASE_URL", "http://newapi.test/v1")
    monkeypatch.setenv("NEWAPI_NANOBANANA2_MODEL", "LingShan-NB-2")
    monkeypatch.setenv("DEFAULT_CHARACTER_IMAGE_SELECTION", "nano-banana-2")

    import novelvideo.config as config

    config = importlib.reload(config)

    assert config.character_image_selection_options()["nano-banana-2"] == "LingShan-NB-2"
    assert config.get_character_image_selection() == "nano-banana-2"

    image_config = config.get_grid_generation_config(selection_override="nano-banana-2")
    assert image_config["provider"] == "newapi"
    assert image_config["api_key"] == "newapi-token"
    assert image_config["base_url"] == "http://newapi.test/v1"
    assert image_config["model"] == "LingShan-NB-2"


def test_fixed_asset_image_providers_default_to_newapi_when_env_is_empty(monkeypatch):
    for key in (
        "PROP_REF_IMAGE_PROVIDER",
        "PROP_REF_IMAGE_MODEL",
        "SCENE_MASTER_IMAGE_PROVIDER",
        "SCENE_REVERSE_MASTER_IMAGE_PROVIDER",
        "SCENE_360_IMAGE_PROVIDER",
    ):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("NEWAPI_IMAGE_MODEL", "LingShan-G2")

    import novelvideo.config as config

    config = importlib.reload(config)

    assert config.PROP_REF_IMAGE_PROVIDER == "newapi"
    assert config.SCENE_MASTER_IMAGE_PROVIDER == "newapi"
    assert config.SCENE_REVERSE_MASTER_IMAGE_PROVIDER == "newapi"
    assert config.SCENE_360_IMAGE_PROVIDER == "newapi"

    from novelvideo.generators import nanobanana_prop, scene_reference_images

    nanobanana_prop = importlib.reload(nanobanana_prop)
    scene_reference_images = importlib.reload(scene_reference_images)

    assert nanobanana_prop.resolve_prop_reference_image_model() == "LingShan-G2"
    assert scene_reference_images._scene_image_provider("master", None) == "newapi"
    assert scene_reference_images._scene_image_provider("reverse_master", None) == "newapi"


def test_configured_image_selection_uses_catalog_request_model_for_scene_and_prop(
    monkeypatch,
):
    import novelvideo.config as config
    import novelvideo.model_gateway_settings as gateway_settings
    from novelvideo.generators import nanobanana_prop
    from novelvideo.task_backend.runners import scene_reference as scene_reference_runner

    monkeypatch.setattr(
        config,
        "_configured_third_party_image_selection_options",
        lambda: {"gpt-image-2": "Configured image"},
    )
    monkeypatch.setattr(
        gateway_settings,
        "get_third_party_media_model_catalog",
        lambda _media_type: [
            {
                "id": "gpt-image-2",
                "apiModel": "gpt-image-2",
                "gatewayModel": "configured-image-model",
            }
        ],
    )

    assert config.resolve_image_generation_source("gpt-image-2") == (
        "newapi",
        "gpt-image-2",
    )
    assert nanobanana_prop._prop_reference_image_source("gpt-image-2") == (
        "newapi",
        "gpt-image-2",
    )
    assert scene_reference_runner._scene_image_source("gpt-image-2") == (
        "newapi",
        "gpt-image-2",
    )


def test_prop_reference_defaults_to_catalog_model_in_canonical_ce(monkeypatch):
    import novelvideo.config as config
    from novelvideo.generators import nanobanana_prop

    monkeypatch.setattr(
        config,
        "_configured_third_party_image_selection_options",
        lambda: {"gpt-image-2": "Configured image"},
    )

    assert nanobanana_prop.resolve_prop_reference_image_model() == "gpt-image-2"


def test_configured_image_selection_resolves_third_party_credentials_and_upstream(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.delenv("ST_CONTROL_PLANE_DSN", raising=False)
    monkeypatch.setenv("ST_EDITION", "ce")

    import json

    from novelvideo import config
    from novelvideo import model_gateway_settings

    model_gateway_settings._write_many(
        {
            "model_gateway_mode": "custom",
            "third_party_gateway_groups": json.dumps(
                [
                    {
                        "id": "image",
                        "name": "Image",
                        "protocol": "openai",
                        "baseUrl": "https://images.example/v1",
                        "apiKey": "sk-image",
                        "capabilities": ["image"],
                        "modelMappings": [
                            {
                                "requestPattern": "gpt-image-2",
                                "upstreamModel": "configured-image-model",
                            }
                        ],
                    }
                ]
            ),
        }
    )

    gateway = config.get_effective_newapi_gateway_config(
        capability="image", model="gpt-image-2"
    )

    assert gateway.api_key == "sk-image"
    assert gateway.base_url == "https://images.example/v1"
    assert gateway.model == "configured-image-model"


def test_character_generation_routes_arbitrary_canonical_image_selection_to_newapi(
    monkeypatch, tmp_path
):
    from novelvideo.generators import image_generator

    calls = []

    class FakeCharacterGenerator:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def generate_character_portrait(self, **_kwargs):
            return type("Result", (), {"success": True, "reference_paths": ["portrait.png"]})()

    monkeypatch.setattr(image_generator, "configured_image_generation_selection_options", lambda: {"gpt-image-2.5": "Configured"})
    monkeypatch.setattr(image_generator, "normalize_character_image_selection", lambda value: value)
    monkeypatch.setattr(image_generator, "IMAGE_GENERATION_SELECTIONS", {})
    monkeypatch.setattr(
        "novelvideo.generators.nanobanana_character.NanoBananaCharacterGenerator",
        FakeCharacterGenerator,
    )

    result = run_async(
        image_generator.generate_character_reference_unified(
            character_name="小圆",
            appearance_prompt="人物",
            output_dir=str(tmp_path),
            model="gpt-image-2.5",
        )
    )

    assert result == ["portrait.png"]
    assert calls == [{"selection": "gpt-image-2.5", "egress_context": None}]


@pytest.mark.parametrize("reference_format", ["images", "input_reference", "multipart"])
def test_resolve_third_party_image_request_preserves_canvas_request_metadata(
    monkeypatch, reference_format
):
    from novelvideo import model_gateway_settings

    request_schema = {
        "endpoint": "images/generations",
        "referenceFormat": reference_format,
        "parameters": [],
    }
    catalog = [
        {
            "id": "gpt-image-2",
            "apiModel": "gpt-image-2",
            "gatewayModel": "configured-image-model",
            "request": request_schema,
            "modelParams": {"quality": "high"},
            "gatewayGroupId": "image",
        }
    ]
    monkeypatch.setattr(
        model_gateway_settings,
        "get_third_party_media_model_catalog",
        lambda _media_type: catalog,
    )
    monkeypatch.setattr(
        model_gateway_settings,
        "get_third_party_gateway_groups",
        lambda: [
            {
                "id": "image",
                "baseUrl": "https://images.example/v1",
                "apiKey": "sk-image",
                "protocol": "openai",
            }
        ],
    )

    resolved = model_gateway_settings.resolve_third_party_image_request("gpt-image-2")

    assert resolved["upstream_model"] == "configured-image-model"
    assert resolved["reference_image_format"] == reference_format
    assert resolved["endpoint"] == "images/generations"
    assert resolved["request_schema"] == request_schema
    assert resolved["model_params"] == {"quality": "high"}
    assert resolved["base_url"] == "https://images.example/v1"
    assert resolved["api_key"] == "sk-image"


def test_resolve_third_party_image_request_returns_none_without_canonical_catalog(
    monkeypatch,
):
    from novelvideo import model_gateway_settings

    monkeypatch.setattr(
        model_gateway_settings,
        "get_third_party_media_model_catalog",
        lambda _media_type: [],
    )

    assert model_gateway_settings.resolve_third_party_image_request("gpt-image-2") is None


def test_newapi_sketch_config_defaults_to_dc_image2_low_quality(monkeypatch):
    import httpx
    import novelvideo.config as config
    from novelvideo.generators import nanobanana_grid

    posted = {}

    class FakeResponse:
        headers = {"x-newapi-request-id": "req-sketch"}

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "resp-sketch",
                "data": [{"b64_json": base64.b64encode(b"sketch").decode()}],
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            posted["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            posted["json"] = json
            return FakeResponse()

    monkeypatch.setenv("NEWAPI_API_KEY", "newapi-token")
    monkeypatch.setenv("NEWAPI_BASE_URL", "http://newapi.test/v1")
    monkeypatch.setenv("NEWAPI_IMAGE_MODEL", "LingShan-G2")
    monkeypatch.setenv("DEFAULT_SKETCH_IMAGE_SELECTION", "gpt-image-2")
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    config = importlib.reload(config)
    sketch_config = config.get_sketch_generation_config()

    assert sketch_config["provider"] == "newapi"
    assert sketch_config["model"] == "LingShan-G2"
    assert sketch_config["image_size"] == "1K"
    assert sketch_config["openai_image_quality"] == "low"

    trace = {}
    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key=sketch_config["api_key"],
            model=sketch_config["model"],
            prompt="sketch prompt",
            image_config={
                "aspect_ratio": "2:3",
                "image_size": sketch_config["image_size"],
                "quality": sketch_config["openai_image_quality"],
            },
            base_url=sketch_config["base_url"],
            trace=trace,
        )
    )
    assert posted["json"]["response_format"] == "url"

    assert image_bytes == b"sketch"
    assert error == ""
    assert posted["timeout"] == nanobanana_grid.NEWAPI_IMAGE_HTTP_TIMEOUT_SECONDS == 1800.0
    assert posted["json"]["model"] == "LingShan-G2"
    assert posted["json"]["quality"] == "low"
    assert posted["json"]["size"] == "688x1024"
    assert posted["json"]["metadata"] == {"ratio": "2:3", "resolution": "1k"}
    assert "extra_fields" not in posted["json"]
    assert trace == {"request_id": "req-sketch", "response_id": "resp-sketch"}


def test_newapi_sketch_config_can_use_dc_banana2_without_quality(monkeypatch):
    import httpx
    import novelvideo.config as config
    from novelvideo.generators import nanobanana_grid

    posted = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(b"sketch").decode()}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            posted["json"] = json
            return FakeResponse()

    monkeypatch.setenv("NEWAPI_API_KEY", "newapi-token")
    monkeypatch.setenv("NEWAPI_BASE_URL", "http://newapi.test/v1")
    monkeypatch.setenv("NEWAPI_NANOBANANA2_MODEL", "LingShan-NB-2")
    monkeypatch.setenv("DEFAULT_SKETCH_IMAGE_SELECTION", "nano-banana-2")
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    config = importlib.reload(config)
    sketch_config = config.get_sketch_generation_config()

    assert sketch_config["provider"] == "newapi"
    assert sketch_config["model"] == "LingShan-NB-2"
    assert sketch_config["image_size"] == "1K"

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key=sketch_config["api_key"],
            model=sketch_config["model"],
            prompt="sketch prompt",
            image_config={
                "aspect_ratio": "2:3",
                "image_size": sketch_config["image_size"],
                "quality": sketch_config["openai_image_quality"],
            },
            base_url=sketch_config["base_url"],
        )
    )

    assert image_bytes == b"sketch"
    assert error == ""
    assert posted["json"]["model"] == "LingShan-NB-2"
    assert posted["json"]["quality"] == "low"
    assert posted["json"]["size"] == "688x1024"
    assert posted["json"]["metadata"] == {"ratio": "2:3", "resolution": "1k"}
    assert "extra_fields" not in posted["json"]


def test_catalog_can_enable_arbitrary_newapi_image_quality(monkeypatch):
    import httpx
    from novelvideo.generators import nanobanana_grid

    posted = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(b"image").decode()}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            posted["json"] = json
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="newapi-token",
            model="Seedream-Custom",
            prompt="prompt",
            image_config={
                "aspect_ratio": "adaptive",
                "image_size": "3K",
                "quality": "xhigh",
                "request_schema": {
                    "endpoint": "images/generations",
                    "parameters": [
                        {
                            "key": "watermark",
                            "requestPath": "watermark",
                            "control": "switch",
                            "default": False,
                        }
                    ],
                    "includeQuality": True,
                },
                "model_params": {"watermark": True},
            },
            base_url="http://newapi.test/v1",
        )
    )

    assert image_bytes == b"image"
    assert error == ""
    assert posted["json"]["model"] == "Seedream-Custom"
    assert posted["json"]["quality"] == "xhigh"
    assert "width" not in posted["json"]
    assert "height" not in posted["json"]
    assert posted["json"]["metadata"] == {"ratio": "auto", "resolution": "3k"}
    assert posted["json"]["watermark"] is True
    assert "extra_fields" not in posted["json"]


@pytest.mark.parametrize(
    ("model", "resolution", "ratio"),
    [
        ("custom-seedream-alias", "2K", "3:2"),
        ("future-image-model", "2K", "16:9"),
        ("future-image-model", "2K", "21:9"),
        ("future-image-model", "3K", "16:9"),
        ("future-image-model", "2048x1376", "3:2"),
    ],
)
def test_admin_min_pixels_applies_to_named_and_explicit_resolutions(
    model,
    resolution,
    ratio,
):
    from novelvideo.generators.nanobanana_grid import resolve_openai_image_size

    width, height = (
        int(value)
        for value in resolve_openai_image_size(
            ratio,
            resolution,
            model,
            allow_dynamic_resolution=True,
            min_pixels=3_686_400,
        ).split("x")
    )

    assert width * height >= 3_686_400


@pytest.mark.parametrize(
    ("resolution", "ratio", "expected"),
    [
        ("8K", "16:9", "8192x4608"),
        ("5.5K", "1:1", "5632x5632"),
        ("2048x1152", "1:1", "2048x1152"),
    ],
)
def test_newapi_image_size_supports_dynamic_admin_resolutions(
    resolution,
    ratio,
    expected,
):
    from novelvideo.generators.nanobanana_grid import resolve_openai_image_size

    assert (
        resolve_openai_image_size(
            ratio,
            resolution,
            "future-image-model",
            allow_dynamic_resolution=True,
        )
        == expected
    )


def test_newapi_image_call_rejects_unrecognized_admin_resolution():
    from novelvideo.generators import nanobanana_grid

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="newapi-token",
            model="future-image-model",
            prompt="prompt",
            image_config={"aspect_ratio": "16:9", "image_size": "ultra"},
            base_url="http://newapi.test/v1",
        )
    )

    assert image_bytes is None
    assert "unsupported image resolution: ultra" in error


def test_newapi_image_call_applies_admin_min_pixels(monkeypatch):
    import httpx
    from novelvideo.generators import nanobanana_grid

    posted = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(b"image").decode()}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            posted["json"] = json
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="newapi-token",
            model="arbitrary-admin-model-id",
            prompt="prompt",
            image_config={
                "aspect_ratio": "3:2",
                "image_size": "2048x1376",
                "request_schema": {
                    "endpoint": "images/generations",
                    "parameters": [],
                    "minPixels": 3_686_400,
                },
            },
            base_url="http://newapi.test/v1",
        )
    )

    assert image_bytes == b"image"
    assert error == ""
    width, height = (int(value) for value in posted["json"]["size"].split("x"))
    assert width * height >= 3_686_400
    assert posted["json"]["metadata"] == {
        "ratio": "3:2",
        "resolution": "2048x1376",
    }
    assert posted["json"]["watermark"] is False
    assert "extra_fields" not in posted["json"]


def test_newapi_image_call_sends_gpt_image2_params(monkeypatch):
    import httpx
    from novelvideo.generators import nanobanana_grid

    posted = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(b"image-bytes").decode()}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            posted["url"] = url
            posted["headers"] = headers
            posted["json"] = json
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="newapi-token",
            model="gpt-image-2.5",
            prompt="portrait prompt",
            image_config={
                "aspect_ratio": "3:4",
                "image_size": "0.5K",
                "quality": "medium",
            },
            base_url="http://newapi.test/v1",
        )
    )

    assert image_bytes == b"image-bytes"
    assert error == ""
    assert posted["url"] == "http://newapi.test/v1/images/generations"
    assert posted["headers"]["Authorization"] == "Bearer newapi-token"
    assert posted["json"]["model"] == "gpt-image-2.5"
    assert posted["json"]["prompt"] == "portrait prompt"
    assert posted["json"]["quality"] == "medium"
    assert posted["json"]["size"] == "768x1024"
    assert posted["json"]["tier"] == "1k"
    assert "width" not in posted["json"]
    assert "height" not in posted["json"]
    assert posted["json"]["metadata"] == {"ratio": "3:4", "resolution": "1k"}
    assert "extra_fields" not in posted["json"]


def test_newapi_image_auto_ratio_keeps_resolution_without_dimensions(monkeypatch):
    import httpx
    from novelvideo.generators import nanobanana_grid

    posted = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(b"image-bytes").decode()}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            posted["json"] = json
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="newapi-token",
            model="LingShan-G2",
            prompt="follow the reference geometry",
            image_config={"aspect_ratio": "auto", "image_size": "2K"},
            base_url="http://newapi.test/v1",
        )
    )

    assert image_bytes == b"image-bytes"
    assert error == ""
    assert "width" not in posted["json"]
    assert "height" not in posted["json"]
    assert "size" not in posted["json"]
    assert "tier" not in posted["json"]
    assert posted["json"]["metadata"] == {"ratio": "auto", "resolution": "2k"}


def test_newapi_image_call_omits_invalid_quality_and_tier(monkeypatch):
    import httpx
    from novelvideo.generators import nanobanana_grid

    posted = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(b"image-bytes").decode()}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            posted["json"] = json
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="newapi-token",
            model="gpt-image-2.5",
            prompt="prompt",
            image_config={
                "aspect_ratio": "16:9",
                "image_size": "2K",
                "quality": "ultra",
                "tier": "8k",
            },
            base_url="http://newapi.test/v1",
        )
    )

    assert image_bytes == b"image-bytes"
    assert error == ""
    assert "quality" not in posted["json"]
    assert "tier" not in posted["json"]


def test_newapi_image_call_sends_quality_for_arbitrary_model(monkeypatch):
    import httpx
    from novelvideo.generators import nanobanana_grid

    posted = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(b"image-bytes").decode()}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            posted["json"] = json
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="newapi-token",
            model="arbitrary-image-model",
            prompt="prompt",
            image_config={
                "aspect_ratio": "1:1",
                "image_size": "1K",
                "quality": "high",
            },
            base_url="http://newapi.test/v1",
        )
    )

    assert image_bytes == b"image-bytes"
    assert error == ""
    assert posted["json"]["quality"] == "high"


def test_newapi_image_call_reports_transport_exception_type(monkeypatch):
    import httpx
    from novelvideo.generators import nanobanana_grid

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            raise httpx.ReadTimeout("")

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="newapi-token",
            model="LingShan-G2",
            prompt="portrait prompt",
            image_config={"aspect_ratio": "16:9", "image_size": "1K"},
            base_url="http://newapi.test/v1",
        )
    )

    assert image_bytes is None
    assert "请求异常: ReadTimeout" in error
    assert "endpoint=http://newapi.test/v1" in error
    assert "model=LingShan-G2" in error


@pytest.mark.parametrize(
    "InsufficientCreditsError",
    [
        InsufficientCreditsError,
        _ForeignBillingError,
    ],
    ids=["personal", "foreign"],
)
def test_newapi_image_call_reraises_insufficient_credit(
    monkeypatch, InsufficientCreditsError
):
    from novelvideo.generators import nanobanana_grid

    class FakeUsageMeter:
        async def reserve_current_model_call_credit(self, **_kwargs):
            raise InsufficientCreditsError(user_id="usr_1", cost=5, balance=0)

    monkeypatch.setattr(nanobanana_grid, "get_usage_meter", lambda: FakeUsageMeter())

    with pytest.raises(InsufficientCreditsError):
        run_async(
            nanobanana_grid._call_newapi_image_api(
                api_key="newapi-token",
                model="LingShan-G2",
                prompt="portrait prompt",
                base_url="http://newapi.test/v1",
            )
        )


@pytest.mark.parametrize(
    "InsufficientCreditsError",
    [
        InsufficientCreditsError,
        _ForeignBillingError,
    ],
    ids=["personal", "foreign"],
)
def test_newapi_sketch_grid_reraises_insufficient_credit(
    monkeypatch, tmp_path, InsufficientCreditsError
):
    from novelvideo.generators import nanobanana_grid

    async def fake_call_newapi_image_api(**_kwargs):
        raise InsufficientCreditsError(user_id="usr_1", cost=5, balance=0)

    monkeypatch.setattr(
        nanobanana_grid,
        "_call_newapi_image_api",
        fake_call_newapi_image_api,
    )

    generator = nanobanana_grid.NanoBananaGridGenerator(
        api_key="newapi-token",
        config={
            "provider": "newapi",
            "api_key": "newapi-token",
            "base_url": "http://newapi.test/v1",
            "model": "LingShan-G2",
            "rows": 1,
            "cols": 1,
            "batch_size": 1,
            "total_panels": 1,
            "mode": "1x1",
            "image_size": "1K",
            "openai_sketch_image_quality": "low",
        },
    )

    with pytest.raises(InsufficientCreditsError):
        run_async(
            generator.generate_grid(
                beats=[
                    {
                        "beat_number": 3,
                        "visual_description": "女主站在竹林中回头。",
                        "narration": "她终于察觉身后有人。",
                    }
                ],
                character_map={},
                style="chinese_period_drama",
                output_path=str(tmp_path / "sketch.png"),
                rows=1,
                cols=1,
                sketch=True,
                mode_key="1x1_2-3_sketch",
                location_beat_numbers=[3],
            )
        )


def test_newapi_image_call_omits_quality_for_nanobanana2(monkeypatch):
    import httpx
    from novelvideo.generators import nanobanana_grid

    posted = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(b"image-bytes").decode()}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            posted["json"] = json
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="newapi-token",
            model="LingShan-NB-2",
            prompt="portrait prompt",
            image_config={
                "aspect_ratio": "3:4",
                "image_size": "1K",
                "quality": "medium",
            },
            base_url="http://newapi.test/v1",
        )
    )

    assert image_bytes == b"image-bytes"
    assert error == ""
    assert posted["json"]["model"] == "LingShan-NB-2"
    assert posted["json"]["quality"] == "medium"
    assert posted["json"]["size"] == "768x1024"
    assert posted["json"]["metadata"] == {"ratio": "3:4", "resolution": "1k"}
    assert "extra_fields" not in posted["json"]


def test_newapi_image_call_relays_reference_images(monkeypatch):
    import httpx
    from novelvideo.generators import nanobanana_grid

    posted = {}
    relayed = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(b"image-bytes").decode()}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            posted["url"] = url
            posted["json"] = json
            return FakeResponse()

    def fake_upload_image_bytes(data, *, ext="png", ttl=None, image_transform=None):
        relayed.append((data, ext, ttl, image_transform))
        return f"https://relay.test/{len(relayed)}.png"

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(nanobanana_grid, "upload_image_bytes", fake_upload_image_bytes)

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="newapi-token",
            model="LingShan-G2",
            prompt="identity prompt",
            reference_images=[b"ref-a", b"ref-b"],
            image_config={
                "aspect_ratio": "3:4",
                "image_size": "1K",
                "quality": "medium",
                "output_format": "png",
                "input_fidelity": "high",
            },
            base_url="http://newapi.test/v1",
        )
    )

    assert image_bytes == b"image-bytes"
    assert error == ""
    assert posted["url"] == "http://newapi.test/v1/images/edits"
    assert relayed == [
        (
            b"ref-a",
            "png",
            nanobanana_grid.NEWAPI_MEDIA_INPUT_MIN_TTL_SECONDS,
            nanobanana_grid.IMAGE_TRANSFORM_AI_REFERENCE_JPEG,
        ),
        (
            b"ref-b",
            "png",
            nanobanana_grid.NEWAPI_MEDIA_INPUT_MIN_TTL_SECONDS,
            nanobanana_grid.IMAGE_TRANSFORM_AI_REFERENCE_JPEG,
        ),
    ]
    assert posted["json"]["image"] == [
        "https://relay.test/1.png",
        "https://relay.test/2.png",
    ]
    assert "images" not in posted["json"]
    assert posted["json"]["output_format"] == "png"
    assert posted["json"]["input_fidelity"] == "high"
    assert "extra_fields" not in posted["json"]


@pytest.mark.parametrize("reference_count", [1, 2])
@pytest.mark.parametrize("configure_via_env", [False, True], ids=["config", "env"])
def test_newapi_image_edit_supports_cockpit_reference_format(
    monkeypatch, reference_count, configure_via_env
):
    import json
    import httpx
    from novelvideo.generators import nanobanana_grid

    posted = []
    real_client = httpx.AsyncClient

    def handle_request(request):
        posted.append((request.url.path, json.loads(request.content)))
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(b"edited-image").decode()}]},
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handle_request), **kwargs
        ),
    )
    monkeypatch.setattr(
        nanobanana_grid,
        "upload_image_bytes",
        lambda data, **_kwargs: f"https://relay.test/{data.decode()}.png",
    )
    image_config = {"aspect_ratio": "3:4", "image_size": "1K"}
    if configure_via_env:
        monkeypatch.setenv("NEWAPI_IMAGE_EDIT_REFERENCE_FORMAT", "images")
    else:
        monkeypatch.delenv("NEWAPI_IMAGE_EDIT_REFERENCE_FORMAT", raising=False)
        image_config["reference_image_format"] = "images"

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="test-token",
            model="LingShan-G2",
            prompt="identity prompt",
            reference_images=[f"ref-{i}".encode() for i in range(reference_count)],
            image_config=image_config,
            base_url="http://newapi.test/v1",
        )
    )

    assert image_bytes == b"edited-image"
    assert error == ""
    assert len(posted) == 1
    path, payload = posted[0]
    assert path == "/v1/images/edits"
    expected_images = [{"image_url": "https://relay.test/ref-0.png"}]
    if reference_count == 2:
        expected_images.append({"image_url": "https://relay.test/ref-1.png"})
    assert payload["images"] == expected_images
    assert "image" not in payload
    context = nanobanana_grid._newapi_safe_request_context(
        endpoint="http://newapi.test/v1",
        request_path="/images/edits",
        model="LingShan-G2",
        payload=payload,
        prompt="identity prompt",
    )
    assert context["reference_image_count"] == reference_count
    assert "https://relay.test" not in str(context)


@pytest.mark.parametrize(
    ("reference_format", "expected_key"),
    [("input_reference", "input_reference"), ("images", "images")],
)
def test_newapi_image_edit_supports_json_reference_protocols(
    monkeypatch, reference_format, expected_key
):
    import json
    import httpx
    from novelvideo.generators import nanobanana_grid

    posted = []
    real_client = httpx.AsyncClient

    def handle_request(request):
        posted.append((request.url.path, request.headers.get("content-type"), json.loads(request.content)))
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(b"edited").decode()}]},
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handle_request), **kwargs
        ),
    )
    monkeypatch.setattr(
        nanobanana_grid,
        "upload_image_bytes",
        lambda data, **_kwargs: f"https://relay.test/{data.decode()}.png",
    )

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="test-token",
            model="gpt-image-2.5",
            prompt="edit",
            reference_images=[b"ref-a", b"ref-b"],
            image_config={"reference_image_format": reference_format},
            base_url="https://gateway.test/v1",
        )
    )

    assert image_bytes == b"edited"
    assert error == ""
    assert len(posted) == 1
    path, content_type, payload = posted[0]
    assert path == "/v1/images/edits"
    assert content_type == "application/json"
    assert payload[expected_key] == [
        {"image_url": "https://relay.test/ref-a.png"},
        {"image_url": "https://relay.test/ref-b.png"},
    ]


def test_newapi_image_reference_request_uses_catalog_endpoint(monkeypatch):
    """A catalog can route reference-image requests through generations."""
    import json
    import httpx
    from novelvideo.generators import nanobanana_grid

    posted = []
    real_client = httpx.AsyncClient

    def handle_request(request):
        posted.append((request.url.path, json.loads(request.content)))
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(b"generated-image").decode()}]},
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handle_request), **kwargs
        ),
    )
    monkeypatch.setattr(
        nanobanana_grid,
        "upload_image_bytes",
        lambda data, **_kwargs: f"https://relay.test/{data.decode()}.png",
    )

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="test-token",
            model="gpt-image-2",
            prompt="four-panel story",
            reference_images=[b"source"],
            image_config={
                "aspect_ratio": "1:1",
                "image_size": "1K",
                "request_schema": {
                    "endpoint": "images/generations",
                    "referenceFormat": "images",
                    "parameters": [],
                },
            },
            base_url="http://newapi.test/v1",
        )
    )

    assert image_bytes == b"generated-image"
    assert error == ""
    assert posted[0][0] == "/v1/images/generations"
    assert posted[0][1]["images"] == [{"image_url": "https://relay.test/source.png"}]
    assert "image" not in posted[0][1]


def test_newapi_image_edit_supports_multipart_image_files_without_relay(
    monkeypatch,
):
    import httpx
    from novelvideo.generators import nanobanana_grid

    posted = []
    real_client = httpx.AsyncClient

    def handle_request(request):
        posted.append((request.headers.get("content-type"), request.content))
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(b"edited").decode()}]},
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handle_request), **kwargs
        ),
    )
    monkeypatch.setattr(
        nanobanana_grid,
        "upload_image_bytes",
        lambda *_args, **_kwargs: pytest.fail("multipart must not relay uploads"),
    )

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="test-token",
            model="gpt-image-2.5",
            prompt="edit prompt",
            reference_images=[
                ("first.jpg", b"jpeg-bytes", "image/jpeg"),
                ("second.png", b"png-bytes", "image/png"),
            ],
            image_config={
                "reference_image_format": "multipart",
                "quality": "medium",
                "aspect_ratio": "3:4",
                "image_size": "1K",
            },
            base_url="https://gateway.test/v1",
        )
    )

    assert image_bytes == b"edited"
    assert error == ""
    assert len(posted) == 1
    content_type, body = posted[0]
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b'name="image[]"; filename="first.jpg"' in body
    assert b'name="image[]"; filename="second.png"' in body
    assert b'name="prompt"' in body and b"edit prompt" in body
    assert b'name="model"' in body and b"gpt-image-2.5" in body
    assert b'name="size"' in body and b"768x1024" in body
    assert b'name="quality"' in body and b"medium" in body
    assert b'name="n"' in body and b"\r\n\r\n1\r\n" in body
    assert b'name="response_format"' not in body
    assert b'name="metadata"' not in body
    assert b'name="width"' not in body
    assert b'name="height"' not in body
    assert b'name="watermark"' not in body


def test_newapi_image_edit_multipart_uses_singular_image_for_one_reference(monkeypatch):
    import httpx
    from novelvideo.generators import nanobanana_grid

    posted = []
    real_client = httpx.AsyncClient

    def handle_request(request):
        posted.append(request.content)
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(b"edited").decode()}]},
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handle_request), **kwargs
        ),
    )

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="test-token",
            model="gpt-image-2.5",
            prompt="edit prompt",
            reference_images=[("first.jpg", b"jpeg-bytes", "image/jpeg")],
            image_config={
                "aspect_ratio": "3:4",
                "image_size": "1K",
                "reference_image_format": "multipart",
            },
            base_url="https://gateway.test/v1",
        )
    )

    assert image_bytes == b"edited"
    assert error == ""
    assert len(posted) == 1
    assert b'name="image"; filename="first.jpg"' in posted[0]
    assert b'name="image[]"' not in posted[0]


def test_newapi_multipart_reference_schema_routes_to_image_edits(monkeypatch):
    import httpx
    from novelvideo.generators import nanobanana_grid

    posted = []
    real_client = httpx.AsyncClient

    def handle_request(request):
        posted.append((request.url.path, request.content))
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(b"edited").decode()}]},
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handle_request), **kwargs
        ),
    )

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="test-token",
            model="gpt-image-2.5",
            prompt="edit prompt",
            reference_images=[("reference.png", b"png-bytes", "image/png")],
            image_config={
                "reference_image_format": "multipart",
                "request_schema": {
                    "endpoint": "images/generations",
                    "referenceFormat": "multipart",
                    "parameters": [],
                },
            },
            base_url="https://gateway.test/v1",
        )
    )

    assert image_bytes == b"edited"
    assert error == ""
    assert posted[0][0] == "/v1/images/edits"


def test_gemini_image_gateway_uses_native_generate_content_json(monkeypatch):
    import json
    import httpx
    from novelvideo.generators import nanobanana_grid

    posted = []
    real_client = httpx.AsyncClient

    def handle_request(request):
        posted.append((str(request.url), dict(request.headers), json.loads(request.content)))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "done"},
                                {
                                    "inlineData": {
                                        "mimeType": "image/png",
                                        "data": base64.b64encode(b"gemini-image").decode(),
                                    }
                                },
                            ]
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handle_request), **kwargs
        ),
    )

    image_bytes, text, error = run_async(
        nanobanana_grid._call_gemini_image_api(
            api_key="gemini-key",
            model="gemini-2.5-flash-image",
            prompt="make a poster",
            reference_images=[(b"reference", "/tmp/ref.png")],
            image_config={"aspect_ratio": "3:4", "image_size": "2K"},
            base_url="https://gemini.example/v1beta",
        )
    )

    assert image_bytes == b"gemini-image"
    assert text == "done"
    assert error == ""
    assert len(posted) == 1
    url, headers, payload = posted[0]
    assert url == (
        "https://gemini.example/v1beta/models/"
        "gemini-2.5-flash-image:generateContent"
    )
    assert headers["x-goog-api-key"] == "gemini-key"
    assert payload["contents"][0]["parts"][0] == {"text": "make a poster"}
    assert payload["contents"][0]["parts"][1]["inlineData"]["mimeType"] == "image/png"
    assert payload["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]
    assert payload["generationConfig"]["imageConfig"] == {
        "imageSize": "2K",
        "aspectRatio": "3:4",
    }


def test_gemini_text_to_image_uses_native_generate_content(monkeypatch, tmp_path):
    from google import genai
    from novelvideo.generators import nanobanana_grid

    calls = []

    async def fake_native(**kwargs):
        calls.append(kwargs)
        return b"native-gemini-image", "", ""

    monkeypatch.setattr(nanobanana_grid, "_call_gemini_image_api", fake_native)
    monkeypatch.setattr(
        genai,
        "Client",
        lambda **_kwargs: pytest.fail("Gemini text-to-image must use the native gateway helper"),
    )

    output = run_async(
        nanobanana_grid.generate_text_to_image(
            prompt="a test image",
            output_path=str(tmp_path / "gemini-text.png"),
            aspect_ratio="3:4",
            image_size="2K",
            config={
                "provider": "newapi",
                "gateway_protocol": "gemini",
                "gateway_native_base_url": "https://gemini.example/v1beta",
                "api_key": "gemini-key",
                "model": "gemini-3.1-flash-image-preview",
                "rows": 1,
                "cols": 1,
                "total_panels": 1,
                "mode": "1x1",
            },
        )
    )

    assert output.read_bytes() == b"native-gemini-image"
    assert len(calls) == 1
    assert calls[0]["model"] == "gemini-3.1-flash-image-preview"
    assert calls[0]["reference_images"] is None
    assert calls[0]["base_url"] == "https://gemini.example/v1beta"


def test_gemini_native_helper_adds_v1beta_to_gateway_root(monkeypatch):
    import httpx
    from novelvideo.generators import nanobanana_grid

    posted = []
    real_client = httpx.AsyncClient

    def handle_request(request):
        posted.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "image/png",
                                        "data": base64.b64encode(b"image").decode(),
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handle_request), **kwargs
        ),
    )

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_gemini_image_api(
            api_key="gemini-key",
            model="gemini-3.1-flash-image-preview",
            prompt="a test image",
            base_url="https://gemini.example",
        )
    )

    assert image_bytes == b"image"
    assert error == ""
    assert posted == [
        "https://gemini.example/v1beta/models/"
        "gemini-3.1-flash-image-preview:generateContent"
    ]


def test_gemini_grid_generation_uses_native_generate_content(monkeypatch, tmp_path):
    import httpx
    from novelvideo.generators import nanobanana_grid

    real_client = httpx.AsyncClient
    posted = []

    def handle_request(request):
        posted.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "image/png",
                                        "data": base64.b64encode(b"grid-image").decode(),
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handle_request), **kwargs
        ),
    )
    generator = nanobanana_grid.NanoBananaGridGenerator(
        api_key="gemini-key",
        config={
            "provider": "newapi",
            "gateway_protocol": "gemini",
            "gateway_native_base_url": "https://gemini.example/v1beta",
            "api_key": "gemini-key",
            "model": "gemini-2.5-flash-image",
            "rows": 1,
            "cols": 1,
            "batch_size": 1,
            "total_panels": 1,
            "mode": "1x1",
        },
    )

    result = run_async(
        generator.generate_grid(
            beats=[{"beat_number": 1, "visual_description": "a tree", "narration": ""}],
            character_map={},
            style="",
                output_path=str(tmp_path / "gemini-grid.png"),
                rows=1,
                cols=1,
                sketch=True,
                beat_start_index=0,
                total_episode_beats=1,
                sketch_dir=str(tmp_path),
                mode_key="1x1_2-3_sketch",
            )
    )

    assert result.success is True
    assert posted == ["/v1beta/models/gemini-2.5-flash-image:generateContent"]
    assert (tmp_path / "gemini-grid.png").exists()


def test_gemini_grid_request_helper_uses_native_protocol(monkeypatch):
    from novelvideo.generators import nanobanana_grid

    captured = {}

    async def fake_native(**kwargs):
        captured.update(kwargs)
        return b"grid", "", ""

    monkeypatch.setattr(nanobanana_grid, "_call_gemini_image_api", fake_native)
    image_bytes, _text, error = run_async(
        nanobanana_grid._call_gemini_grid_image_api(
            api_key="gemini-key",
            model="gemini-2.5-flash-image",
            prompt="grid prompt",
            reference_images=[(b"ref", "/tmp/reference.jpg")],
            image_size="2K",
            aspect_ratio="3:4",
            base_url="https://gemini.example/v1beta",
        )
    )

    assert image_bytes == b"grid"
    assert error == ""
    assert captured["base_url"] == "https://gemini.example/v1beta"
    assert captured["reference_images"] == [(b"ref", "/tmp/reference.jpg")]


def test_newapi_image_gateway_surfaces_error_body_when_http_response_is_200(
    monkeypatch,
):
    import httpx
    from novelvideo.generators import nanobanana_grid

    real_client = httpx.AsyncClient

    def handle_request(_request):
        return httpx.Response(
            200,
            json={
                "error": {
                    "message": "No available channel for model gpt-image-2",
                    "type": "new_api_error",
                }
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handle_request), **kwargs
        ),
    )

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="test-token",
            model="gpt-image-2",
            prompt="prompt",
            base_url="https://gateway.example/v1",
        )
    )

    assert image_bytes is None
    assert "No available channel for model gpt-image-2" in error
    assert "new_api_error" in error


def test_newapi_image_edit_rejects_unknown_reference_format_before_upload(monkeypatch):
    from novelvideo.generators import nanobanana_grid

    def unexpected_upload(*_args, **_kwargs):
        pytest.fail("invalid format must not upload reference images")

    monkeypatch.setattr(nanobanana_grid, "upload_image_bytes", unexpected_upload)
    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="test-token",
            model="LingShan-G2",
            prompt="identity prompt",
            reference_images=[b"ref"],
            image_config={"reference_image_format": "typo"},
            base_url="http://newapi.test/v1",
        )
    )
    assert image_bytes is None
    assert "reference image format" in error.lower()


def test_newapi_image_call_preserves_reference_image_extensions(monkeypatch):
    import httpx
    from novelvideo.generators import nanobanana_grid

    relayed = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(b"image-bytes").decode()}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            return FakeResponse()

    def fake_upload_image_bytes(data, *, ext="png", ttl=None, image_transform=None):
        relayed.append((data, ext, ttl, image_transform))
        return f"https://relay.test/{len(relayed)}.{ext}"

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(nanobanana_grid, "upload_image_bytes", fake_upload_image_bytes)

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="newapi-token",
            model="LingShan-G2",
            prompt="identity prompt",
            reference_images=[
                ("face.jpg", b"jpg-bytes", "image/jpeg"),
                (b"webp-bytes", "image/webp"),
            ],
            image_config={"aspect_ratio": "3:4", "image_size": "1K", "quality": "medium"},
            base_url="http://newapi.test/v1",
        )
    )

    assert image_bytes == b"image-bytes"
    assert error == ""
    assert relayed == [
        (
            b"jpg-bytes",
            "jpg",
            nanobanana_grid.NEWAPI_MEDIA_INPUT_MIN_TTL_SECONDS,
            nanobanana_grid.IMAGE_TRANSFORM_AI_REFERENCE_JPEG,
        ),
        (
            b"webp-bytes",
            "webp",
            nanobanana_grid.NEWAPI_MEDIA_INPUT_MIN_TTL_SECONDS,
            nanobanana_grid.IMAGE_TRANSFORM_AI_REFERENCE_JPEG,
        ),
    ]


def test_newapi_image_http_error_logs_redacted_request_context(monkeypatch, caplog):
    import httpx
    from novelvideo.generators import nanobanana_grid

    posted = {}
    refunds = []

    class FakeResponse:
        status_code = 400
        text = '{"error":{"message":"openai_error","type":"bad_response_status_code"}}'
        headers = {
            "x-newapi-request-id": "req-123",
            "cf-ray": "cf-ray-456",
            "date": "Fri, 22 May 2026 03:00:00 GMT",
            "authorization": "Bearer should-not-leak",
        }

        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "bad response",
                request=httpx.Request("POST", "http://newapi.test/v1/images/generations"),
                response=self,
            )

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            posted["url"] = url
            posted["headers"] = headers
            posted["json"] = json
            return FakeResponse()

    def fake_upload_image_bytes(data, *, ext="png", ttl=None, image_transform=None):
        return f"https://relay.test/signed-{data.decode()}?token=secret"

    class FakeUsageMeter:
        async def reserve_current_model_call_credit(self, **_kwargs):
            return "reservation_1"

        async def refund_model_call_credit_reservation(self, reservation_id, *, metadata=None):
            refunds.append({"reservation_id": reservation_id, "metadata": metadata or {}})

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(nanobanana_grid, "upload_image_bytes", fake_upload_image_bytes)
    monkeypatch.setattr(nanobanana_grid, "get_usage_meter", lambda: FakeUsageMeter())
    caplog.set_level(logging.WARNING, logger="novelvideo.generators.nanobanana_grid")

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="newapi-token",
            model="LingShan-G2",
            prompt="sensitive prompt body",
            reference_images=[b"ref-a"],
            image_config={"aspect_ratio": "2:1", "image_size": "2K", "quality": "medium"},
            base_url="http://newapi.test/v1",
        )
    )

    log_text = "\n".join(record.getMessage() for record in caplog.records)

    assert image_bytes is None
    assert "request_id=req-123" in error
    assert "cf-ray-456" in error
    assert "model=LingShan-G2" in error
    assert "size=2048x1024" in error
    assert "tier=" in error
    assert "geometry_metadata={'ratio': '2:1', 'resolution': '2k'}" in error
    assert "reference_image_count=1" in error
    assert "request_id=req-123" in log_text
    assert "http://newapi.test/v1/images/edits" in log_text
    assert "prompt_sha256=" in log_text
    assert "sensitive prompt body" not in error
    assert "sensitive prompt body" not in log_text
    assert "newapi-token" not in error
    assert "newapi-token" not in log_text
    assert "token=secret" not in error
    assert "token=secret" not in log_text
    assert refunds == [
        {
            "reservation_id": "reservation_1",
            "metadata": {
                "source": "newapi_image_api",
                "error": "HTTP 400",
                "request_id": "req-123",
                "http_status": 400,
                "response_headers": {
                    "x-newapi-request-id": "req-123",
                    "cf-ray": "cf-ray-456",
                    "date": "Fri, 22 May 2026 03:00:00 GMT",
                },
            },
        }
    ]


def test_newapi_image_http_5xx_does_not_retry_in_app(monkeypatch):
    import httpx
    from novelvideo.generators import nanobanana_grid

    attempts = 0

    class FailingResponse:
        status_code = 502
        text = '{"error":{"message":"error","type":"bad_response"}}'
        headers = {"x-oneapi-request-id": "req-fail"}

        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "bad gateway",
                request=httpx.Request("POST", "http://newapi.test/v1/images/generations"),
                response=self,
            )

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            nonlocal attempts
            attempts += 1
            return FailingResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    image_bytes, _text, error = run_async(
        nanobanana_grid._call_newapi_image_api(
            api_key="newapi-token",
            model="LingShan-G2",
            prompt="retry prompt",
            image_config={"aspect_ratio": "2:1", "image_size": "2K", "quality": "medium"},
            base_url="http://newapi.test/v1",
        )
    )

    assert image_bytes is None
    assert "HTTP 502" in error
    assert "request_id=req-fail" in error
    assert attempts == 1


def test_newapi_identity_image_sends_portrait_then_costume_references(
    monkeypatch,
    tmp_path,
):
    from novelvideo.generators import nanobanana_character

    captured = {}

    async def fake_call_newapi_image_api(**kwargs):
        captured.update(kwargs)
        return b"identity-image", "", ""

    monkeypatch.setattr(
        nanobanana_character,
        "_call_newapi_image_api",
        fake_call_newapi_image_api,
    )

    generator = nanobanana_character.NanoBananaCharacterGenerator(
        config={
            "provider": "newapi",
            "api_key": "newapi-token",
            "model": "LingShan-NB-2",
            "base_url": "http://newapi.test/v1",
        }
    )
    output_path = tmp_path / "identity_body_temp.png"

    image_bytes = run_async(
        generator._generate_with_reference(
            client=None,
            prompt="identity prompt",
            reference_image=None,
            output_path=str(output_path),
            reference_image_bytes=b"portrait-bytes",
            reference_image_name="/project/characters/李雷/reference_portrait.jpg",
            aspect_ratio="16:9",
            image_size="1K",
            additional_image_bytes=[b"costume-bytes"],
            additional_image_names=["/project/characters/李雷/学生_costume.png"],
        )
    )

    assert image_bytes == b"identity-image"
    assert output_path.read_bytes() == b"identity-image"
    assert captured["model"] == "LingShan-NB-2"
    assert captured["base_url"] == "http://newapi.test/v1"
    assert captured["image_config"] == {
        "aspect_ratio": "16:9",
        "image_size": "1K",
        "quality": "medium",
    }
    assert captured["reference_images"] == [
        ("reference_portrait.jpg", b"portrait-bytes", "image/jpeg"),
        ("学生_costume.png", b"costume-bytes", "image/png"),
    ]


def test_newapi_identity_image_passes_shared_canvas_request_metadata(
    monkeypatch, tmp_path
):
    from novelvideo import model_gateway_settings
    from novelvideo.generators import nanobanana_character

    captured = {}

    async def fake_call_newapi_image_api(**kwargs):
        captured.update(kwargs)
        return b"identity-shared-schema", "", ""

    monkeypatch.setattr(nanobanana_character, "_call_newapi_image_api", fake_call_newapi_image_api)
    monkeypatch.setattr(
        model_gateway_settings,
        "resolve_third_party_image_request",
        lambda _model: {
            "request_schema": {
                "endpoint": "images/generations",
                "referenceFormat": "images",
                "parameters": [],
            },
            "model_params": {"quality": "high"},
            "reference_image_format": "images",
            "upstream_model": "configured-image-model",
        },
    )
    generator = nanobanana_character.NanoBananaCharacterGenerator(
        config={
            "provider": "newapi",
            "api_key": "newapi-token",
            "model": "gpt-image-2",
            "base_url": "http://newapi.test/v1",
        }
    )

    output_path = tmp_path / "identity.png"
    result = run_async(
        generator._generate_with_reference(
            client=None,
            prompt="identity prompt",
            reference_image=None,
            output_path=str(output_path),
            reference_image_bytes=b"portrait-bytes",
            reference_image_name="portrait.jpg",
            aspect_ratio="16:9",
            image_size="1K",
            additional_image_bytes=[b"costume-bytes"],
            additional_image_names=["costume.png"],
        )
    )

    assert result == b"identity-shared-schema"
    assert captured["image_config"]["reference_image_format"] == "images"
    assert captured["image_config"]["model_params"] == {"quality": "high"}


@pytest.mark.parametrize(
    "InsufficientCreditsError",
    [
        InsufficientCreditsError,
        _ForeignBillingError,
    ],
    ids=["personal", "foreign"],
)
def test_newapi_character_portrait_reraises_insufficient_credit(
    monkeypatch, tmp_path, InsufficientCreditsError
):
    from novelvideo.generators import nanobanana_character

    async def fake_call_newapi_image_api(**_kwargs):
        raise InsufficientCreditsError(user_id="usr_1", cost=5, balance=0)

    monkeypatch.setattr(
        nanobanana_character,
        "_call_newapi_image_api",
        fake_call_newapi_image_api,
    )

    generator = nanobanana_character.NanoBananaCharacterGenerator(
        config={
            "provider": "newapi",
            "api_key": "newapi-token",
            "model": "LingShan-G2",
            "base_url": "http://newapi.test/v1",
        }
    )

    with pytest.raises(InsufficientCreditsError):
        run_async(
            generator.generate_character_portrait(
                character_name="李雷",
                character_prompt="young man",
                output_dir=str(tmp_path),
            )
        )


def test_newapi_character_portrait_raise_on_error_preserves_provider_detail(monkeypatch, tmp_path):
    import novelvideo.config as config
    from novelvideo.generators import image_generator, nanobanana_character

    async def fake_call_newapi_image_api(**_kwargs):
        return None, "", "HTTP 504: request_id=req-123; body=provider timeout"

    monkeypatch.setenv("NEWAPI_API_KEY", "newapi-token")
    monkeypatch.setenv("NEWAPI_BASE_URL", "http://newapi.test/v1")
    monkeypatch.setenv("NEWAPI_IMAGE_MODEL", "LingShan-G2")
    monkeypatch.setenv("DEFAULT_CHARACTER_IMAGE_SELECTION", "gpt-image-2")
    importlib.reload(config)
    monkeypatch.setattr(
        nanobanana_character,
        "_call_newapi_image_api",
        fake_call_newapi_image_api,
    )

    with pytest.raises(RuntimeError, match="HTTP 504: request_id=req-123"):
        run_async(
            image_generator.generate_character_reference_unified(
                character_name="李雷",
                appearance_prompt="young man",
                output_dir=str(tmp_path),
                count=1,
                model="gpt-image-2",
                raise_on_error=True,
            )
        )


def test_newapi_scene_master_uses_text_only_nanobanana2(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    from novelvideo.generators import scene_reference_images
    from novelvideo.models import NovelScene

    captured = {}

    async def fake_call_newapi_image_api(**kwargs):
        captured.update(kwargs)
        return b"scene-master", "", ""

    monkeypatch.setenv("NEWAPI_API_KEY", "newapi-token")
    monkeypatch.setenv("NEWAPI_BASE_URL", "http://newapi.test/v1")
    monkeypatch.setenv("SCENE_MASTER_IMAGE_PROVIDER", "newapi")
    monkeypatch.setenv("SCENE_MASTER_IMAGE_MODEL", "LingShan-NB-2")
    _patch_scene_newapi_gateway(monkeypatch)
    monkeypatch.setattr(
        scene_reference_images,
        "_call_newapi_image_api",
        fake_call_newapi_image_api,
    )
    monkeypatch.setattr(scene_reference_images, "SCENE_MASTER_IMAGE_PROVIDER", "newapi")
    monkeypatch.setattr(scene_reference_images, "SCENE_MASTER_IMAGE_MODEL", "LingShan-NB-2")

    scene = NovelScene(
        name="古董店",
        scene_type="interior",
        environment_prompt="从店门可以直接看到收银台，周围堆放着一些古董",
    )

    output_path = run_async(
        scene_reference_images.generate_scene_reference_image(
            project_dir=tmp_path,
            scene=scene,
            kind="master",
            style_name="live_action",
            style_prompt="grounded realism",
            avoid_instructions="no people",
        )
    )

    assert output_path == tmp_path / "assets" / "scenes" / "古董店" / "master.png"
    assert output_path.read_bytes() == b"scene-master"
    assert captured["api_key"] == "newapi-token"
    assert captured["base_url"] == "http://newapi.test/v1"
    assert captured["model"] == "LingShan-NB-2"
    assert captured["reference_images"] is None
    assert captured["image_config"] == {
        "aspect_ratio": "16:9",
        "image_size": "1K",
        "output_format": "png",
    }
    assert "SCENE NAME: 古董店" in captured["prompt"]
    assert "从店门可以直接看到收银台" in captured["prompt"]


def test_scene_reference_passes_shared_canvas_request_metadata(monkeypatch, tmp_path):
    from novelvideo import model_gateway_settings
    from novelvideo.generators import scene_reference_images
    from novelvideo.models import NovelScene

    captured = {}

    async def fake_call_newapi_image_api(**kwargs):
        captured.update(kwargs)
        return b"scene-shared-schema", "", ""

    monkeypatch.setattr(scene_reference_images, "_call_newapi_image_api", fake_call_newapi_image_api)
    monkeypatch.setattr(
        model_gateway_settings,
        "resolve_third_party_image_request",
        lambda _model: {
            "request_schema": {
                "endpoint": "images/generations",
                "referenceFormat": "images",
                "parameters": [],
            },
            "model_params": {"quality": "high"},
            "reference_image_format": "images",
            "upstream_model": "configured-image-model",
        },
    )
    _patch_scene_newapi_gateway(monkeypatch)
    monkeypatch.setattr(scene_reference_images, "SCENE_MASTER_IMAGE_PROVIDER", "newapi")
    monkeypatch.setattr(scene_reference_images, "SCENE_MASTER_IMAGE_MODEL", "gpt-image-2")

    output = run_async(
        scene_reference_images.generate_scene_reference_image(
            project_dir=tmp_path,
            scene=NovelScene(name="共享场景", scene_type="interior", environment_prompt="室内"),
            kind="master",
        )
    )

    assert output.read_bytes() == b"scene-shared-schema"
    assert captured["image_config"]["reference_image_format"] == "images"
    assert captured["image_config"]["request_schema"]["endpoint"] == "images/generations"
    assert captured["image_config"]["model_params"] == {"quality": "high"}


@pytest.mark.asyncio
async def test_newapi_scene_reference_accepts_copied_file_without_image_bytes(
    monkeypatch, tmp_path
):
    from pathlib import Path

    from novelvideo.generators import scene_reference_images
    from novelvideo.models import NovelScene

    async def copied_image(**kwargs):
        assert kwargs["read_copied_bytes"] is False
        Path(kwargs["delivery_path"]).write_bytes(b"copied-scene")
        kwargs["delivery_state"]["copied"] = True
        return None, "", ""

    _patch_scene_newapi_gateway(monkeypatch)
    monkeypatch.setattr(scene_reference_images, "SCENE_MASTER_IMAGE_PROVIDER", "newapi")
    monkeypatch.setattr(scene_reference_images, "SCENE_MASTER_IMAGE_MODEL", "LingShan-NB-2")
    monkeypatch.setattr(scene_reference_images, "_call_newapi_image_api", copied_image)
    scene = NovelScene(name="古董店", scene_type="interior", environment_prompt="古董店室内")

    output = await scene_reference_images.generate_scene_reference_image(
        project_dir=tmp_path,
        scene=scene,
        kind="master",
    )
    assert output.read_bytes() == b"copied-scene"


def test_newapi_scene_time_plate_master_injects_time_and_base_reference(monkeypatch, tmp_path):
    from novelvideo.generators import scene_reference_images
    from novelvideo.models import NovelScene

    captured = {}

    async def fake_call_newapi_image_api(**kwargs):
        captured.update(kwargs)
        return b"scene-night-master", "", ""

    base_master_path = tmp_path / "assets" / "scenes" / "古董店" / "master.png"
    base_master_path.parent.mkdir(parents=True)
    base_master_path.write_bytes(b"base-master-bytes")

    monkeypatch.setattr(
        scene_reference_images,
        "_call_newapi_image_api",
        fake_call_newapi_image_api,
    )
    _patch_scene_newapi_gateway(monkeypatch)
    monkeypatch.setattr(scene_reference_images, "SCENE_MASTER_IMAGE_PROVIDER", "newapi")
    monkeypatch.setattr(scene_reference_images, "SCENE_MASTER_IMAGE_MODEL", "LingShan-NB-2")

    scene = NovelScene(
        name="古董店_夜晚",
        base_scene_id="古董店",
        time_of_day="夜晚",
        scene_type="interior",
        environment_prompt="正面：收银台与古董柜\n光源：中性基础光",
    )

    output_path = run_async(
        scene_reference_images.generate_scene_reference_image(
            project_dir=tmp_path,
            scene=scene,
            kind="master",
        )
    )

    assert output_path == tmp_path / "assets" / "scenes" / "古董店_夜晚" / "master.png"
    assert output_path.read_bytes() == b"scene-night-master"
    assert captured["reference_images"] == [
        ("base_scene_master_master.png", b"base-master-bytes", "image/png")
    ]
    assert "TARGET TIME-OF-DAY PLATE: 夜晚" in captured["prompt"]
    assert "overall lighting must read as 夜晚" in captured["prompt"]
    assert "Keep the same architecture" in captured["prompt"]


def test_newapi_scene_variant_plate_master_keeps_described_lighting(monkeypatch, tmp_path):
    from novelvideo.generators import scene_reference_images
    from novelvideo.models import NovelScene

    captured = {}

    async def fake_call_newapi_image_api(**kwargs):
        captured.update(kwargs)
        return b"scene-variant-master", "", ""

    base_master_path = tmp_path / "assets" / "scenes" / "城市街道" / "master.png"
    base_master_path.parent.mkdir(parents=True)
    base_master_path.write_bytes(b"base-master-bytes")

    monkeypatch.setattr(
        scene_reference_images,
        "_call_newapi_image_api",
        fake_call_newapi_image_api,
    )
    _patch_scene_newapi_gateway(monkeypatch)
    monkeypatch.setattr(scene_reference_images, "SCENE_MASTER_IMAGE_PROVIDER", "newapi")
    monkeypatch.setattr(scene_reference_images, "SCENE_MASTER_IMAGE_MODEL", "LingShan-NB-2")

    scene = NovelScene(
        name="城市街道_雨夜版",
        base_scene_id="城市街道",
        variant_id="雨夜版",
        scene_type="exterior",
        environment_prompt="正面：湿漉沥青马路\n光源：路灯昏暗，积水反光，雨夜氛围",
    )

    output_path = run_async(
        scene_reference_images.generate_scene_reference_image(
            project_dir=tmp_path,
            scene=scene,
            kind="master",
        )
    )

    assert output_path == tmp_path / "assets" / "scenes" / "城市街道_雨夜版" / "master.png"
    assert captured["reference_images"] == [
        ("base_scene_master_master.png", b"base-master-bytes", "image/png")
    ]
    assert "STRUCTURED VARIANT PLATE" in captured["prompt"]
    assert "variant_id=雨夜版" in captured["prompt"]
    assert "do NOT neutralize" in captured["prompt"]
    # The base-scene neutralizer must not fire for variant plates.
    assert "IGNORE mood/time-of-day phrases" not in captured["prompt"]


def test_newapi_reverse_master_uses_master_reference_nanobanana2(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    from novelvideo.generators import scene_reference_images
    from novelvideo.models import NovelScene

    captured = {}

    async def fake_call_newapi_image_api(**kwargs):
        captured.update(kwargs)
        return b"scene-reverse", "", ""

    master_path = tmp_path / "assets" / "scenes" / "古董店" / "master.png"
    master_path.parent.mkdir(parents=True)
    master_path.write_bytes(b"master-bytes")

    monkeypatch.setattr(
        scene_reference_images,
        "_call_newapi_image_api",
        fake_call_newapi_image_api,
    )
    _patch_scene_newapi_gateway(monkeypatch)
    monkeypatch.setattr(scene_reference_images, "SCENE_REVERSE_MASTER_IMAGE_PROVIDER", "newapi")
    monkeypatch.setattr(
        scene_reference_images,
        "SCENE_REVERSE_MASTER_IMAGE_MODEL",
        "LingShan-NB-2",
    )

    scene = NovelScene(
        name="古董店",
        scene_type="interior",
        environment_prompt="从店门可以直接看到收银台，周围堆放着一些古董",
    )

    output_path = run_async(
        scene_reference_images.generate_scene_reference_image(
            project_dir=tmp_path,
            scene=scene,
            kind="reverse_master",
            style_name="live_action",
            style_prompt="grounded realism",
            avoid_instructions="no people",
        )
    )

    assert output_path == tmp_path / "assets" / "scenes" / "古董店" / "reverse_master.png"
    assert output_path.read_bytes() == b"scene-reverse"
    assert captured["api_key"] == "newapi-token"
    assert captured["base_url"] == "http://newapi.test/v1"
    assert captured["model"] == "LingShan-NB-2"
    assert captured["reference_images"] == [
        ("scene_master_master.png", b"master-bytes", "image/png")
    ]
    assert captured["image_config"] == {
        "aspect_ratio": "16:9",
        "image_size": "1K",
        "output_format": "png",
    }
    assert "REFERENCE 1 = the scene's FRONT-FACING master" in captured["prompt"]


def test_newapi_reverse_master_can_use_gpt_image2_quality_medium(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    from novelvideo.generators import scene_reference_images
    from novelvideo.models import NovelScene

    captured = {}

    async def fake_call_newapi_image_api(**kwargs):
        captured.update(kwargs)
        return b"scene-reverse", "", ""

    master_path = tmp_path / "assets" / "scenes" / "古董店" / "master.png"
    master_path.parent.mkdir(parents=True)
    master_path.write_bytes(b"master-bytes")

    monkeypatch.setattr(
        scene_reference_images,
        "_call_newapi_image_api",
        fake_call_newapi_image_api,
    )
    _patch_scene_newapi_gateway(monkeypatch)
    monkeypatch.setattr(scene_reference_images, "SCENE_REVERSE_MASTER_IMAGE_PROVIDER", "newapi")
    monkeypatch.setattr(
        scene_reference_images,
        "SCENE_REVERSE_MASTER_IMAGE_MODEL",
        "LingShan-G2",
    )

    scene = NovelScene(
        name="古董店",
        scene_type="interior",
        environment_prompt="从店门可以直接看到收银台，周围堆放着一些古董",
    )

    run_async(
        scene_reference_images.generate_scene_reference_image(
            project_dir=tmp_path,
            scene=scene,
            kind="reverse_master",
        )
    )

    assert captured["model"] == "LingShan-G2"
    assert captured["reference_images"] == [
        ("scene_master_master.png", b"master-bytes", "image/png")
    ]
    assert captured["image_config"] == {
        "aspect_ratio": "16:9",
        "image_size": "1K",
        "output_format": "png",
        "quality": "medium",
    }


def test_newapi_prop_reference_gpt_image2_sends_quality_medium(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    import httpx
    import novelvideo.config as config
    from novelvideo.generators import nanobanana_prop

    posted = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(b"prop-ref").decode()}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            posted["url"] = url
            posted["headers"] = headers
            posted["json"] = json
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setenv("NEWAPI_API_KEY", "newapi-token")
    monkeypatch.setenv("NEWAPI_BASE_URL", "http://newapi.test/v1")
    monkeypatch.setenv("PROP_REF_IMAGE_PROVIDER", "newapi")
    monkeypatch.setenv("PROP_REF_IMAGE_MODEL", "LingShan-G2")
    importlib.reload(config)
    nanobanana_prop = importlib.reload(nanobanana_prop)
    monkeypatch.setattr(
        nanobanana_prop,
        "get_grid_generation_config",
        lambda: {"openai_image_quality": "medium"},
    )

    output_path = tmp_path / "assets" / "props" / "玉佩" / "reference_3view.png"
    result = run_async(
        nanobanana_prop.generate_prop_reference(
            visual_prompt="青绿色玉佩，边缘有金色纹路",
            output_path=str(output_path),
        )
    )

    assert result == str(output_path)
    assert output_path.read_bytes() == b"prop-ref"
    assert posted["url"] == "http://newapi.test/v1/images/generations"
    assert posted["headers"]["Authorization"] == "Bearer newapi-token"
    assert posted["json"]["model"] == "LingShan-G2"
    assert posted["json"]["quality"] == "medium"
    assert posted["json"]["size"] == "1088x608"
    assert posted["json"]["metadata"] == {"ratio": "16:9", "resolution": "1k"}
    assert "extra_fields" not in posted["json"]


def test_newapi_prop_reference_passes_shared_canvas_request_metadata(monkeypatch, tmp_path):
    from novelvideo import model_gateway_settings
    from novelvideo.generators import nanobanana_prop

    captured = {}

    async def fake_call_newapi_image_api(**kwargs):
        captured.update(kwargs)
        return b"prop-shared-schema", "", ""

    monkeypatch.setattr(nanobanana_prop, "_call_newapi_image_api", fake_call_newapi_image_api)
    monkeypatch.setattr(
        model_gateway_settings,
        "resolve_third_party_image_request",
        lambda _model: {
            "request_schema": {
                "endpoint": "images/generations",
                "referenceFormat": "images",
                "parameters": [],
            },
            "model_params": {"quality": "high"},
            "reference_image_format": "images",
            "upstream_model": "configured-image-model",
        },
    )

    output = run_async(
        nanobanana_prop._generate_via_newapi(
            prompt="prop",
            output_path=str(tmp_path / "prop.png"),
            api_key="test-token",
            model="gpt-image-2",
            base_url="https://gateway.test/v1",
        )
    )

    assert output == str(tmp_path / "prop.png")
    assert captured["image_config"]["reference_image_format"] == "images"
    assert captured["image_config"]["model_params"] == {"quality": "high"}


def test_newapi_prop_reference_nanobanana2_omits_quality(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    import httpx
    import novelvideo.config as config
    from novelvideo.generators import nanobanana_prop

    posted = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(b"prop-ref").decode()}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            posted["json"] = json
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setenv("NEWAPI_API_KEY", "newapi-token")
    monkeypatch.setenv("NEWAPI_BASE_URL", "http://newapi.test/v1")
    monkeypatch.setenv("PROP_REF_IMAGE_PROVIDER", "newapi")
    monkeypatch.setenv("PROP_REF_IMAGE_MODEL", "LingShan-NB-2")
    importlib.reload(config)
    nanobanana_prop = importlib.reload(nanobanana_prop)
    monkeypatch.setattr(
        nanobanana_prop,
        "get_grid_generation_config",
        lambda: {"openai_image_quality": "medium"},
    )

    output_path = tmp_path / "assets" / "props" / "玉佩" / "reference_3view.png"
    result = run_async(
        nanobanana_prop.generate_prop_reference(
            visual_prompt="青绿色玉佩，边缘有金色纹路",
            output_path=str(output_path),
        )
    )

    assert result == str(output_path)
    assert output_path.read_bytes() == b"prop-ref"
    assert posted["json"]["model"] == "LingShan-NB-2"
    assert posted["json"]["quality"] == "medium"
    assert posted["json"]["size"] == "1088x608"
    assert posted["json"]["metadata"] == {"ratio": "16:9", "resolution": "1k"}
    assert "extra_fields" not in posted["json"]


@pytest.mark.parametrize(
    "InsufficientCreditsError",
    [
        InsufficientCreditsError,
        _ForeignBillingError,
    ],
    ids=["personal", "foreign"],
)
def test_newapi_prop_reference_reraises_insufficient_credit(
    monkeypatch, tmp_path, InsufficientCreditsError
):
    _isolate_settings_db(monkeypatch, tmp_path)
    import novelvideo.config as config
    from novelvideo.generators import nanobanana_prop

    async def fake_call_newapi_image_api(**_kwargs):
        raise InsufficientCreditsError(user_id="usr_1", cost=5, balance=0)

    monkeypatch.setenv("NEWAPI_API_KEY", "newapi-token")
    monkeypatch.setenv("NEWAPI_BASE_URL", "http://newapi.test/v1")
    monkeypatch.setenv("PROP_REF_IMAGE_PROVIDER", "newapi")
    monkeypatch.setenv("PROP_REF_IMAGE_MODEL", "LingShan-G2")
    importlib.reload(config)
    nanobanana_prop = importlib.reload(nanobanana_prop)
    monkeypatch.setattr(nanobanana_prop, "_call_newapi_image_api", fake_call_newapi_image_api)
    monkeypatch.setattr(
        nanobanana_prop,
        "get_grid_generation_config",
        lambda: {"openai_image_quality": "medium"},
    )

    with pytest.raises(InsufficientCreditsError):
        run_async(
            nanobanana_prop.generate_prop_reference(
                visual_prompt="青绿色玉佩，边缘有金色纹路",
                output_path=str(tmp_path / "reference_3view.png"),
            )
        )


def test_freezone_single_image_generation_routes_newapi(monkeypatch, tmp_path):
    from novelvideo.generators import nanobanana_grid

    captured = {}

    async def fake_call_newapi_image_api(**kwargs):
        captured.update(kwargs)
        return b"freezone-image", "", ""

    monkeypatch.setattr(
        nanobanana_grid, "_call_newapi_image_api", fake_call_newapi_image_api
    )

    output_path = tmp_path / "freezone.png"
    image_path = run_async(
        nanobanana_grid.generate_text_to_image(
            prompt="freezone prompt",
            output_path=str(output_path),
            aspect_ratio="1:1",
            image_size="2K",
            quality="medium",
            config={
                "provider": "newapi",
                "api_key": "newapi-token",
                "model": "LingShan-G2",
                "base_url": "http://newapi.test/v1",
                "openai_image_quality": "medium",
                "openai_sketch_image_quality": "low",
                "image_size": "2K",
                "mode": "1x1",
                "rows": 1,
                "cols": 1,
                "total_panels": 1,
            },
        )
    )

    assert image_path == output_path
    assert output_path.read_bytes() == b"freezone-image"
    assert captured["api_key"] == "newapi-token"
    assert captured["model"] == "LingShan-G2"
    assert captured["prompt"] == "freezone prompt"
    assert captured["reference_images"] is None
    assert captured["base_url"] == "http://newapi.test/v1"
    assert captured["image_config"] == {
        "aspect_ratio": "1:1",
        "image_size": "2K",
        "quality": "medium",
    "request_schema": {},
        "model_params": {},
    }


def run_async(coro):
    import asyncio

    return asyncio.run(coro)
