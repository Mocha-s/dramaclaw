"""Cookie-authenticated views of the gateway's authoritative billing records."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from novelvideo.aigcdo_billing import AigcdoBilling
from novelvideo.aigcdo_gateway import GatewayUsageQuery
from novelvideo.api.auth import AUTH_COOKIE_NAME
from novelvideo.api.routes.aigcdo_auth import AigcdoAPIRoute, require_aigcdo_account


def create_aigcdo_billing_router(billing: AigcdoBilling) -> APIRouter:
    async def boundary(request: Request):
        await require_aigcdo_account(request, billing.auth)

    router = APIRouter(prefix="/account/billing", route_class=AigcdoAPIRoute, dependencies=[Depends(boundary)])

    @router.get("/balance")
    async def balance(request: Request):
        if request.query_params:
            raise HTTPException(400, "Balance query does not accept filters")
        return {"ok": True, "data": await billing.balance(request.cookies.get(AUTH_COOKIE_NAME))}

    @router.get("/usage")
    async def usage(request: Request):
        if any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
            raise HTTPException(400, "Duplicate usage filter")
        try:
            query = GatewayUsageQuery.model_validate(dict(request.query_params))
        except ValidationError:
            raise HTTPException(400, "Invalid usage filters") from None
        return {
            "ok": True,
            "data": await billing.usage(request.cookies.get(AUTH_COOKIE_NAME), **query.model_dump()),
        }

    return router
