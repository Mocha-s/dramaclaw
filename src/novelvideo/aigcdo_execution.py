"""Durable parent-session-bound task and Agent authority, without shared credentials."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from functools import partial
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
from cryptography.fernet import Fernet, InvalidToken

from novelvideo.aigcdo_application_keys import ApplicationKeyError
from novelvideo.aigcdo_gateway import AigcdoGatewayError
from novelvideo.aigcdo_model_runtime import user_key_scope
from novelvideo.ports.auth_contract import (
    AgentAuthenticatedUser, AgentSessionToken, AuthError, AuthFailureReason, DEFAULT_EXTERNAL_AGENT_SCOPES,
)
from novelvideo.ports.authz import AdmissionContext, AuthzError, AuthzServiceUnavailable, BillingPrincipal
from novelvideo.ports.model_credentials import CredentialReference, RequestCredential
from novelvideo.task_backend.consumer import TaskEnvelopeConsumer, VerifiedTaskDelivery
from novelvideo.task_backend.envelope import InvalidTaskEnvelope
from novelvideo.task_backend.producer import TaskEnvelopeProducer, _validate_forbidden_payload_fields

_PARENT: ContextVar[tuple[object, str] | None] = ContextVar("aigcdo_execution_parent", default=None)
_MAX_TTL = 86400


def _denied():
    return AuthError(AuthFailureReason.INVALID)


class AigcdoExecutionAuthority:
    def __init__(self, auth, application_keys, projects, path: Path, encryption_key: bytes):
        self.auth = auth
        self.keys = application_keys
        self.projects = projects
        self.path = path
        self._cipher = Fernet(encryption_key)
        signing_key = hmac.digest(encryption_key, b"aigcdo-task-envelope-v1", "sha256")
        def clock():
            return datetime.now(timezone.utc)
        self.producer = TaskEnvelopeProducer(
            authz=self, active_key_id="aigcdo-v1", keyring={"aigcdo-v1": signing_key},
            clock=clock, envelope_id_factory=lambda: secrets.token_hex(16),
        )
        self.consumer = TaskEnvelopeConsumer(keyring={"aigcdo-v1": signing_key}, authz=self, clock=clock)
        self._request_keys: dict[str, tuple[str, float]] = {}

    @asynccontextmanager
    async def _db(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            self.path.chmod(0o600)
            async with aiosqlite.connect(self.path, timeout=10) as db:
                await db.execute("""CREATE TABLE IF NOT EXISTS execution_grants (
                    kind TEXT NOT NULL, reference TEXT NOT NULL, cipher BLOB NOT NULL,
                    PRIMARY KEY(kind, reference))""")
                await db.commit()
                yield db
        except (OSError, sqlite3.Error):
            raise AigcdoGatewayError("gateway_unavailable") from None

    async def _read(self, kind: str, reference: str) -> dict:
        async with self._db() as db:
            row = await (await db.execute(
                "SELECT cipher FROM execution_grants WHERE kind=? AND reference=?", (kind, reference),
            )).fetchone()
        if row is None:
            raise _denied()
        try:
            data = json.loads(self._cipher.decrypt(row[0]))
            if data["kind"] != kind or data["reference"] != reference or data["expires_at"] <= time.time():
                raise ValueError("invalid grant")
            return data
        except (InvalidToken, KeyError, TypeError, ValueError):
            raise _denied() from None

    async def _insert(self, kind: str, reference: str, data: dict) -> bool:
        cipher = self._cipher.encrypt(json.dumps({**data, "kind": kind, "reference": reference}).encode())
        async with self._db() as db:
            cursor = await db.execute(
                "INSERT OR IGNORE INTO execution_grants VALUES (?, ?, ?)", (kind, reference, cipher),
            )
            await db.commit()
        return cursor.rowcount == 1

    async def _confirm_live(self, kind: str, reference: str, data: dict) -> None:
        # One final snapshot checks both revocation sources after external/project awaits.
        async with self._db() as db:
            await db.execute("ATTACH DATABASE ? AS browser_sessions", (str(self.auth.store.path),))
            row = await (await db.execute(
                """SELECT g.cipher FROM execution_grants g
                   JOIN browser_sessions.sessions s ON s.cookie_hash=?
                   JOIN browser_sessions.identities i ON i.id=s.user_id
                   WHERE g.kind=? AND g.reference=? AND s.user_id=?
                     AND s.expires_at>? AND i.status='active'""",
                (data["parent"], kind, reference, data["user_id"], time.time()),
            )).fetchone()
        if row is None:
            raise _denied()
        try:
            current = json.loads(self._cipher.decrypt(row[0]))
            if current != data or current["expires_at"] <= time.time():
                raise ValueError("grant changed")
        except (InvalidToken, KeyError, ValueError, TypeError):
            raise _denied() from None

    @staticmethod
    def _key_failure(error: ApplicationKeyError):
        if error.status_code >= 500:
            return AuthzServiceUnavailable()
        return AuthzError("AIGCDO_EXECUTION_DENIED")

    async def _project(self, user_id: str, project_id: str | None) -> None:
        if project_id is None:
            return
        project = await self.projects.get_project(project_id)
        if (project is None or project.owner_type != "user" or project.owner_id != user_id
                or project.status != "active" or project.purged_at):
            raise _denied()

    async def _validate(self, data: dict) -> dict:
        user = await self.auth.verify_session_reference(data["parent"])
        if user["id"] != data["user_id"] or user["username"] != data["username"]:
            raise _denied()
        await self._project(user["id"], data["project_id"])
        return user

    @asynccontextmanager
    async def session_scope(self, reference: str):
        # This transports a reference only; every grant creation revalidates it in _parent.
        token = _PARENT.set((self, reference))
        try:
            yield
        finally:
            _PARENT.reset(token)

    def browser_scope(self, raw_cookie: str):
        return self.session_scope(self.auth.store._hash(raw_cookie))

    async def _parent(self):
        current = _PARENT.get()
        if current is None or current[0] is not self:
            raise _denied()
        await self.auth.verify_session_reference(current[1])
        return await self.auth.store.load_reference(current[1])

    async def issue_task(self, cookie: str, *, root_task_id: str, project_id: str, task_type: str, payload: dict):
        async with self.browser_scope(cookie):
            return await self.sign_top_level(
                user_id=None, root_task_id=root_task_id, project_id=project_id,
                task_type=task_type, payload=payload,
            )

    async def sign_top_level(
        self, *, user_id: str | None, root_task_id: str, task_type: str, project_id: str, payload: dict,
    ):
        """Producer seam of the task backend: bind the task to the request's own session."""
        try:
            if not root_task_id or len(root_task_id) > 128 or not project_id:
                raise _denied()
            # Round-trip before awaiting so caller mutation cannot change what is bound/signed.
            copied = json.loads(json.dumps(payload, allow_nan=False))
            _validate_forbidden_payload_fields(copied)
            digest = hashlib.sha256(json.dumps(
                [task_type, copied], sort_keys=True, separators=(",", ":"), allow_nan=False,
            ).encode()).hexdigest()
            session = await self._parent()
            if user_id is not None and user_id != session.user.id:
                raise _denied()
            await self._project(session.user.id, project_id)
            await self.keys.ensure_for_session(session.cookie_hash)
            now = time.time()
            data = {
                "parent": session.cookie_hash, "user_id": session.user.id, "username": session.user.username,
                "project_id": project_id, "digest": digest,
                "expires_at": min(now + _MAX_TTL, session.expires_at),
                "admitted_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
                "admission_id": secrets.token_hex(16),
            }
            await self._insert("task", root_task_id, data)
            original = await self._read("task", root_task_id)
            if any(original[name] != data[name] for name in ("parent", "user_id", "project_id", "digest")):
                raise _denied()
            return await self.producer.sign_top_level(
                user_id=session.user.id, root_task_id=root_task_id, project_id=project_id,
                task_type=task_type, payload=copied,
            )
        except InvalidTaskEnvelope:
            raise
        except ApplicationKeyError as exc:
            raise self._key_failure(exc) from None
        except AigcdoGatewayError:
            raise AuthzServiceUnavailable() from None
        except (AuthError, ValueError, TypeError):
            raise AuthzError("AIGCDO_EXECUTION_DENIED") from None

    @staticmethod
    def _admission(data: dict, root: str) -> AdmissionContext:
        return AdmissionContext(
            requester_user_id=data["user_id"], billing_principal=BillingPrincipal("platform", data["user_id"]),
            credential=CredentialReference("platform", f"aigcdo-task:{root}", 1),
            admission_id=data["admission_id"], root_task_id=root,
            admitted_at=data["admitted_at"], authz_version=1,
        )

    async def admit_model_task(self, *, user_id: str, root_task_id: str) -> AdmissionContext:
        try:
            data = await self._read("task", root_task_id)
            if data["user_id"] != user_id:
                raise _denied()
            await self._validate(data)
            await self.keys.ensure_for_session(data["parent"])
            await self._read("task", root_task_id)
            await self._project(user_id, data["project_id"])
            await self._confirm_live("task", root_task_id, data)
            return self._admission(data, root_task_id)
        except ApplicationKeyError as exc:
            raise self._key_failure(exc) from None
        except AuthError:
            raise AuthzError("AIGCDO_EXECUTION_DENIED") from None
        except AigcdoGatewayError:
            raise AuthzServiceUnavailable() from None

    async def resolve(self, admission: AdmissionContext) -> RequestCredential:
        try:
            if type(admission) is not AdmissionContext:
                raise _denied()
            current = await self.admit_model_task(
                user_id=admission.requester_user_id, root_task_id=admission.root_task_id,
            )
            if current != admission:
                raise _denied()
            data = await self._read("task", admission.root_task_id)
            key = await self.keys.ensure_for_session(data["parent"])
            await self._project(data["user_id"], data["project_id"])
            await self._confirm_live("task", admission.root_task_id, data)
            return RequestCredential(admission.credential, key.key.get_secret_value(), "https://api.aigcdo.top/v1")
        except ApplicationKeyError as exc:
            raise self._key_failure(exc) from None
        except AuthError:
            raise AuthzError("AIGCDO_EXECUTION_DENIED") from None
        except AigcdoGatewayError:
            raise AuthzServiceUnavailable() from None

    async def task_run_scope(self, delivery: VerifiedTaskDelivery):
        """Resolve the task owner's key on the event loop; the worker thread binds it."""
        # shortcut: the key is validated once per task run, not per model call; a task that
        # outlives a logout finishes on its owner's key. Revalidate per call if tasks get long.
        credential = await self.resolve_delivery(delivery)
        return partial(user_key_scope, credential.api_key)

    async def request_key(self, reference: str) -> str:
        """The session owner's ready key for inline model calls, or "" (which fails closed)."""
        cached = self._request_keys.get(reference)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        try:
            key = (await self.keys.ensure_for_session(reference)).key.get_secret_value()
        except (ApplicationKeyError, AigcdoGatewayError, AuthError):
            return ""
        # The boundary re-verifies the session on every request, so a short reuse window
        # only delays noticing a key the gateway itself already refuses.
        if len(self._request_keys) >= 4096:
            self._request_keys.clear()
        self._request_keys[reference] = (key, time.monotonic() + 60)
        return key

    async def resolve_delivery(self, delivery: VerifiedTaskDelivery) -> RequestCredential:
        if type(delivery) is not VerifiedTaskDelivery:
            raise AuthzError("AIGCDO_EXECUTION_DENIED")
        try:
            data = await self._read("task", delivery.admission.root_task_id)
            if data["user_id"] != delivery.requester_user_id or data["project_id"] != delivery.project_id:
                raise _denied()
            payload = {name: getattr(delivery, name) for name in ("episode", "beat_num", "scope", "queue_kind", "payload")}
            digest = hashlib.sha256(json.dumps(
                [delivery.task_type, payload], sort_keys=True, separators=(",", ":"), allow_nan=False,
            ).encode()).hexdigest()
            if digest != data["digest"]:
                raise _denied()
            return await self.resolve(delivery.admission)
        except (AuthError, ValueError, TypeError):
            raise AuthzError("AIGCDO_EXECUTION_DENIED") from None

    async def create_agent_session(
        self, *, username: str, scopes, ttl_seconds: int | None = None, agent_kind: str = "agent",
        worker_id: str | None = None, parent_session_id: str | None = None,
        current_scope_kind: str = "home", current_project_id: str | None = None, metadata: dict | None = None,
    ) -> AgentSessionToken:
        session = await self._parent()
        ttl = 7200 if ttl_seconds is None else ttl_seconds
        if (username != session.user.username or type(ttl) is not int or not 1 <= ttl <= _MAX_TTL
                or not isinstance(scopes, (list, tuple)) or any(type(s) is not str for s in scopes)
                or not set(scopes) <= set(DEFAULT_EXTERNAL_AGENT_SCOPES)
                or parent_session_id not in {None, session.cookie_hash}):
            raise _denied()
        self._scope(current_scope_kind, current_project_id)
        await self._project(session.user.id, current_project_id)
        raw = secrets.token_urlsafe(32)
        reference = self.auth.store._hash(raw)
        expiry = int(min(time.time() + ttl, session.expires_at))
        data = {
            "parent": session.cookie_hash, "user_id": session.user.id, "username": username,
            "project_id": current_project_id, "scope_kind": current_scope_kind, "scopes": list(scopes),
            "expires_at": expiry, "agent_kind": agent_kind, "worker_id": worker_id,
        }
        await self._insert("agent", reference, data)
        await self.auth.store.load_reference(session.cookie_hash)
        return AgentSessionToken(raw, reference, username, tuple(scopes), expiry, worker_id or "", agent_kind)

    @staticmethod
    def _scope(kind, project):
        if kind not in {"home", "project"} or (kind == "home" and project is not None) or (
            kind == "project" and (not isinstance(project, str) or not project)
        ):
            raise _denied()

    async def verify_agent_session(self, token: str) -> dict:
        reference = self.auth.store._hash(token)
        data = await self._read("agent", reference)
        user = await self._validate(data)
        await self._confirm_live("agent", reference, data)
        return AgentAuthenticatedUser(
            id=user["id"], username=user["username"], role=user["role"],
            agent_session_id=reference, agent_kind=data["agent_kind"], worker_id=data["worker_id"],
            scopes=tuple(data["scopes"]), current_scope_kind=data["scope_kind"],
            current_project_id=data["project_id"], parent_session_id=None,
        ).to_legacy_dict()

    async def agent_parent(self, token: str) -> str:
        """The browser session an Agent token acts for; call after verify_agent_session."""
        return (await self._read("agent", self.auth.store._hash(token)))["parent"]

    async def agent_session_stale(self, token: str) -> bool:
        """Whether a worker's token belongs to another (or an ended) session than this request's."""
        current = _PARENT.get()
        try:
            parent = await self.agent_parent(token)
        except AuthError:
            return True
        return current is None or current[0] is not self or parent != current[1]

    async def update_agent_session_scope(self, token_value: str, *, scope_kind: str, project_id: str | None):
        session = await self._parent()
        reference = self.auth.store._hash(token_value)
        data = await self._read("agent", reference)
        if data["parent"] != session.cookie_hash or data["user_id"] != session.user.id:
            raise _denied()
        self._scope(scope_kind, project_id)
        await self._project(session.user.id, project_id)
        cipher = self._cipher.encrypt(json.dumps({**data, "project_id": project_id, "scope_kind": scope_kind}).encode())
        async with self._db() as db:
            cursor = await db.execute("UPDATE execution_grants SET cipher=? WHERE kind='agent' AND reference=?",
                                      (cipher, reference))
            await db.commit()
        if cursor.rowcount != 1:
            raise _denied()

    async def revoke_agent_session(self, token_value: str):
        reference = self.auth.store._hash(token_value)
        async with self._db() as db:
            await db.execute("DELETE FROM execution_grants WHERE kind='agent' AND reference=?", (reference,))
            await db.commit()
