"""Persistent browser sessions backed by AIGCDO user authentication."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path

import aiosqlite
from cryptography.fernet import Fernet, InvalidToken
from pydantic import ValidationError
from ulid import ULID

from novelvideo.aigcdo_gateway import (
    AigcdoGatewayClient,
    AigcdoGatewayError,
    GatewayLoginChallenge,
    GatewaySession,
    GatewaySessionTokens,
    GatewayUser,
)
from novelvideo.ports.auth_contract import (
    AuthenticatedUser, AuthError, AuthFailureReason, LoginResult,
)

SESSION_TTL = 7 * 86400
REFRESH_CLAIM_TTL = 60
# Every private request verifies its session; without reuse each one costs a gateway round trip.
VERIFY_TTL = 30
# How long a just-expired verification still answers requests while it is re-checked.
VERIFY_STALE_GRACE = 300
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Session:
    cookie_hash: str = field(repr=False)
    user: AuthenticatedUser
    gateway_id: int
    tokens: GatewaySessionTokens = field(repr=False)
    expires_at: float
    access_expires_at: float
    cipher: bytes = field(repr=False)
    refreshing_at: float | None


class AigcdoSessionStore:
    def __init__(self, path: Path, encryption_key: bytes) -> None:
        self.path = path
        self._fernet = Fernet(encryption_key)

    def seal_login_challenge(self, challenge: GatewayLoginChallenge) -> str:
        data = {
            "kind": "login_2fa",
            "expires_at": time.time() + 300,
            "temp_token": challenge.temp_token.get_secret_value(),
        }
        return self._fernet.encrypt(json.dumps(data).encode()).decode("ascii")

    def open_login_challenge(self, cookie: str) -> str:
        try:
            if not cookie or len(cookie) > 4096:
                raise ValueError("invalid challenge")
            data = json.loads(self._fernet.decrypt(cookie.encode("ascii")))
            if data["kind"] != "login_2fa" or data["expires_at"] <= time.time():
                raise ValueError("invalid challenge")
            challenge = GatewayLoginChallenge.model_validate({
                "requires_2fa": True, "temp_token": data["temp_token"],
            })
            return challenge.temp_token.get_secret_value()
        except (InvalidToken, ValueError, TypeError, KeyError):
            raise AuthError(AuthFailureReason.INVALID) from None

    @asynccontextmanager
    async def _db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        async with aiosqlite.connect(self.path, timeout=10) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON")
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS identities (
                    id TEXT PRIMARY KEY,
                    gateway_id INTEGER NOT NULL UNIQUE,
                    username TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    cookie_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES identities(id),
                    cipher BLOB NOT NULL,
                    expires_at REAL NOT NULL,
                    access_expires_at REAL NOT NULL,
                    refreshing_at REAL
                );
                CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
            """)
            yield db

    @staticmethod
    def _hash(raw_cookie: str | None) -> str:
        if not raw_cookie:
            raise AuthError(AuthFailureReason.MISSING)
        if not isinstance(raw_cookie, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", raw_cookie):
            raise AuthError(AuthFailureReason.INVALID)
        return hashlib.sha256(raw_cookie.encode("ascii")).hexdigest()

    def _encrypt(
        self, cookie_hash: str, user_id: str, tokens: GatewaySessionTokens,
        expires_at: float, access_expires_at: float,
    ) -> bytes:
        data = {
            "cookie_hash": cookie_hash, "user_id": user_id,
            "expires_at": expires_at, "access_expires_at": access_expires_at,
            "tokens": {
                "access_token": tokens.access_token.get_secret_value(),
                "refresh_token": tokens.refresh_token.get_secret_value(),
                "expires_in": tokens.expires_in, "token_type": tokens.token_type,
            },
        }
        return self._fernet.encrypt(json.dumps(data).encode())

    async def create(self, session: GatewaySession) -> LoginResult:
        if session.user.status != "active":
            raise AuthError(AuthFailureReason.USER_SUSPENDED)
        raw_cookie = secrets.token_urlsafe(32)
        cookie_hash = self._hash(raw_cookie)
        now = time.time()
        user_id = str(ULID())
        username = f"aigcdo_{user_id.lower()}"
        async with self._db() as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                """INSERT INTO identities(id, gateway_id, username, role, status)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(gateway_id) DO UPDATE SET role=excluded.role, status=excluded.status""",
                (user_id, session.user.id, username, session.user.role, session.user.status),
            )
            cursor = await db.execute("SELECT * FROM identities WHERE gateway_id=?", (session.user.id,))
            row = await cursor.fetchone()
            user = AuthenticatedUser(id=row["id"], username=row["username"], role=row["role"])
            expires_at = now + SESSION_TTL
            access_expires_at = now + session.expires_in
            cipher = self._encrypt(cookie_hash, user.id, session, expires_at, access_expires_at)
            await db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, NULL)",
                (cookie_hash, user.id, cipher, expires_at, access_expires_at),
            )
            await db.commit()
        return LoginResult(user=user, session_id=cookie_hash, raw_cookie=raw_cookie)

    async def get_identity(self, user_id: str) -> AuthenticatedUser | None:
        async with self._db() as db:
            cursor = await db.execute(
                "SELECT * FROM identities WHERE id=? AND status='active'", (user_id,)
            )
            row = await cursor.fetchone()
        return AuthenticatedUser(id=row["id"], username=row["username"], role=row["role"]) if row else None

    async def get_user_id(self, username: str) -> str | None:
        async with self._db() as db:
            cursor = await db.execute(
                "SELECT id FROM identities WHERE username=? AND status='active'", (username,)
            )
            row = await cursor.fetchone()
        return row["id"] if row else None

    async def load(self, raw_cookie: str | None) -> _Session:
        return await self.load_reference(self._hash(raw_cookie))

    async def load_reference(self, cookie_hash: str) -> _Session:
        """Server-side reference only; HTTP callers must still supply the raw Cookie."""
        if not isinstance(cookie_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", cookie_hash):
            raise AuthError(AuthFailureReason.INVALID)
        async with self._db() as db:
            cursor = await db.execute(
                """SELECT s.*, i.gateway_id, i.username, i.role, i.status
                   FROM sessions s JOIN identities i ON i.id=s.user_id WHERE cookie_hash=?""",
                (cookie_hash,),
            )
            row = await cursor.fetchone()
        if row is None:
            raise AuthError(AuthFailureReason.INVALID)
        if row["expires_at"] <= time.time():
            await self.delete(cookie_hash)
            raise AuthError(AuthFailureReason.EXPIRED)
        if row["status"] != "active":
            raise AuthError(AuthFailureReason.USER_SUSPENDED)
        return self._decode(row)

    def _decode(self, row: aiosqlite.Row) -> _Session:
        cookie_hash = row["cookie_hash"]
        try:
            data = json.loads(self._fernet.decrypt(row["cipher"]))
            if (
                data["cookie_hash"] != cookie_hash or data["user_id"] != row["user_id"]
                or data["expires_at"] != row["expires_at"]
                or data["access_expires_at"] != row["access_expires_at"]
            ):
                raise ValueError("session binding mismatch")
            tokens = GatewaySessionTokens.model_validate(data["tokens"])
        except (InvalidToken, ValueError, KeyError, TypeError, ValidationError):
            raise AuthError(AuthFailureReason.INVALID) from None
        return _Session(
            cookie_hash, AuthenticatedUser(row["user_id"], row["username"], row["role"]),
            row["gateway_id"], tokens, row["expires_at"], row["access_expires_at"],
            row["cipher"], row["refreshing_at"],
        )

    async def delete(self, cookie_hash: str) -> None:
        async with self._db() as db:
            await db.execute("DELETE FROM sessions WHERE cookie_hash=?", (cookie_hash,))
            await db.commit()

    async def take_for_logout(self, raw_cookie: str) -> _Session | None:
        try:
            cookie_hash = self._hash(raw_cookie)
        except AuthError:
            return None
        async with self._db() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """SELECT s.*, i.gateway_id, i.username, i.role, i.status
                   FROM sessions s JOIN identities i ON i.id=s.user_id WHERE cookie_hash=?""",
                (cookie_hash,),
            )
            row = await cursor.fetchone()
            await db.execute("DELETE FROM sessions WHERE cookie_hash=?", (cookie_hash,))
            await db.commit()
        if row is None:
            return None
        try:
            return self._decode(row)
        except AuthError:
            logger.warning("Local session revoked; gateway credentials could not be decrypted")
            return None

    async def claim_refresh(self, session: _Session) -> None:
        if session.refreshing_at is not None:
            if session.refreshing_at + REFRESH_CLAIM_TTL <= time.time():
                await self.delete(session.cookie_hash)
                raise AuthError(AuthFailureReason.EXPIRED)
            raise AigcdoGatewayError("gateway_unavailable")
        async with self._db() as db:
            cursor = await db.execute(
                """UPDATE sessions SET refreshing_at=?
                   WHERE cookie_hash=? AND cipher=? AND refreshing_at IS NULL AND expires_at>?""",
                (time.time(), session.cookie_hash, session.cipher, time.time()),
            )
            await db.commit()
        if cursor.rowcount != 1:
            raise AigcdoGatewayError("gateway_unavailable")

    async def save_refresh(self, session: _Session, tokens: GatewaySessionTokens) -> None:
        access_expires_at = time.time() + tokens.expires_in
        cipher = self._encrypt(
            session.cookie_hash, session.user.id, tokens, session.expires_at, access_expires_at
        )
        async with self._db() as db:
            cursor = await db.execute(
                """UPDATE sessions SET cipher=?, access_expires_at=?, refreshing_at=NULL
                   WHERE cookie_hash=? AND cipher=? AND refreshing_at IS NOT NULL AND expires_at>?""",
                (cipher, access_expires_at, session.cookie_hash, session.cipher, time.time()),
            )
            await db.commit()
        if cursor.rowcount != 1:
            raise AuthError(AuthFailureReason.REVOKED)

    async def confirm_identity(self, session: _Session, user: GatewayUser) -> dict:
        if user.id != session.gateway_id:
            await self.delete(session.cookie_hash)
            raise AuthError(AuthFailureReason.INVALID)
        async with self._db() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT 1 FROM sessions WHERE cookie_hash=? AND expires_at>?",
                (session.cookie_hash, time.time()),
            )
            if await cursor.fetchone() is None:
                raise AuthError(AuthFailureReason.REVOKED)
            await db.execute(
                "UPDATE identities SET role=?, status=? WHERE id=?",
                (user.role, user.status, session.user.id),
            )
            if user.status != "active":
                await db.execute("DELETE FROM sessions WHERE user_id=?", (session.user.id,))
            await db.commit()
        if user.status != "active":
            raise AuthError(AuthFailureReason.USER_SUSPENDED)
        return {
            **AuthenticatedUser(session.user.id, session.user.username, user.role).to_legacy_dict(),
            "credential_kind": "browser_session",
            # What the account menu shows; the username is an opaque storage id.
            "email": user.email,
        }


