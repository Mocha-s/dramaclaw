import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  beginCheckoutAttempt, readCheckoutAttempt, clearCheckoutAttempt,
  amountWithinLimits, normalizedAmount, paymentReturnOrderId, safeCheckoutLink,
} from "@/lib/aigcdo-account";

describe("AIGCDO checkout attempt", () => {
  beforeEach(() => sessionStorage.clear());

  it("persists one attempt across retries and separates users", () => {
    const first = beginCheckoutAttempt("alice", "10.2", "alipay");
    expect(beginCheckoutAttempt("alice", "10.20", "alipay")).toEqual(first);
    expect(readCheckoutAttempt("alice")).toEqual(first);
    expect(beginCheckoutAttempt("bob", "10.20", "alipay").idempotencyKey).not.toBe(first.idempotencyKey);
    expect(() => beginCheckoutAttempt("alice", "11", "alipay")).toThrow();
    clearCheckoutAttempt("alice");
    expect(beginCheckoutAttempt("alice", "11", "alipay").idempotencyKey).not.toBe(first.idempotencyKey);
  });

  it("refuses creation when durable browser state cannot be written", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("full"); });
    try { expect(() => beginCheckoutAttempt("alice", "10", "alipay")).toThrow(); }
    finally { spy.mockRestore(); }
  });

  it.each(["0", "-1", "NaN", "Infinity", "1e2", "10.251", "1000000.01", "01.00"])(
    "rejects invalid amount %s", (value) => expect(() => normalizedAmount(value)).toThrow(),
  );
  it("formats without floating point conversion", () => {
    expect(normalizedAmount("10")).toBe("10.00");
    expect(normalizedAmount("0.01")).toBe("0.01");
    expect(normalizedAmount("1000000")).toBe("1000000.00");
  });
  it.each([
    ["0.99", "1", "1000", false],
    ["1", "1.00", "1e3", true],
    ["1000", "1", "1e3", true],
    ["1000.01", "1", "1e3", false],
    ["1", "1.000000000000000001", "0", false],
    ["1", "0", "0.999999999999999999", false],
    ["0.01", "1e-8", "0", true],
  ])("checks %s against exact limits %s–%s", (amount, minimum, maximum, accepted) => {
    expect(amountWithinLimits(amount, minimum, maximum)).toBe(accepted);
  });
  it.each(["NaN", "-1", "1e999", "1e1000000"])("fails closed on malformed limit %s", (limit) => {
    expect(() => amountWithinLimits("10", "0", limit)).toThrow();
  });
  it("does not trust payment status or ambiguous IDs in return URL", () => {
    expect(paymentReturnOrderId("?order_id=12&status=COMPLETED&sign=fake")).toBe("12");
    expect(paymentReturnOrderId("?order_id=12&order_id=13")).toBeNull();
    expect(paymentReturnOrderId("?out_trade_no=12&status=COMPLETED")).toBeNull();
    expect(paymentReturnOrderId("?order_id=../12")).toBeNull();
  });
  it.each(["javascript:alert(1)", "http://pay.example/", "https://user:pass@pay.example/", "//pay.example", "https://pay.example/ bad"])(
    "rejects unsafe payment links %s", (url) => expect(safeCheckoutLink(url)).toBeNull(),
  );
  it("allows a secure payment link", () => {
    expect(safeCheckoutLink("https://pay.example/pay?t=1")).toBe("https://pay.example/pay?t=1");
  });
});
