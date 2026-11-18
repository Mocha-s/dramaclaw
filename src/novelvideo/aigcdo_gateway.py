"""Server-side user authentication client for the AIGCDO gateway."""

from __future__ import annotations

from decimal import Decimal
from datetime import date
import logging
import re
from typing import Annotated, Any, Literal, TypeVar

import time
import httpx
from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    model_validator,
)


logger = logging.getLogger(__name__)

AUTH_SETTINGS_TTL = 60

_ERRORS = {
    "authentication_failed": (401, "Gateway authentication failed"),
    "access_denied": (403, "Gateway access denied"),
    "request_rejected": (400, "Gateway rejected the request"),
    "rate_limited": (429, "Too many gateway requests"),
    "gateway_unavailable": (503, "Gateway is temporarily unavailable"),
    "invalid_response": (502, "Gateway returned an invalid response"),
    "resource_not_found": (404, "Gateway resource not found"),
    "payment_pending": (503, "Order creation outcome needs reconciliation; do not resubmit"),
    "idempotency_conflict": (409, "Checkout attempt does not match the original request"),
    "payment_storage_unavailable": (503, "Payment request storage is unavailable"),
    "payment_not_submitted": (400, "No order was submitted; refresh checkout configuration"),
    "session_changed": (409, "Account session changed; reload account identity"),
}


