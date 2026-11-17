"""Durable, user-owned model Key provisioning through existing gateway APIs."""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from novelvideo.aigcdo_gateway import AigcdoGatewayError, GatewayAPIKey
from novelvideo.aigcdo_sessions import AigcdoAuthPort

_ERRORS = {
    "group_unavailable": (403, "Application model group is unavailable"),
    "provisioning_pending": (503, "Application Key provisioning needs reconciliation"),
    "application_key_blocked": (403, "Application Key requires explicit reauthorization"),
    "binding_migration_required": (409, "Application Key binding requires migration"),
    "invalid_binding": (503, "Application Key binding is unavailable"),
    "storage_unavailable": (503, "Application Key storage is temporarily unavailable"),
}


class ApplicationKeyError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        self.status_code, message = _ERRORS[code]
        super().__init__(message)


@dataclass(frozen=True)
class _Binding:
    user_id: str
    gateway_id: int
    group_id: int
    name: str
    key: SecretStr = field(repr=False)
    state: str
    key_id: int | None


class AigcdoApplicationKeyStore:
    def __init__(self, path: Path, encryption_key: bytes) -> None:
        self.path = path
        self._fernet = Fernet(encryption_key)

    @asynccontextmanager
    async def _db(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            self.path.chmod(0o600)
            async with aiosqlite.connect(self.path, timeout=10) as db:
                db.row_factory = aiosqlite.Row
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS application_keys (
                        user_id TEXT PRIMARY KEY,
                        gateway_id INTEGER NOT NULL,
                        group_id INTEGER NOT NULL,
                        name TEXT NOT NULL UNIQUE,
                        cipher BLOB NOT NULL,
                        state TEXT NOT NULL,
                        key_id INTEGER
                    )
                """)
                await db.commit()
                yield db
        except (OSError, sqlite3.Error):
            raise ApplicationKeyError("storage_unavailable") from None

    async def prepare(self, user_id: str, gateway_id: int, group_id: int) -> _Binding:
        async with self._db() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT * FROM application_keys WHERE user_id=?", (user_id,))
            row = await cursor.fetchone()
            if row is None:
                name = f"aigcdo-{secrets.token_hex(16)}"
                payload = {
                    "user_id": user_id, "gateway_id": gateway_id, "group_id": group_id,
                    "name": name, "key": f"sk-{secrets.token_hex(32)}",
                }
                cipher = self._fernet.encrypt(json.dumps(payload).encode())
                await db.execute(
                    "INSERT INTO application_keys VALUES (?, ?, ?, ?, ?, 'prepared', NULL)",
                    (user_id, gateway_id, group_id, name, cipher),
                )
                cursor = await db.execute("SELECT * FROM application_keys WHERE user_id=?", (user_id,))
                row = await cursor.fetchone()
            await db.commit()
        try:
            payload = json.loads(self._fernet.decrypt(row["cipher"]))
            if any(payload[key] != row[key] for key in ("user_id", "gateway_id", "group_id", "name")):
                raise ValueError("binding mismatch")
            if not isinstance(payload["key"], str) or not re.fullmatch(r"sk-[0-9a-f]{64}", payload["key"]):
                raise ValueError("invalid Key")
        except (InvalidToken, ValueError, KeyError, TypeError):
            raise ApplicationKeyError("invalid_binding") from None
        if row["gateway_id"] != gateway_id or row["group_id"] != group_id:
            raise ApplicationKeyError("binding_migration_required")
        return _Binding(
            user_id, gateway_id, group_id, row["name"], SecretStr(payload["key"]),
            row["state"], row["key_id"],
        )

    async def claim_creation(self, binding: _Binding) -> bool:
        async with self._db() as db:
            cursor = await db.execute(
                "UPDATE application_keys SET state='uncertain' WHERE user_id=? AND state='prepared'",
                (binding.user_id,),
            )
            await db.commit()
        return cursor.rowcount == 1

    async def release_unsubmitted(self, binding: _Binding) -> None:
        async with self._db() as db:
            await db.execute(
                """UPDATE application_keys SET state='prepared'
                   WHERE user_id=? AND name=? AND state='uncertain' AND key_id IS NULL""",
                (binding.user_id, binding.name),
            )
            await db.commit()

    async def activate(self, binding: _Binding, key_id: int) -> None:
        async with self._db() as db:
            cursor = await db.execute(
                """UPDATE application_keys SET state='active', key_id=?
                   WHERE user_id=? AND state IN ('uncertain', 'active')
                   AND (key_id IS NULL OR key_id=?)""",
                (key_id, binding.user_id, key_id),
            )
            await db.commit()
        if cursor.rowcount != 1:
            raise ApplicationKeyError("application_key_blocked")

    async def block(self, binding: _Binding) -> None:
        async with self._db() as db:
            await db.execute("UPDATE application_keys SET state='blocked' WHERE user_id=?", (binding.user_id,))
            await db.commit()


class AigcdoApplicationKeys:
    def __init__(
        self, auth: AigcdoAuthPort, store: AigcdoApplicationKeyStore, *, group_id: int,
    ) -> None:
        if type(group_id) is not int or group_id <= 0:
            raise ValueError("application group must be a positive integer")
        self.auth = auth
        self.store = store
        self.group_id = group_id

    async def _validate(self, binding: _Binding, key: GatewayAPIKey) -> None:
        if (
            key.user_id != binding.gateway_id or key.group_id != binding.group_id
            or key.name != binding.name or key.status != "active"
            or (binding.key_id is not None and key.id != binding.key_id)
            or not hmac.compare_digest(key.key.get_secret_value(), binding.key.get_secret_value())
            or (key.expires_at is not None and key.expires_at <= datetime.now(timezone.utc))
        ):
            await self.store.block(binding)
            raise ApplicationKeyError("application_key_blocked")

    async def ensure(self, raw_cookie: str) -> GatewayAPIKey:
        await self.auth.verify_session(raw_cookie)
        session = await self.auth.store.load(raw_cookie)
        return await self._ensure(session, lambda: self.auth.store.load(raw_cookie))

    async def ensure_for_session(self, session_id: str) -> GatewayAPIKey:
        await self.auth.verify_session_reference(session_id)
        session = await self.auth.store.load_reference(session_id)
        return await self._ensure(session, lambda: self.auth.store.load_reference(session_id))

    async def _ensure(self, session, reload_session) -> GatewayAPIKey:
        token = session.tokens.access_token.get_secret_value()
        groups = await self.auth.gateway.available_groups(token)
        if not any(group.id == self.group_id and group.status == "active" for group in groups):
            raise ApplicationKeyError("group_unavailable")
        binding = await self.store.prepare(session.user.id, session.gateway_id, self.group_id)
        if binding.state == "blocked":
            raise ApplicationKeyError("application_key_blocked")
        if binding.state == "active":
            if binding.key_id is None:
                raise ApplicationKeyError("invalid_binding")
            try:
                key = await self.auth.gateway.get_key(token, binding.key_id)
            except AigcdoGatewayError as exc:
                if exc.code == "resource_not_found":
                    await self.store.block(binding)
                    raise ApplicationKeyError("application_key_blocked") from None
                raise
        elif binding.state == "prepared" and await self.store.claim_creation(binding):
            try:
                await reload_session()
            except BaseException:
                # No gateway call has started, so this claim is safe to release.
                await self.store.release_unsubmitted(binding)
                raise
            # Persist uncertainty before POST; a lost response must never trigger another creation.
            key = await self.auth.gateway.create_key(
                token, name=binding.name, group_id=binding.group_id,
                custom_key=binding.key.get_secret_value(), idempotency_key=binding.name,
            )
        elif binding.state in {"prepared", "uncertain"}:
            found = await self.auth.gateway.find_keys(token, binding.name)
            matches = [key for key in found if key.name == binding.name]
            if not matches:
                # shortcut: no blind replay after uncertain creation; operator reconciliation is required.
                raise ApplicationKeyError("provisioning_pending")
            if len(matches) != 1:
                await self.store.block(binding)
                raise ApplicationKeyError("application_key_blocked")
            key = matches[0]
        else:
            raise ApplicationKeyError("invalid_binding")
        await self._validate(binding, key)
        await self.store.activate(binding, key.id)
        # A logout during the external request must not return a credential to its old session.
        await reload_session()
        return key
