"""Gateway-owned recharge orders with durable, at-most-once create attempts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import aiosqlite
from cryptography.fernet import Fernet, InvalidToken

from novelvideo.aigcdo_billing import CreditDisplayPolicy
from novelvideo.aigcdo_gateway import AigcdoGatewayError
from novelvideo.aigcdo_payment_contract import GatewayCreatedOrder, GatewayPaymentOrder
from novelvideo.aigcdo_sessions import AigcdoAuthPort
from novelvideo.api.routes.aigcdo_auth import trusted_app_origin


class AigcdoPaymentStore:
    """Request/receipt journal only; stores no wallet balance or login tokens."""

    def __init__(self, path: Path, encryption_key: bytes) -> None:
        self.path = path
        self._cipher = Fernet(encryption_key)

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
                    CREATE TABLE IF NOT EXISTS payment_attempts (
                        user_id TEXT NOT NULL,
                        attempt_hash TEXT NOT NULL,
                        request_hash TEXT NOT NULL,
                        receipt BLOB,
                        PRIMARY KEY (user_id, attempt_hash)
                    )
                """)
                await db.commit()
                yield db
        except (OSError, sqlite3.Error):
            raise AigcdoGatewayError("payment_storage_unavailable") from None

    async def claim(
        self, user_id: str, attempt_hash: str, request_hash: str, *, create: bool = True,
        reject: bool = False,
    ) -> dict | None:
        async with self._db() as db:
            await db.execute("BEGIN IMMEDIATE")
            row = await (await db.execute(
                "SELECT * FROM payment_attempts WHERE user_id=? AND attempt_hash=?",
                (user_id, attempt_hash),
            )).fetchone()
            if row is None:
                if create:
                    receipt = self._cipher.encrypt(json.dumps({
                        "user_id": user_id, "attempt_hash": attempt_hash,
                        "request_hash": request_hash, "result": None,
                    }).encode()) if reject else None
                    await db.execute(
                        "INSERT INTO payment_attempts VALUES (?, ?, ?, ?)",
                        (user_id, attempt_hash, request_hash, receipt),
                    )
                await db.commit()
                if reject:
                    raise AigcdoGatewayError("payment_not_submitted")
                return None
            if row["request_hash"] != request_hash:
                raise AigcdoGatewayError("idempotency_conflict")
            if row["receipt"] is None:
                raise AigcdoGatewayError("payment_pending")
        try:
            data = json.loads(self._cipher.decrypt(row["receipt"]))
            if (data["user_id"], data["attempt_hash"], data["request_hash"]) != (
                user_id, attempt_hash, request_hash,
            ):
                raise ValueError("receipt binding mismatch")
            result = data["result"]
        except (InvalidToken, ValueError, TypeError, KeyError):
            raise AigcdoGatewayError("payment_storage_unavailable") from None
        if result is None:
            raise AigcdoGatewayError("payment_not_submitted")
        return result

    async def complete(self, user_id: str, attempt_hash: str, request_hash: str, result: dict) -> None:
        receipt = self._cipher.encrypt(json.dumps({
            "user_id": user_id, "attempt_hash": attempt_hash, "request_hash": request_hash, "result": result,
        }).encode())
        async with self._db() as db:
            cursor = await db.execute(
                """UPDATE payment_attempts SET receipt=?
                   WHERE user_id=? AND attempt_hash=? AND request_hash=? AND receipt IS NULL""",
                (receipt, user_id, attempt_hash, request_hash),
            )
            await db.commit()
        if cursor.rowcount != 1:
            raise AigcdoGatewayError("payment_storage_unavailable")