class AigcdoGatewayError(Exception):
    """A safe error for callers; never contains an upstream body or credential."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.status_code, message = _ERRORS[code]
        super().__init__(message)


def _valid_token(value: str) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", value) is not None


def _validated_secret(value: SecretStr) -> SecretStr:
    if not _valid_token(value.get_secret_value()):
        raise ValueError("invalid credential format")
    return value


_Token = Annotated[SecretStr, AfterValidator(_validated_secret)]
_UserText = Annotated[str, Field(min_length=1, strict=True)]
_PositiveInt = Annotated[int, Field(gt=0, strict=True)]
_Amount = Annotated[Decimal, Field(allow_inf_nan=False)]


class GatewayUser(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    id: _PositiveInt
    email: _UserText
    role: Literal["user", "admin"]
    status: _UserText
    balance: _Amount
    frozen_balance: _Amount


class GatewaySessionTokens(BaseModel):
    """Gateway credentials for server-side storage, not a browser response DTO."""

    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    access_token: _Token
    refresh_token: _Token
    expires_in: _PositiveInt
    token_type: Literal["Bearer"]


class GatewaySession(GatewaySessionTokens):
    user: GatewayUser


class GatewayLoginChallenge(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    requires_2fa: Literal[True]
    temp_token: _Token


class GatewayLoginDocument(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)

    id: Annotated[str, Field(min_length=1, max_length=128)]
    title: Annotated[str, Field(min_length=1, max_length=256)]
    content_md: Annotated[str, Field(min_length=1, max_length=131072)]


class GatewayAuthSettings(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)

    registration_enabled: bool
    email_verify_enabled: bool
    invitation_code_enabled: bool
    turnstile_enabled: bool
    # Public by design: the browser needs it to render the widget.
    turnstile_site_key: Annotated[str, Field(max_length=128, pattern=r"^[A-Za-z0-9_-]*$")] = ""
    tencent_captcha_enabled: bool
    aliyun_captcha_enabled: bool
    login_agreement_enabled: bool
    login_agreement_revision: Annotated[str, Field(max_length=256)]
    login_agreement_documents: Annotated[list[GatewayLoginDocument], Field(max_length=10)]

    @model_validator(mode="after")
    def require_enabled_agreement(self):
        if self.login_agreement_enabled and (
            not self.login_agreement_revision or not self.login_agreement_documents
        ):
            raise ValueError("enabled agreement requires documents and revision")
        return self


class GatewayGroup(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    id: _PositiveInt
    name: _UserText
    platform: _UserText
    status: _UserText


class _GatewayGroups(BaseModel):
    items: list[GatewayGroup]


class GatewayAPIKey(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    id: _PositiveInt
    user_id: _PositiveInt
    group_id: _PositiveInt | None
    name: _UserText
    key: _Token
    status: _UserText
    expires_at: AwareDatetime | None


class GatewayKeyPage(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    items: list[GatewayAPIKey]
    total: Annotated[int, Field(ge=0, strict=True)]
    page: _PositiveInt
    page_size: _PositiveInt
    pages: Annotated[int, Field(ge=0, strict=True)]


class GatewayUsageRecord(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    id: _PositiveInt
    user_id: _PositiveInt
    request_id: Annotated[str, Field(strict=True, max_length=255)]
    model: _UserText
    actual_cost: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
    refunded_cost: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
    net_actual_cost: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
    billing_type: Annotated[int, Field(ge=0, le=1, strict=True)]
    created_at: AwareDatetime
    input_tokens: Annotated[int, Field(ge=0, strict=True)]
    output_tokens: Annotated[int, Field(ge=0, strict=True)]


class GatewayUsagePage(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    items: list[GatewayUsageRecord]
    total: Annotated[int, Field(ge=0, strict=True)]
    page: _PositiveInt
    page_size: _PositiveInt
    pages: Annotated[int, Field(ge=0, strict=True)]


class GatewayUsageQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    page: Annotated[int, Field(ge=1, le=1_000_000)] = 1
    page_size: Annotated[int, Field(ge=1, le=100)] = 20
    model: Annotated[str, Field(min_length=1, max_length=255, pattern=r"^\S+$")] | None = None
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start date is after end date")
        return self


_Model = TypeVar("_Model", bound=BaseModel)


def _parse(model: type[_Model], data: dict[str, Any]) -> _Model:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        # Pydantic errors can retain raw credential inputs; log field names and kinds only.
        logger.warning("AIGCDO gateway response did not match %s: %s", model.__name__, sorted({
            ".".join(str(part) for part in error["loc"]) + ":" + error["type"] for error in exc.errors()
        })[:12])
        raise AigcdoGatewayError("invalid_response") from None


class AigcdoGatewayClient:
    """Use user JWTs against a fixed origin; admin/model keys are not required."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = httpx.AsyncClient(
            base_url="https://api.aigcdo.top/api/v1/",
            timeout=httpx.Timeout(15.0, connect=5.0),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self._auth_settings: tuple[float, GatewayAuthSettings] | None = None

    async def __aenter__(self) -> AigcdoGatewayClient:
        await self._http.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._http.__aexit__(*args)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        access_token: str | None = None,
        params: dict[str, str | int] | None = None,
        idempotency_key: str | None = None,
        array_response: bool = False,
        referer: str | None = None,
    ) -> Any:
        if access_token is not None and not _valid_token(access_token):
            raise AigcdoGatewayError("authentication_failed")
        headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
        if referer is not None:
            headers["Referer"] = referer
        if idempotency_key is not None:
            if not _valid_token(idempotency_key) or len(idempotency_key) > 128:
                raise AigcdoGatewayError("request_rejected")
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = await self._http.request(method, path, json=body, headers=headers, params=params)
        except httpx.RequestError as exc:
            logger.warning("AIGCDO gateway unreachable for %s %s: %s", method, path, type(exc).__name__)
            raise AigcdoGatewayError("gateway_unavailable") from None

        if response.status_code >= 400:
            # Operators need the gateway's own reason; callers only ever get the safe code.
            try:
                reason = str(response.json().get("reason") or "")[:80]
            except (ValueError, AttributeError):
                reason = ""
            logger.warning(
                "AIGCDO gateway refused %s %s: HTTP %s %s", method, path, response.status_code,
                reason if re.fullmatch(r"[A-Za-z0-9_.-]*", reason) else "",
            )
        if response.status_code >= 500:
            raise AigcdoGatewayError("gateway_unavailable")
        if response.status_code in {401, 403, 404, 429}:
            code = {
                401: "authentication_failed",
                403: "access_denied",
                404: "resource_not_found",
                429: "rate_limited",
            }[response.status_code]
            raise AigcdoGatewayError(code)
        if response.status_code >= 400:
            raise AigcdoGatewayError("request_rejected")
        if not response.is_success:
            raise AigcdoGatewayError("invalid_response")
        try:
            envelope = response.json(parse_float=Decimal)
        except ValueError:
            raise AigcdoGatewayError("invalid_response") from None
        if not isinstance(envelope, dict):
            raise AigcdoGatewayError("invalid_response")
        code = envelope.get("code")
        if type(code) not in {int, str}:
            raise AigcdoGatewayError("invalid_response")
        if code != 0:
            raise AigcdoGatewayError("request_rejected")
        data = envelope.get("data")
        if not isinstance(data, list if array_response else dict):
            raise AigcdoGatewayError("invalid_response")
        return data

    async def public_auth_settings(self) -> GatewayAuthSettings:
        # The login page waits on this and the gateway link is slow and lossy: reuse the
        # last answer for a minute, and keep serving it while the gateway is unreachable.
        cached = self._auth_settings
        if cached and cached[0] > time.monotonic():
            return cached[1]
        try:
            settings = _parse(GatewayAuthSettings, await self._request("GET", "settings/public"))
        except AigcdoGatewayError as exc:
            if cached and exc.code == "gateway_unavailable":
                return cached[1]
            raise
        self._auth_settings = (time.monotonic() + AUTH_SETTINGS_TTL, settings)
        return settings

    async def login(
        self, email: str, password: str, *, turnstile_token: str = "",
    ) -> GatewaySession | GatewayLoginChallenge:
        data = await self._request(
            "POST", "auth/login",
            # Sent only when the gateway asked for one, so the wire is unchanged otherwise.
            body={"email": email, "password": password,
                  **({"turnstile_token": turnstile_token} if turnstile_token else {})},
        )
        if data.get("requires_2fa") is True:
            return _parse(GatewayLoginChallenge, data)
        if data.get("requires_2fa", False) is not False:
            raise AigcdoGatewayError("invalid_response")
        return _parse(GatewaySession, data)

    async def login_2fa(self, temp_token: str, code: str) -> GatewaySession:
        data = await self._request(
            "POST", "auth/login/2fa", body={"temp_token": temp_token, "totp_code": code}
        )
        return _parse(GatewaySession, data)

    async def register(
        self, email: str, password: str, *, verify_code: str = "", turnstile_token: str = "",
    ) -> GatewaySession:
        data = await self._request(
            "POST",
            "auth/register",
            body={"email": email, "password": password, "verify_code": verify_code,
                  **({"turnstile_token": turnstile_token} if turnstile_token else {})},
        )
        return _parse(GatewaySession, data)

    async def me(self, access_token: str) -> GatewayUser:
        data = await self._request("GET", "auth/me", access_token=access_token)
        return _parse(GatewayUser, data)

    async def refresh(self, refresh_token: str) -> GatewaySessionTokens:
        data = await self._request(
            "POST", "auth/refresh", body={"refresh_token": refresh_token}
        )
        return _parse(GatewaySessionTokens, data)

    async def logout(self, refresh_token: str) -> None:
        await self._request("POST", "auth/logout", body={"refresh_token": refresh_token})

    async def available_groups(self, access_token: str) -> list[GatewayGroup]:
        data = await self._request(
            "GET", "groups/available", access_token=access_token, array_response=True,
        )
        return _parse(_GatewayGroups, {"items": data}).items

    async def get_key(self, access_token: str, key_id: int) -> GatewayAPIKey:
        if type(key_id) is not int or key_id <= 0:
            raise AigcdoGatewayError("request_rejected")
        return _parse(GatewayAPIKey, await self._request(
            "GET", f"keys/{key_id}", access_token=access_token,
        ))

    async def find_keys(self, access_token: str, name: str) -> list[GatewayAPIKey]:
        found: list[GatewayAPIKey] = []
        for page in range(1, 11):
            data = await self._request(
                "GET", "keys", access_token=access_token,
                params={"search": name, "page": page, "page_size": 100},
            )
            result = _parse(GatewayKeyPage, data)
            if result.page != page or result.pages > 10:
                raise AigcdoGatewayError("invalid_response")
            found.extend(result.items)
            if page >= result.pages:
                if len(found) != result.total:
                    raise AigcdoGatewayError("invalid_response")
                return found
            if not result.items:
                raise AigcdoGatewayError("invalid_response")
        raise AigcdoGatewayError("invalid_response")

    async def create_key(
        self, access_token: str, *, name: str, group_id: int,
        custom_key: str, idempotency_key: str,
    ) -> GatewayAPIKey:
        if (
            type(group_id) is not int or group_id <= 0
            or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", custom_key)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", name)
        ):
            raise AigcdoGatewayError("request_rejected")
        return _parse(GatewayAPIKey, await self._request(
            "POST", "keys", access_token=access_token, idempotency_key=idempotency_key,
            body={"name": name, "group_id": group_id, "custom_key": custom_key},
        ))

    async def profile(self, access_token: str) -> GatewayUser:
        return _parse(GatewayUser, await self._request(
            "GET", "user/profile", access_token=access_token,
        ))

    async def usage(
        self, access_token: str, *, page: int = 1, page_size: int = 20,
        model: str | None = None, start_date: date | None = None, end_date: date | None = None,
    ) -> GatewayUsagePage:
        try:
            query = GatewayUsageQuery(
                page=page, page_size=page_size, model=model, start_date=start_date, end_date=end_date,
            )
        except ValidationError:
            raise AigcdoGatewayError("request_rejected") from None
        data = await self._request(
            "GET", "usage", access_token=access_token,
            params={**query.model_dump(mode="json", exclude_none=True), "timezone": "UTC"},
        )
        result = _parse(GatewayUsagePage, data)
        expected_count = max(0, min(page_size, result.total - (page - 1) * page_size))
        if (
            result.page != page or result.page_size != page_size
            or result.pages != max(1, (result.total + page_size - 1) // page_size)
            or len(result.items) != expected_count
            or len({item.id for item in result.items}) != len(result.items)
        ):
            raise AigcdoGatewayError("invalid_response")
        return result

    async def payment_checkout(self, access_token: str):
        from novelvideo.aigcdo_payment_contract import GatewayCheckout

        return _parse(GatewayCheckout, await self._request(
            "GET", "payment/checkout-info", access_token=access_token,
        ))

    async def create_payment_order(
        self, access_token: str, *, amount: Decimal, payment_type: str, app_origin: str,
    ):
        from novelvideo.aigcdo_payment_contract import GatewayCreatedOrder

        return _parse(GatewayCreatedOrder, await self._request(
            "POST", "payment/orders", access_token=access_token, referer=app_origin + "/",
            body={
                # Gateway's Go contract requires a JSON number; validated two-decimal input only.
                "amount": float(amount), "payment_type": payment_type, "order_type": "balance",
                "return_url": app_origin + "/payment/result", "is_mobile": False,
            },
        ))

    async def payment_order(self, access_token: str, order_id: int):
        from novelvideo.aigcdo_payment_contract import GatewayPaymentOrder

        if type(order_id) is not int or order_id <= 0:
            raise AigcdoGatewayError("request_rejected")
        return _parse(GatewayPaymentOrder, await self._request(
            "GET", f"payment/orders/{order_id}", access_token=access_token,
        ))

    async def payment_orders(self, access_token: str, *, page: int = 1, page_size: int = 20):
        from novelvideo.aigcdo_payment_contract import GatewayOrderPage

        if type(page) is not int or not 1 <= page <= 1_000_000 or type(page_size) is not int or not 1 <= page_size <= 100:
            raise AigcdoGatewayError("request_rejected")
        result = _parse(GatewayOrderPage, await self._request(
            "GET", "payment/orders/my", access_token=access_token,
            params={"page": page, "page_size": page_size, "order_type": "balance"},
        ))
        if (
            result.page != page or result.page_size != page_size
            or result.pages != max(1, (result.total + page_size - 1) // page_size)
            or len(result.items) != max(0, min(page_size, result.total - (page - 1) * page_size))
            or len({order.id for order in result.items}) != len(result.items)
        ):
            raise AigcdoGatewayError("invalid_response")
        return result

    async def cancel_payment_order(self, access_token: str, order_id: int) -> None:
        await self._request("POST", f"payment/orders/{order_id}/cancel", access_token=access_token, body={})

    async def verify_payment_order(self, access_token: str, out_trade_no: str):
        from novelvideo.aigcdo_payment_contract import GatewayPaymentOrder

        return _parse(GatewayPaymentOrder, await self._request(
            "POST", "payment/orders/verify", access_token=access_token, body={"out_trade_no": out_trade_no},
        ))