class AigcdoAuthPort:
    def __init__(self, store: AigcdoSessionStore, gateway: AigcdoGatewayClient) -> None:
        self.store = store
        self.gateway = gateway
        self._verified: dict[str, tuple[float, bytes, dict]] = {}
        self._reverifying: dict[str, asyncio.Task] = {}
        # Who administers this installation; the gateway's own admin role means nothing here.
        self.admin_gateway_ids: set[int] = set()

    async def _created(self, session: GatewaySession) -> LoginResult:
        result = await self.store.create(session)
        role = "admin" if session.user.id in self.admin_gateway_ids else "user"
        return replace(result, user=replace(result.user, role=role))

    async def login(
        self, email: str, password: str, *, turnstile_token: str = "",
    ) -> LoginResult | GatewayLoginChallenge:
        result = await self.gateway.login(email, password, turnstile_token=turnstile_token)
        if isinstance(result, GatewayLoginChallenge):
            return result
        return await self._created(result)

    async def register(
        self, email: str, password: str, *, verify_code: str = "", turnstile_token: str = "",
    ) -> LoginResult:
        return await self._created(await self.gateway.register(
            email, password, verify_code=verify_code, turnstile_token=turnstile_token,
        ))

    async def login_2fa(self, temp_token: str, code: str) -> LoginResult:
        return await self._created(await self.gateway.login_2fa(temp_token, code))

    async def verify_session(self, raw_cookie: str | None) -> dict:
        session = await self.store.load(raw_cookie)
        cached = self._verified.get(session.cookie_hash)
        # The local row was just re-read, so logout and expiry stay immediate; only a
        # gateway-side change (disable, role, password reset) waits out VERIFY_TTL here.
        # Task and Agent authority (verify_session_reference) always asks the gateway.
        if cached and cached[1] == session.cipher:
            now = time.time()
            if cached[0] > now:
                return dict(cached[2])
            # The gateway link is slow and lossy: answer from the last result and re-check
            # behind the request, so page loads neither wait on it nor fail with it.
            if cached[0] + VERIFY_STALE_GRACE > now:
                if session.cookie_hash not in self._reverifying:
                    self._reverifying[session.cookie_hash] = asyncio.create_task(self._reverify(session))
                return dict(cached[2])
        return dict(await self._verify_and_cache(session))

    async def _verify_and_cache(self, session: _Session) -> dict:
        verified = await self._verify(session)
        if len(self._verified) >= 4096:
            self._verified.clear()
        self._verified[session.cookie_hash] = (time.time() + VERIFY_TTL, session.cipher, verified)
        return verified

    async def _reverify(self, session: _Session) -> None:
        try:
            await self._verify_and_cache(session)
        except AigcdoGatewayError as exc:
            if exc.code != "gateway_unavailable":
                self._verified.pop(session.cookie_hash, None)
        except Exception:
            # Revoked or suspended: the next request must ask again and fail properly.
            self._verified.pop(session.cookie_hash, None)
        finally:
            self._reverifying.pop(session.cookie_hash, None)

    async def verify_session_reference(self, session_id: str) -> dict:
        return await self._verify(await self.store.load_reference(session_id))

    async def _verify(self, session: _Session) -> dict:
        if session.access_expires_at <= time.time() or session.refreshing_at is not None:
            await self.store.claim_refresh(session)
            tokens = None
            try:
                tokens = await self.gateway.refresh(session.tokens.refresh_token.get_secret_value())
                await self.store.save_refresh(session, tokens)
            except BaseException as exc:
                # Refresh may already have consumed the old token; never retry it blindly.
                await self.store.delete(session.cookie_hash)
                if tokens is not None:
                    try:
                        await self.gateway.logout(tokens.refresh_token.get_secret_value())
                    except AigcdoGatewayError:
                        logger.warning("Could not revoke orphaned gateway refresh session")
                if isinstance(exc, AigcdoGatewayError) and exc.code in {
                    "authentication_failed", "access_denied",
                }:
                    raise AuthError(AuthFailureReason.REVOKED) from None
                raise
            session = await self.store.load_reference(session.cookie_hash)
        try:
            user = await self.gateway.me(session.tokens.access_token.get_secret_value())
        except AigcdoGatewayError as exc:
            if exc.code in {"authentication_failed", "access_denied"}:
                await self.store.delete(session.cookie_hash)
                raise AuthError(AuthFailureReason.REVOKED) from None
            raise
        verified = await self.store.confirm_identity(session, user)
        return {**verified, "role": "admin" if session.gateway_id in self.admin_gateway_ids else "user"}

    async def revoke_session(self, raw_cookie: str) -> None:
        session = await self.store.take_for_logout(raw_cookie)
        if session is None:
            return
        await self.gateway.logout(session.tokens.refresh_token.get_secret_value())