class AigcdoPayments:
    def __init__(
        self, auth: AigcdoAuthPort, store: AigcdoPaymentStore,
        policy: CreditDisplayPolicy, app_origin: str,
    ) -> None:
        self.auth = auth
        self.store = store
        self.policy = policy
        self.app_origin = trusted_app_origin(app_origin)

    async def _session(self, cookie: str | None):
        await self.auth.verify_session(cookie)
        return await self.auth.store.load(cookie)

    @staticmethod
    def _order_data(order: GatewayPaymentOrder, gateway_id: int) -> dict:
        if order.user_id != gateway_id or order.order_type != "balance":
            raise AigcdoGatewayError("access_denied")
        data = order.model_dump(mode="json", exclude={"user_id"})
        data["id"] = str(order.id)
        data["ledger_unit"] = "USD"
        data["fulfilled"] = order.status == "COMPLETED"
        return data

    async def checkout(self, cookie: str | None) -> dict:
        session = await self._session(cookie)
        info = await self.auth.gateway.payment_checkout(session.tokens.access_token.get_secret_value())
        data = info.model_dump(mode="json")
        data["methods"] = {
            name: details for name, details in data["methods"].items()
            if name in {"alipay", "wxpay"} and details["payment_type"] == name
        }
        data["policy"] = self.policy.metadata()
        await self.auth.store.load(cookie)
        return data

    async def create(
        self, cookie: str | None, *, amount: Decimal, payment_type: str, idempotency_key: str,
    ) -> dict:
        if (
            not isinstance(amount, Decimal) or not amount.is_finite()
            or not 0 < amount <= Decimal("1000000")
            or amount != amount.quantize(Decimal("0.01"))
            or payment_type not in {"alipay", "wxpay"}
            or not isinstance(idempotency_key, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", idempotency_key)
        ):
            raise AigcdoGatewayError("request_rejected")
        normalized = format(amount.quantize(Decimal("0.01")), "f")
        attempt_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
        request_hash = hashlib.sha256(
            json.dumps([normalized, payment_type, self.app_origin]).encode()
        ).hexdigest()
        session = await self._session(cookie)
        token = session.tokens.access_token.get_secret_value()
        cached = await self.store.claim(session.user.id, attempt_hash, request_hash, create=False)
        if cached is None:
            # New-order restrictions must not prevent recovery of an existing checkout.
            info = await self.auth.gateway.payment_checkout(token)
            method = info.methods.get(payment_type)
            rejected = (
                info.balance_disabled or method is None or method.payment_type != payment_type
                or (info.global_min and amount < info.global_min)
                or (info.global_max and amount > info.global_max)
            )
            await self.auth.store.load(cookie)
            # Retire rejected attempts atomically so an overlapping preflight cannot submit later.
            cached = await self.store.claim(session.user.id, attempt_hash, request_hash, reject=bool(rejected))
        if cached is None:
            # The gateway create handler is not idempotent. Never repeat after this point.
            try:
                created = await self.auth.gateway.create_payment_order(
                    token, amount=amount, payment_type=payment_type, app_origin=self.app_origin,
                )
                order = await self.auth.gateway.payment_order(token, created.order_id)
            except AigcdoGatewayError as exc:
                if exc.status_code >= 500:
                    raise AigcdoGatewayError("payment_pending") from None
                raise
            self._validate_created(created, order, session.gateway_id, method.currency, payment_type)
            cached = {
                "order_id": order.id,
                "out_trade_no": order.out_trade_no,
                "expected_credits": self.policy.display(order.amount),
                "policy": self.policy.metadata(),
                "checkout": {"pay_url": created.pay_url, "qr_code": created.qr_code},
            }
            try:
                await self.store.complete(session.user.id, attempt_hash, request_hash, cached)
            except AigcdoGatewayError:
                raise AigcdoGatewayError("payment_pending") from None
        else:
            order = await self.auth.gateway.payment_order(token, cached["order_id"])
            if order.out_trade_no != cached["out_trade_no"]:
                raise AigcdoGatewayError("invalid_response")
        data = self._order_data(order, session.gateway_id)
        checkout = cached["checkout"] if (
            order.status == "PENDING" and order.expires_at > datetime.now(timezone.utc)
        ) else None
        await self.auth.store.load(cookie)
        return {
            "order": data, "checkout": checkout,
            "expected_credits": cached["expected_credits"], "policy": cached["policy"],
        }

    @staticmethod
    def _validate_created(
        created: GatewayCreatedOrder, order: GatewayPaymentOrder, gateway_id: int,
        currency: str, payment_type: str,
    ) -> None:
        AigcdoPayments._order_data(order, gateway_id)
        if (
            order.id != created.order_id or order.currency != currency or order.payment_type != payment_type
            or any(getattr(created, key) != getattr(order, key) for key in (
                "amount", "pay_amount", "fee_rate", "bonus_amount", "currency", "payment_type", "out_trade_no",
            ))
            or not (created.pay_url or created.qr_code)
        ):
            raise AigcdoGatewayError("invalid_response")

    async def orders(self, cookie: str | None, *, page: int = 1, page_size: int = 20) -> dict:
        session = await self._session(cookie)
        result = await self.auth.gateway.payment_orders(
            session.tokens.access_token.get_secret_value(), page=page, page_size=page_size,
        )
        items = [self._order_data(order, session.gateway_id) for order in result.items]
        await self.auth.store.load(cookie)
        return {"items": items, "page": result.page, "page_size": result.page_size,
                "total": result.total, "pages": result.pages}

    async def order(self, cookie: str | None, order_id: int) -> dict:
        session = await self._session(cookie)
        order = await self.auth.gateway.payment_order(session.tokens.access_token.get_secret_value(), order_id)
        if order.id != order_id:
            raise AigcdoGatewayError("invalid_response")
        data = self._order_data(order, session.gateway_id)
        await self.auth.store.load(cookie)
        return data

    async def verify(self, cookie: str | None, order_id: int) -> dict:
        session = await self._session(cookie)
        token = session.tokens.access_token.get_secret_value()
        original = await self.auth.gateway.payment_order(token, order_id)
        self._order_data(original, session.gateway_id)
        if original.id != order_id:
            raise AigcdoGatewayError("invalid_response")
        await self.auth.store.load(cookie)
        order = await self.auth.gateway.verify_payment_order(token, original.out_trade_no)
        if order.id != order_id or order.out_trade_no != original.out_trade_no:
            raise AigcdoGatewayError("invalid_response")
        result = self._order_data(order, session.gateway_id)
        await self.auth.store.load(cookie)
        return result
