"""Same-origin recharge and own-order endpoints; payment callbacks stay on gateway."""

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, ValidationError

from novelvideo.aigcdo_payments import AigcdoPayments
from novelvideo.api.auth import AUTH_COOKIE_NAME
from novelvideo.api.routes.aigcdo_auth import (
    AigcdoAPIRoute, _Input, _body, require_aigcdo_origin, require_aigcdo_account,
)


class _Create(_Input):
    amount: Annotated[str, Field(pattern=r"^(?:0|[1-9][0-9]{0,6})(?:\.[0-9]{1,2})?$")]
    payment_type: Literal["alipay", "wxpay"]


def create_aigcdo_payments_router(payments: AigcdoPayments) -> APIRouter:
    async def boundary(request: Request):
        require_aigcdo_origin(request, payments.app_origin)
        if request.method != "GET" and request.query_params:
            raise HTTPException(400, "Unexpected payment query")
        await require_aigcdo_account(request, payments.auth)

    router = APIRouter(
        prefix="/account/payments", route_class=AigcdoAPIRoute, dependencies=[Depends(boundary)],
    )

    def cookie(request: Request):
        return request.cookies.get(AUTH_COOKIE_NAME)

    def order_id(value: str) -> int:
        if not value.isascii() or not value.isdigit() or not 1 <= len(value) <= 18 or int(value) <= 0:
            raise HTTPException(400, "Invalid order ID")
        return int(value)

    @router.get("/checkout")
    async def checkout(request: Request):
        if request.query_params:
            raise HTTPException(400, "Unexpected payment query")
        return {"ok": True, "data": await payments.checkout(cookie(request))}

    @router.post("/orders")
    async def create(request: Request):
        body = await _body(request, _Create)
        if len(request.headers.getlist("idempotency-key")) != 1:
            raise HTTPException(400, "Idempotency-Key required")
        return {"ok": True, "data": await payments.create(
            cookie(request), amount=Decimal(body.amount), payment_type=body.payment_type,
            idempotency_key=request.headers["idempotency-key"],
        )}

    @router.get("/orders")
    async def orders(request: Request):
        params = request.query_params
        if set(params) - {"page", "page_size"} or any(len(params.getlist(k)) != 1 for k in params):
            raise HTTPException(400, "Invalid order filters")
        try:
            if any(not value.isascii() or not value.isdigit() or len(value) > 7 for value in params.values()):
                raise ValueError()
            page, page_size = int(params.get("page", "1")), int(params.get("page_size", "20"))
        except (ValueError, ValidationError):
            raise HTTPException(400, "Invalid order pagination") from None
        return {"ok": True, "data": await payments.orders(cookie(request), page=page, page_size=page_size)}

    @router.get("/orders/{value}")
    async def order(value: str, request: Request):
        if request.query_params:
            raise HTTPException(400, "Unexpected payment query")
        return {"ok": True, "data": await payments.order(cookie(request), order_id(value))}

    @router.post("/orders/{value}/verify")
    async def verify(value: str, request: Request):
        await _body(request, _Input)
        return {"ok": True, "data": await payments.verify(cookie(request), order_id(value))}

    return router
