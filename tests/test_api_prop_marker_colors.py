import pytest

from novelvideo.agents.asset_compiler import AssetCompiler
from novelvideo.models import PropMenuItem


class _Store:
    def __init__(self):
        self.patches: list[dict] = []

    async def patch_episode(self, episode_num: int, **fields):
        self.patches.append({"episode": episode_num, **fields})


@pytest.mark.asyncio
async def test_ensure_global_prop_marker_colors_assigns_and_persists():
    from novelvideo.api.routes.generation import ensure_global_prop_marker_colors

    store = _Store()
    beats = [{"visual_description": "[[寻迹牌]]泛起微光"}]
    prop_menu = [{"prop_id": "寻迹牌", "is_global_asset": True, "marker_color": ""}]

    menu = await ensure_global_prop_marker_colors(store, 1, beats, prop_menu, {})

    assert menu[0]["marker_color"].startswith("#")
    assert store.patches == [{"episode": 1, "prop_menu": menu}]


@pytest.mark.asyncio
async def test_ensure_global_prop_marker_colors_keeps_existing_and_skips_patch():
    from novelvideo.api.routes.generation import ensure_global_prop_marker_colors

    store = _Store()
    beats = [{"visual_description": "[[寻迹牌]]泛起微光"}]
    prop_menu = [{"prop_id": "寻迹牌", "is_global_asset": True, "marker_color": "#0D47A1 ROYAL BLUE"}]

    menu = await ensure_global_prop_marker_colors(store, 1, beats, prop_menu, {})

    assert menu[0]["marker_color"] == "#0D47A1 ROYAL BLUE"
    assert store.patches == []


@pytest.mark.asyncio
async def test_ensure_global_prop_marker_colors_ignores_local_props_and_missing_store_method():
    from novelvideo.api.routes.generation import ensure_global_prop_marker_colors

    beats = [{"visual_description": "[[纸箱]]放在地上"}]
    prop_menu = [{"prop_id": "纸箱", "marker_color": ""}]

    menu = await ensure_global_prop_marker_colors(object(), 1, beats, prop_menu, {})

    assert menu[0]["marker_color"] == ""


def test_carry_over_marker_colors_by_prop_id():
    previous = [PropMenuItem(prop_id="寻迹牌", marker_color="#0D47A1 ROYAL BLUE"), PropMenuItem(prop_id="竹杖", marker_color="#2E7D32 GREEN")]
    fresh = [PropMenuItem(prop_id="寻迹牌"), PropMenuItem(prop_id="包"), PropMenuItem(prop_id="竹杖", marker_color="#111111 KEEP")]

    merged = AssetCompiler._carry_over_marker_colors(fresh, previous)

    assert [item.prop_id for item in merged] == ["寻迹牌", "包", "竹杖"]
    assert merged[0].marker_color == "#0D47A1 ROYAL BLUE"
    assert merged[1].marker_color == ""
    assert merged[2].marker_color == "#111111 KEEP"
