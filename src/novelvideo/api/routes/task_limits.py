"""Authenticated CE runtime controls for task lane limits."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from novelvideo.api.auth import get_api_user
from novelvideo.runtime_settings import read_runtime_json, write_runtime_json
from novelvideo.task_backend.limits import (
    GLOBAL_LANE_CONCURRENCY_DEFAULTS,
    GLOBAL_LANE_QUEUE_LIMIT_DEFAULTS,
    PROJECT_LANE_LIMIT_DEFAULTS,
    PROJECT_USER_LANE_LIMIT_DEFAULTS,
    TASK_LIMITS_RUNTIME_KEY,
)
from novelvideo.task_backend.queues import QUEUE_KINDS

router = APIRouter()


class TaskLaneLimit(BaseModel):
    globalConcurrency: int = Field(ge=1, le=32)
    globalQueueLimit: int = Field(ge=1, le=4096)
    projectActiveLimit: int = Field(ge=1, le=256)
    projectUserActiveLimit: int = Field(ge=1, le=256)


class TaskLimitsConfig(BaseModel):
    lanes: dict[str, TaskLaneLimit]

    @model_validator(mode="after")
    def validate_lanes(self) -> "TaskLimitsConfig":
        if set(self.lanes) != set(QUEUE_KINDS):
            raise ValueError("lanes must contain default, video, world, and ffmpeg")
        return self


def _require_ce_task_limits_admin() -> None:
    from novelvideo.api.routes.model_gateway import require_ce_gateway_settings_management

    try:
        require_ce_gateway_settings_management()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None


def _defaults() -> dict[str, Any]:
    return {
        "lanes": {
            lane: {
                "globalConcurrency": GLOBAL_LANE_CONCURRENCY_DEFAULTS[lane],
                "globalQueueLimit": GLOBAL_LANE_QUEUE_LIMIT_DEFAULTS[lane],
                "projectActiveLimit": PROJECT_LANE_LIMIT_DEFAULTS[lane],
                "projectUserActiveLimit": PROJECT_USER_LANE_LIMIT_DEFAULTS[lane],
            }
            for lane in sorted(QUEUE_KINDS)
        }
    }


def _current() -> dict[str, Any]:
    saved = read_runtime_json(TASK_LIMITS_RUNTIME_KEY, {})
    defaults = _defaults()
    if not isinstance(saved, dict):
        return defaults
    merged = {"lanes": {**defaults["lanes"]}}
    for lane, values in (saved.get("lanes") or {}).items():
        if lane in merged["lanes"] and isinstance(values, dict):
            merged["lanes"][lane] = {**merged["lanes"][lane], **values}
    return TaskLimitsConfig.model_validate(merged).model_dump()


@router.get("/config/task-limits")
async def get_task_limits(_user: dict = Depends(get_api_user)) -> dict[str, Any]:
    _require_ce_task_limits_admin()
    return {"ok": True, "data": _current(), "defaults": _defaults()}


@router.put("/config/task-limits")
async def save_task_limits(
    body: TaskLimitsConfig,
    _user: dict = Depends(get_api_user),
) -> dict[str, Any]:
    _require_ce_task_limits_admin()
    value = body.model_dump()
    write_runtime_json(TASK_LIMITS_RUNTIME_KEY, value)
    from novelvideo.ports import get_task_backend
    try:
        backend = get_task_backend()
    except Exception as exc:
        if exc.__class__.__name__ != "PortNotRegistered":
            raise
    else:
        reload_limits = getattr(backend, "reload_limits", None)
        if callable(reload_limits):
            reload_limits()
    return {"ok": True, "data": value, "effective": _current()}
