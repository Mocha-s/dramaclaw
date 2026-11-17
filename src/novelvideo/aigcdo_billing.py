"""Read-only gateway billing projection; no local wallet or balance mutations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

from novelvideo.aigcdo_gateway import AigcdoGatewayError, GatewayUsageQuery
from novelvideo.aigcdo_sessions import AigcdoAuthPort


@dataclass(frozen=True)
class CreditDisplayPolicy:
    credits_per_unit: Decimal
    decimal_places: int
    version: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.credits_per_unit, Decimal)
            or not self.credits_per_unit.is_finite() or self.credits_per_unit <= 0
            or not Decimal("1e-12") <= self.credits_per_unit <= Decimal("1e12")
            or len(self.credits_per_unit.as_tuple().digits) > 28
            or type(self.decimal_places) is not int or not 0 <= self.decimal_places <= 8
            or not isinstance(self.version, str) or not self.version.strip() or len(self.version) > 64
        ):
            raise ValueError("Invalid credit display policy")

    def display(self, amount: Decimal) -> str:
        if not amount.is_finite() or amount.copy_abs() > Decimal("1e20"):
            raise AigcdoGatewayError("invalid_response")
        try:
            with localcontext() as context:
                context.prec = 64
                rounded = (amount * self.credits_per_unit).quantize(
                    Decimal(1).scaleb(-self.decimal_places), rounding=ROUND_HALF_UP,
                )
                return format(rounded.copy_abs() if rounded == 0 else rounded, "f")
        except InvalidOperation:
            raise AigcdoGatewayError("invalid_response") from None

    def metadata(self) -> dict:
        return {
            "credits_per_unit": str(self.credits_per_unit),
            "decimal_places": self.decimal_places, "rounding": "ROUND_HALF_UP", "version": self.version,
        }


class AigcdoBilling:
    def __init__(self, auth: AigcdoAuthPort, policy: CreditDisplayPolicy) -> None:
        self.auth = auth
        self.policy = policy

    async def balance(self, cookie: str | None) -> dict:
        await self.auth.verify_session(cookie)
        session = await self.auth.store.load(cookie)
        user = await self.auth.gateway.profile(session.tokens.access_token.get_secret_value())
        await self.auth.store.confirm_identity(session, user)
        if user.frozen_balance < 0:
            raise AigcdoGatewayError("invalid_response")
        available = self.policy.display(user.balance)
        frozen = self.policy.display(user.frozen_balance)
        return {
            "ledger_unit": "USD", "available_amount": str(user.balance),
            "frozen_amount": str(user.frozen_balance),
            "available_credits": available, "frozen_credits": frozen,
            "policy": self.policy.metadata(),
        }

    async def usage(self, cookie: str | None, **filters) -> dict:
        query = GatewayUsageQuery.model_validate(filters)
        await self.auth.verify_session(cookie)
        session = await self.auth.store.load(cookie)
        page = await self.auth.gateway.usage(
            session.tokens.access_token.get_secret_value(), **query.model_dump(),
        )
        if any(item.user_id != session.gateway_id for item in page.items):
            raise AigcdoGatewayError("invalid_response")
        items = []
        for item in page.items:
            net = self.policy.display(item.net_actual_cost)
            # Validate display bounds for all monetary values, not only net cost.
            self.policy.display(item.actual_cost)
            self.policy.display(item.refunded_cost)
            items.append({
                "id": str(item.id), "request_id": item.request_id, "model": item.model,
                "occurred_at": item.created_at.isoformat(),
                "billing_type": "wallet" if item.billing_type == 0 else "subscription",
                "charged_amount": str(item.actual_cost), "refunded_amount": str(item.refunded_cost),
                "net_amount": str(item.net_actual_cost), "net_credits": net,
                "wallet_debit_credits": net if item.billing_type == 0 else self.policy.display(Decimal(0)),
                "input_tokens": item.input_tokens, "output_tokens": item.output_tokens,
            })
        await self.auth.store.load(cookie)
        return {
            "items": items, "total": page.total, "page": page.page,
            "page_size": page.page_size, "pages": page.pages,
            "ledger_unit": "USD", "policy": self.policy.metadata(),
            "filters": {**query.model_dump(mode="json", exclude={"page", "page_size"}, exclude_none=True),
                        "timezone": "UTC"},
        }
