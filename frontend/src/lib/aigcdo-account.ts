import { z } from "zod";
import { generateClientId } from "@/lib/client-id";

const attemptSchema = z.object({
  amount: z.string().regex(/^(0|[1-9]\d{0,6})\.\d{2}$/),
  paymentType: z.enum(["alipay", "wxpay"]),
  idempotencyKey: z.string().regex(/^[A-Za-z0-9_-]{16,128}$/),
});
export type CheckoutAttempt = z.infer<typeof attemptSchema>;
const storageKey = (userId: string) => `aigcdo-checkout:${encodeURIComponent(userId)}`;

export function normalizedAmount(value: string): string {
  if (!/^(0|[1-9]\d{0,6})(\.\d{1,2})?$/.test(value)) throw new Error("invalid_amount");
  const [whole, fraction = ""] = value.split(".");
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  if (cents <= 0n || cents > 100000000n) throw new Error("invalid_amount");
  return `${whole}.${fraction.padEnd(2, "0")}`;
}

function decimalParts(value: string): { coefficient: bigint; exponent: number } {
  const match = /^(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d{1,3}))?$/.exec(value);
  if (!match || value.length > 128) throw new Error("invalid_limit");
  const exponent = Number(match[3] ?? 0) - (match[2]?.length ?? 0);
  if (Math.abs(exponent) > 128) throw new Error("invalid_limit");
  return { coefficient: BigInt(match[1] + (match[2] ?? "")), exponent };
}

export function amountWithinLimits(value: string, minimum: string, maximum: string): boolean {
  const amount = decimalParts(normalizedAmount(value));
  const compare = (limit: ReturnType<typeof decimalParts>) => {
    const scale = Math.min(amount.exponent, limit.exponent);
    const a = amount.coefficient * 10n ** BigInt(amount.exponent - scale);
    const b = limit.coefficient * 10n ** BigInt(limit.exponent - scale);
    return a < b ? -1 : a > b ? 1 : 0;
  };
  const min = decimalParts(minimum), max = decimalParts(maximum);
  return compare(min) >= 0 && (max.coefficient === 0n || compare(max) <= 0);
}

export function readCheckoutAttempt(userId: string): CheckoutAttempt | null {
  const raw = sessionStorage.getItem(storageKey(userId));
  if (!raw) return null;
  // Corrupt state fails closed; replacing it could repeat an uncertain order.
  const value = attemptSchema.parse(JSON.parse(raw));
  normalizedAmount(value.amount);
  return value;
}

export function beginCheckoutAttempt(userId: string, amount: string, paymentType: "alipay" | "wxpay"): CheckoutAttempt {
  const normalized = normalizedAmount(amount);
  const existing = readCheckoutAttempt(userId);
  if (existing) {
    if (existing.amount !== normalized || existing.paymentType !== paymentType) throw new Error("attempt_pending");
    return existing;
  }
  const next = attemptSchema.parse({
    amount: normalized, paymentType, idempotencyKey: `checkout-${generateClientId()}`,
  });
  sessionStorage.setItem(storageKey(userId), JSON.stringify(next));
  return next;
}

export function clearCheckoutAttempt(userId: string): void {
  sessionStorage.removeItem(storageKey(userId));
}

export function paymentReturnOrderId(search: string): string | null {
  const values = new URLSearchParams(search).getAll("order_id");
  return values.length === 1 && /^[1-9]\d{0,17}$/.test(values[0]) ? values[0] : null;
}

export function safeCheckoutLink(value: string): string | null {
  if (/[\s\\\u0000-\u001f\u007f]/.test(value)) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

export function safeQrPayload(value: string): string | null {
  if (!value || value.length > 8192 || /[\s\\\u0000-\u001f\u007f]/.test(value)) return null;
  if (safeCheckoutLink(value)) return value;
  try {
    const url = new URL(value);
    return url.protocol === "weixin:" && url.host === "wxpay" && url.pathname === "/bizpayurl" &&
      !url.username && !url.password ? value : null;
  } catch { return null; }
}
