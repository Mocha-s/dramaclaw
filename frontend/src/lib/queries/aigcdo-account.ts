import { z } from "zod";
import { api } from "@/lib/api";
import type { CheckoutAttempt } from "@/lib/aigcdo-account";

const decimal = z.string().max(128).regex(/^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$/);
const id = z.string().regex(/^[1-9]\d{0,17}$/);
const timestamp = z.string().datetime({ offset: true });
export const accountIdentitySchema = z.object({ id: z.string().min(1), username: z.string(), role: z.string() });
export const balanceSchema = z.object({
  available_credits: decimal, frozen_credits: decimal,
});
const method = z.object({
  payment_type: z.string(), currency: z.string().regex(/^[A-Z]{3}$/),
  single_min: decimal, single_max: decimal, fee_rate: decimal, daily_limit: decimal,
});
export const checkoutSchema = z.object({
  methods: z.record(z.string(), method), balance_disabled: z.boolean(),
  balance_recharge_multiplier: decimal, recharge_fee_rate: decimal,
  recharge_bonus_mode: z.enum(["bonus", "discount"]),
  recharge_bonus_tiers: z.array(z.object({ min_amount: decimal, bonus_percent: decimal })),
  global_min: decimal, global_max: decimal,
});
export const orderSchema = z.object({
  id, credits: decimal, pay_amount: decimal,
  currency: z.string().regex(/^[A-Z]{3}$/), payment_type: z.string(), out_trade_no: z.string(),
  status: z.enum(["PENDING", "PAID", "RECHARGING", "COMPLETED", "EXPIRED", "CANCELLED", "FAILED",
    "REFUND_REQUESTED", "REFUNDING", "REFUND_PENDING", "PARTIALLY_REFUNDED", "REFUNDED", "REFUND_FAILED"]),
  fulfilled: z.boolean(), created_at: timestamp, expires_at: timestamp,
  paid_at: timestamp.nullable(), completed_at: timestamp.nullable(),
});
export type AccountOrder = z.infer<typeof orderSchema>;
export const createdSchema = z.object({
  order: orderSchema, checkout: z.object({ pay_url: z.string(), qr_code: z.string() }).nullable(),
});
const pagination = { page: z.number().int().positive(), page_size: z.number().int().positive(),
  pages: z.number().int().positive(), total: z.number().int().nonnegative() };
export const ordersSchema = z.object({ items: z.array(orderSchema), ...pagination });
export const usageSchema = z.object({
  items: z.array(z.object({
    id, request_id: z.string(), model: z.string(), occurred_at: timestamp,
    billing_type: z.enum(["wallet", "subscription"]), net_credits: decimal,
    wallet_debit_credits: decimal,
  })), ...pagination,
});

export class AccountApiError extends Error {
  constructor(public readonly code: string, public readonly status: number) {
    super(code);
  }
}

export const ACCOUNT_SESSION_CHANGED = "aigcdo-account-session-changed";

function sessionChanged() {
  window.dispatchEvent(new Event(ACCOUNT_SESSION_CHANGED));
  return new AccountApiError("session_changed", 409);
}

async function assertIdentity(userId: string, signal?: AbortSignal): Promise<void> {
  const user = await accountApi.identity(signal);
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
  if (user.id !== userId) throw sessionChanged();
}

export async function request<T extends z.ZodType>(
  path: string, schema: T, options: {
    signal?: AbortSignal; json?: object; headers?: Record<string, string>; expectedUserId?: string;
  } = {},
): Promise<z.infer<T>> {
  const { expectedUserId, ...transportOptions } = options;
  const response = await api(path, {
    ...transportOptions, method: options.json ? "POST" : "GET", retry: 0, throwHttpErrors: false,
    headers: { ...options.headers, ...(expectedUserId ? { "X-AIGCDO-User-ID": expectedUserId } : {}) },
  });
  const body: unknown = await response.json().catch(() => null);
  const envelope = z.object({ ok: z.boolean(), code: z.string().optional(), data: z.unknown().optional() }).safeParse(body);
  if (!response.ok || !envelope.success || !envelope.data.ok) {
    if (envelope.success && envelope.data.code === "session_changed") throw sessionChanged();
    throw new AccountApiError(envelope.success ? envelope.data.code ?? "request_failed" : "invalid_response", response.status);
  }
  const parsed = schema.safeParse(envelope.data.data);
  if (!parsed.success) throw new AccountApiError("invalid_response", 502);
  return parsed.data;
}

const root = "api/v1/account";
export const accountApi = {
  identity: (signal?: AbortSignal) => request("api/v1/auth/me", accountIdentitySchema, { signal }),
  balance: (userId: string, signal?: AbortSignal) => request(`${root}/billing/balance`, balanceSchema, { signal, expectedUserId: userId }),
  usage: (userId: string, page: number, signal?: AbortSignal) => request(`${root}/billing/usage?page=${page}&page_size=20`, usageSchema, { signal, expectedUserId: userId }),
  checkout: (userId: string, signal?: AbortSignal) => request(`${root}/payments/checkout`, checkoutSchema, { signal, expectedUserId: userId }),
  orders: (userId: string, page: number, signal?: AbortSignal) => request(`${root}/payments/orders?page=${page}&page_size=20`, ordersSchema, { signal, expectedUserId: userId }),
  order: (userId: string, orderId: string, signal?: AbortSignal) => request(`${root}/payments/orders/${id.parse(orderId)}`, orderSchema, { signal, expectedUserId: userId }),
  verify: async (userId: string, orderId: string, signal?: AbortSignal) => {
    await assertIdentity(userId, signal);
    return request(`${root}/payments/orders/${id.parse(orderId)}/verify`, orderSchema, { json: {}, signal, expectedUserId: userId });
  },
  create: async (userId: string, attempt: CheckoutAttempt, signal?: AbortSignal) => {
    await assertIdentity(userId, signal);
    return request(`${root}/payments/orders`, createdSchema, {
      json: { amount: attempt.amount, payment_type: attempt.paymentType },
      headers: { "Idempotency-Key": attempt.idempotencyKey }, signal, expectedUserId: userId,
    });
  },
};
export const accountQueryKey = (userId: string, ...parts: (string | number)[]) => ["aigcdo-account", userId, ...parts];
export const orderIsProcessing = (order: AccountOrder) => ["PENDING", "PAID", "RECHARGING"].includes(order.status);
export const orderIsCredited = (order: AccountOrder) => order.status === "COMPLETED" && order.fulfilled;
