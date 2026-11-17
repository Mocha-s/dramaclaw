"""Owner-scoped project ports for authenticated AIGCDO users."""

from __future__ import annotations

import re

from fastapi import HTTPException

from novelvideo.aigcdo_sessions import AigcdoSessionStore
from novelvideo.ports.local.project import SQLiteProjectRegistry
from novelvideo.ports.project import Principal, ProjectRecord


class AigcdoProjectRegistry(SQLiteProjectRegistry):
    def __init__(self, identities: AigcdoSessionStore) -> None:
        super().__init__()
        self.identities = identities

    async def resolve_username_by_user_id(self, user_id: str) -> str | None:
        identity = await self.identities.get_identity(user_id)
        return identity.username if identity else None

    async def resolve_user_id_by_username(self, username: str) -> str | None:
        return await self.identities.get_user_id(username)

    async def create_project(
        self, *, owner_user_id: str, owner_username: str, name: str,
        display_name: str | None = None, home_node_id: str | None = None,
        output_dir: str | None = None, state_dir: str | None = None,
        runtime_dir: str | None = None,
    ) -> ProjectRecord:
        canonical = await self.resolve_username_by_user_id(owner_user_id)
        if canonical is None or canonical != owner_username:
            raise ValueError("project owner is not a registered active user")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_]{0,63}", name):
            raise ValueError("invalid project name")
        if any(value is not None for value in (output_dir, state_dir, runtime_dir)):
            raise ValueError("new projects must use their owner's storage paths")
        if home_node_id not in {None, "local"}:
            raise ValueError("project registry supports only this node")
        return await super().create_project(
            owner_user_id=owner_user_id, owner_username=canonical,
            name=name, display_name=display_name,
        )


class AigcdoProjectAccess:
    def __init__(self, registry: AigcdoProjectRegistry) -> None:
        self.registry = registry

    async def resolve_requester_principals(self, user_id: str) -> list[Principal]:
        if await self.registry.identities.get_identity(user_id) is None:
            return []
        return [Principal("user", user_id)]

    async def require_task_submission(self, ctx) -> None:
        project = await self.registry.get_project(ctx.project_id)
        if project is None or project.status != "active" or project.purged_at:
            raise HTTPException(409, "Project must be active before starting tasks")
        principals = await self.resolve_requester_principals(ctx.requester_user_id)
        if await self.effective_project_role(project, principals) != "owner":
            raise HTTPException(403, "Project task access denied")

    async def effective_project_role(
        self, project: ProjectRecord, principals: list[Principal],
    ) -> str | None:
        if project.owner_type != "user" or project.purged_at:
            return None
        if Principal("user", project.owner_id) not in principals:
            return None
        if await self.registry.identities.get_identity(project.owner_id) is None:
            return None
        return "owner"

    async def effective_project_role_by_id(
        self, project_id: str, principals: list[Principal],
    ) -> str | None:
        project = await self.registry.get_project(project_id)
        if project is None:
            return None
        return await self.effective_project_role(project, principals)

    async def count_project_task_eligible_users(
        self, *, project_id: str, owner_type: str, owner_id: str,
    ) -> int:
        if owner_type != "user":
            return 0
        project = await self.registry.get_project(project_id)
        if project is None or project.status != "active":
            return 0
        role = await self.effective_project_role(project, [Principal("user", owner_id)])
        return int(role == "owner")
