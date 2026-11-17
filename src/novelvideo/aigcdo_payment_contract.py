"""Whitelisted Sub2API balance-recharge wire contracts."""

from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

Money = Annotated[Decimal, Field(ge=0, le=Decimal("1e12"), allow_inf_nan=False)]
PositiveID = Annotated[int, Field(gt=0, strict=True)]
PaymentType = Literal["alipay", "wxpay"]
Status = Literal[
    "PENDING", "PAID", "RECHARGING", "COMPLETED", "EXPIRED", "CANCELLED", "FAILED",
    "REFUND_REQUESTED", "REFUNDING", "REFUND_PENDING", "PARTIALLY_REFUNDED", "REFUNDED", "REFUND_FAILED",
]


class PaymentDTO(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)


class PaymentMethod(PaymentDTO):
    payment_type: str
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    fee_rate: Money
    single_min: Money
    single_max: Money
    daily_limit: Money


class BonusTier(PaymentDTO):
    min_amount: Money
    bonus_percent: Annotated[Decimal, Field(ge=0, le=1000, allow_inf_nan=False)]


class GatewayCheckout(PaymentDTO):
    methods: dict[str, PaymentMethod]
    balance_disabled: Annotated[bool, Field(strict=True)]
    balance_recharge_multiplier: Annotated[Decimal, Field(gt=0, le=Decimal("1e12"), allow_inf_nan=False)]
    recharge_fee_rate: Money
    recharge_bonus_mode: Literal["bonus", "discount"]
    recharge_bonus_tiers: list[BonusTier]
    global_min: Money
    global_max: Money


class GatewayCreatedOrder(PaymentDTO):
    order_id: PositiveID
    amount: Money
    pay_amount: Money
    bonus_amount: Money
    fee_rate: Money
    # The gateway omits these two for some providers (Go `omitempty`); the order read is authoritative.
    currency: Annotated[str, Field(pattern=r"^([A-Z]{3})?$")] = ""
    payment_type: PaymentType
    out_trade_no: Annotated[str, Field(min_length=1, max_length=128)]
    status: Status
    result_type: Literal["order_created", ""] = ""
    expires_at: AwareDatetime
    pay_url: Annotated[str, Field(max_length=8192, repr=False)] = ""
    qr_code: Annotated[str, Field(max_length=8192, repr=False)] = ""

    @field_validator("pay_url", "qr_code")
    @classmethod
    def safe_checkout_url(cls, value: str, info):
        if not value:
            return value
        if any(ord(c) < 33 or ord(c) == 127 for c in value) or "\\" in value:
            raise ValueError("invalid payment URL")
        url = urlsplit(value)
        if url.username or url.password or not url.hostname:
            raise ValueError("invalid payment URL")
        if url.scheme != "https" and not (
            info.field_name == "qr_code" and url.scheme == "weixin"
            and url.netloc == "wxpay" and url.path == "/bizpayurl"
        ):
            raise ValueError("unsupported payment URL")
        return value


class GatewayPaymentOrder(PaymentDTO):
    id: PositiveID
    user_id: PositiveID
    amount: Money
    pay_amount: Money
    bonus_amount: Money
    fee_rate: Money
    refund_amount: Money
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    payment_type: str
    out_trade_no: Annotated[str, Field(min_length=1, max_length=128)]
    status: Status
    order_type: Literal["balance", "subscription"]
    created_at: AwareDatetime
    expires_at: AwareDatetime
    paid_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None


class GatewayOrderPage(PaymentDTO):
    items: list[GatewayPaymentOrder]
    page: PositiveID
    page_size: PositiveID
    pages: PositiveID
    total: Annotated[int, Field(ge=0, strict=True)]
