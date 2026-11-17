import { fireEvent, render, screen, waitFor, cleanup, within, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ky from "ky";
import i18n from "i18next";
import { server } from "@/__mocks__/msw/server";
import { AigcdoAccountPage, AigcdoPaymentResult } from "@/components/aigcdo/account-page";
import zh from "../../../../public/locales/zh/account.json";
import { readCheckoutAttempt } from "@/lib/aigcdo-account";

vi.mock("@/lib/api", () => ({
  api: ky.create({ baseUrl: "http://localhost:3000/", credentials: "include" }),
}));

const policy = { credits_per_unit: "100", decimal_places: 4, rounding: "ROUND_HALF_UP", version: "v1" };
const order = {
  id: "1", credits: "2255.0000", pay_amount: "10.25", currency: "CNY",
  payment_type: "alipay", out_trade_no: "trade-1", status: "PENDING", fulfilled: false,
  created_at: "2026-11-15T00:00:00Z", expires_at: "2099-11-15T00:30:00Z",
  paid_at: null, completed_at: null,
};
const ok = (data: unknown) => HttpResponse.json({ ok: true, data });
const pages = { page: 1, page_size: 20, pages: 1, total: 1 };

function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: {
    queries: { retry: false }, mutations: { retry: false },
  } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  sessionStorage.clear();
  i18n.addResourceBundle("zh", "account", zh, true, true);
  server.use(
    http.get("*/api/v1/auth/me", () => ok({ id: "alice", username: "alice", role: "user" })),
    http.get("*/api/v1/account/billing/balance", () => ok({
      ledger_unit: "USD", available_amount: "12.34567891", frozen_amount: "2",
      available_credits: "1234.5679", frozen_credits: "200.0000", policy,
    })),
    http.get("*/api/v1/account/billing/usage", () => ok({ items: [{
      id: "101", request_id: "request-1", model: "image-model", occurred_at: order.created_at,
      billing_type: "subscription", charged_amount: "0.1", refunded_amount: "0", net_amount: "0.1",
      net_credits: "10.0000", wallet_debit_credits: "0.0000",
    }], ...pages })),
    http.get("*/api/v1/account/payments/checkout", () => ok({
      methods: { alipay: { payment_type: "alipay", currency: "CNY", single_min: "1", single_max: "1000", fee_rate: "0", daily_limit: "5000" } },
      balance_disabled: false, balance_recharge_multiplier: "2", recharge_fee_rate: "0",
      recharge_bonus_mode: "bonus", recharge_bonus_tiers: [], global_min: "1", global_max: "1000", policy,
    })),
    http.get("*/api/v1/account/payments/orders", () => ok({ items: [order], ...pages })),
    http.get("*/api/v1/account/payments/orders/1", () => ok(order)),
  );
});
afterEach(cleanup);

describe("AIGCDO account", () => {
  it("shows exact balances and labels subscription usage separately", async () => {
    mount(<AigcdoAccountPage userId="alice" />);
    expect(await screen.findByText("1234.5679")).toBeInTheDocument();
    expect(screen.getByText("200.0000")).toBeInTheDocument();
    expect(await screen.findByText("订阅用量")).toBeInTheDocument();
    expect(screen.getByText("0.0000")).toBeInTheDocument();
  });

  it("keeps the original attempt on timeout and retry, including after remount", async () => {
    const keys: (string | null)[] = [];
    server.use(http.post("*/api/v1/account/payments/orders", async ({ request }) => {
      keys.push(request.headers.get("Idempotency-Key"));
      expect(await request.json()).toEqual({ amount: "10.25", payment_type: "alipay" });
      return HttpResponse.json({ ok: false, code: "payment_pending" }, { status: 503 });
    }));
    const view = mount(<AigcdoAccountPage userId="alice" />);
    fireEvent.change(await screen.findByLabelText("充值金额（CNY）"), { target: { value: "10.25" } });
    fireEvent.click(screen.getByRole("button", { name: "创建充值订单" }));
    expect(await screen.findByText(/订单可能已经创建/)).toBeInTheDocument();
    expect(screen.getByLabelText("充值金额（CNY）")).toBeDisabled();
    view.unmount();
    mount(<AigcdoAccountPage userId="alice" />);
    fireEvent.click(await screen.findByRole("button", { name: "重试原操作" }));
    await waitFor(() => expect(keys).toHaveLength(2));
    expect(keys[0]).toBe(keys[1]);
    expect(keys[0]).toMatch(/^checkout-/);
  });

  it("shows credited amount without double counting bonus and never trusts unsafe checkout link", async () => {
    server.use(http.post("*/api/v1/account/payments/orders", () => ok({
      order, expected_credits: "2255.0000", policy,
      checkout: { pay_url: "javascript:alert(1)", qr_code: "" },
    })));
    mount(<AigcdoAccountPage userId="alice" />);
    fireEvent.change(await screen.findByLabelText("充值金额（CNY）"), { target: { value: "10.25" } });
    fireEvent.click(screen.getByRole("button", { name: "创建充值订单" }));
    expect(await screen.findByText(/2255.0000/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "前往支付" })).not.toBeInTheDocument();
    expect(screen.queryByText("已到账")).not.toBeInTheDocument();
  });

  it("does not show a zero balance when the gateway is unavailable", async () => {
    server.use(http.get("*/api/v1/account/billing/balance", () => HttpResponse.json(
      { ok: false, code: "gateway_unavailable" }, { status: 503 },
    )));
    mount(<AigcdoAccountPage userId="alice" />);
    expect(await screen.findByText("余额暂不可用，请重试")).toBeInTheDocument();
    expect(screen.queryByText("1234.5679")).not.toBeInTheDocument();
  });

  it("prevents posting when attempt storage fails", async () => {
    let posts = 0;
    server.use(http.post("*/api/v1/account/payments/orders", () => {
      posts += 1;
      return ok({});
    }));
    mount(<AigcdoAccountPage userId="alice" />);
    fireEvent.change(await screen.findByLabelText("充值金额（CNY）"), { target: { value: "10.25" } });
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("full"); });
    try {
      fireEvent.click(screen.getByRole("button", { name: "创建充值订单" }));
      expect(await screen.findByText(/无法保存下单操作/)).toBeInTheDocument();
      expect(posts).toBe(0);
    } finally { spy.mockRestore(); }
  });

  it("does not reuse the previous user's recharge attempt when the account changes", async () => {
    server.use(http.post("*/api/v1/account/payments/orders", () =>
      HttpResponse.json({ ok: false, code: "payment_pending" }, { status: 503 })));
    const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = render(<QueryClientProvider client={query}><AigcdoAccountPage userId="alice" /></QueryClientProvider>);
    fireEvent.change(await screen.findByLabelText("充值金额（CNY）"), { target: { value: "10.25" } });
    fireEvent.click(screen.getByRole("button", { name: "创建充值订单" }));
    expect(await screen.findByText(/订单可能已经创建/)).toBeInTheDocument();
    view.rerender(<QueryClientProvider client={query}><AigcdoAccountPage userId="bob" /></QueryClientProvider>);
    expect(await screen.findByRole("button", { name: "创建充值订单" })).toBeInTheDocument();
    expect(screen.getByLabelText("充值金额（CNY）")).toHaveValue("");
    expect(screen.queryByText(/订单可能已经创建/)).not.toBeInTheDocument();
  });

  it("hides payment link after the latest order becomes credited", async () => {
    let current = order;
    server.use(
      http.post("*/api/v1/account/payments/orders", () => ok({
        order, expected_credits: "2255.0000", policy,
        checkout: { pay_url: "https://cashier.example.test/pay", qr_code: "" },
      })),
      http.get("*/api/v1/account/payments/orders/1", () => ok(current)),
      http.post("*/api/v1/account/payments/orders/1/verify", () => {
        current = { ...order, status: "COMPLETED", fulfilled: true };
        return ok(current);
      }),
    );
    mount(<AigcdoAccountPage userId="alice" />);
    fireEvent.change(await screen.findByLabelText("充值金额（CNY）"), { target: { value: "10.25" } });
    fireEvent.click(screen.getByRole("button", { name: "创建充值订单" }));
    expect(await screen.findByRole("link", { name: "前往支付" })).toHaveAttribute("href", "https://cashier.example.test/pay");
    fireEvent.click(screen.getByRole("button", { name: "查询支付结果" }));
    await screen.findByRole("button", { name: "创建另一笔充值" });
    expect(screen.queryByRole("link", { name: "前往支付" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "创建另一笔充值" }));
    expect(screen.getByRole("button", { name: "创建充值订单" })).toBeInTheDocument();
  });

  it("rejects below-minimum amounts before persisting or submitting an attempt", async () => {
    let posts = 0;
    server.use(http.post("*/api/v1/account/payments/orders", () => {
      posts += 1;
      return HttpResponse.json({ ok: false, code: "request_rejected" }, { status: 400 });
    }));
    mount(<AigcdoAccountPage userId="alice" />);
    const amount = await screen.findByLabelText("充值金额（CNY）");
    fireEvent.change(amount, { target: { value: "0.50" } });
    fireEvent.click(screen.getByRole("button", { name: "创建充值订单" }));
    expect(await screen.findByText("请输入有效金额，最多两位小数")).toBeInTheDocument();
    expect(amount).not.toBeDisabled();
    expect(readCheckoutAttempt("alice")).toBeNull();
    expect(posts).toBe(0);
  });

  it("unlocks only when the server proves this attempt was never submitted", async () => {
    server.use(http.post("*/api/v1/account/payments/orders", () =>
      HttpResponse.json({ ok: false, code: "payment_not_submitted" }, { status: 400 })));
    mount(<AigcdoAccountPage userId="alice" />);
    const amount = await screen.findByLabelText("充值金额（CNY）");
    fireEvent.change(amount, { target: { value: "10.25" } });
    fireEvent.click(screen.getByRole("button", { name: "创建充值订单" }));
    await screen.findByText("请求未完成，请刷新订单并重试原操作");
    expect(amount).not.toBeDisabled();
    expect(readCheckoutAttempt("alice")).toBeNull();
  });

  it("keeps an uncertain attempt locked on a generic rejection", async () => {
    server.use(http.post("*/api/v1/account/payments/orders", () =>
      HttpResponse.json({ ok: false, code: "request_rejected" }, { status: 400 })));
    mount(<AigcdoAccountPage userId="alice" />);
    const amount = await screen.findByLabelText("充值金额（CNY）");
    fireEvent.change(amount, { target: { value: "10.25" } });
    fireEvent.click(screen.getByRole("button", { name: "创建充值订单" }));
    await screen.findByText(/订单可能已经创建/);
    expect(amount).toBeDisabled();
    expect(readCheckoutAttempt("alice")).not.toBeNull();
  });

  it.each(["focus", "storage"])("refreshes identity and clears private UI on %s", async (event) => {
    let cookieIdentity = "alice";
    server.use(
      http.get("*/api/v1/auth/me", () => ok({ id: cookieIdentity, username: cookieIdentity, role: "user" })),
      http.post("*/api/v1/account/payments/orders", () =>
        HttpResponse.json({ ok: false, code: "payment_pending" }, { status: 503 })),
    );
    mount(<AigcdoAccountPage userId="alice" />);
    fireEvent.change(await screen.findByLabelText("充值金额（CNY）"), { target: { value: "10.25" } });
    fireEvent.click(screen.getByRole("button", { name: "创建充值订单" }));
    await screen.findByText(/订单可能已经创建/);
    cookieIdentity = "bob";
    fireEvent(window, new Event(event));
    await screen.findByRole("button", { name: "创建充值订单" });
    expect(screen.getByLabelText("充值金额（CNY）")).toHaveValue("");
    expect(screen.queryByText(/订单可能已经创建/)).not.toBeInTheDocument();
    expect(readCheckoutAttempt("alice")).not.toBeNull();
    expect(readCheckoutAttempt("bob")).toBeNull();
  });

  it("detects cookie identity changes before recovering the previous user's attempt", async () => {
    let cookieIdentity = "alice";
    const posts: { identity: string; key: string | null }[] = [];
    server.use(
      http.get("*/api/v1/auth/me", () => ok({ id: cookieIdentity, username: cookieIdentity, role: "user" })),
      http.post("*/api/v1/account/payments/orders", ({ request }) => {
        posts.push({ identity: cookieIdentity, key: request.headers.get("Idempotency-Key") });
        return HttpResponse.json({ ok: false, code: "payment_pending" }, { status: 503 });
      }),
    );
    mount(<AigcdoAccountPage userId="alice" />);
    fireEvent.change(await screen.findByLabelText("充值金额（CNY）"), { target: { value: "10.25" } });
    fireEvent.click(screen.getByRole("button", { name: "创建充值订单" }));
    await screen.findByText(/订单可能已经创建/);
    expect(posts).toHaveLength(1);
    cookieIdentity = "bob";
    // No prop change or browser focus event: the mutation itself must recheck identity.
    fireEvent.click(screen.getByRole("button", { name: "重试原操作" }));
    await screen.findByRole("button", { name: "创建充值订单" });
    expect(posts).toHaveLength(1);
    expect(readCheckoutAttempt("alice")).not.toBeNull();
    expect(readCheckoutAttempt("bob")).toBeNull();
    expect(screen.getByLabelText("充值金额（CNY）")).toHaveValue("");
  });

  it("binds account requests to the page identity even if cookies changed after preflight", async () => {
    const identities: (string | null)[] = [];
    server.use(http.get("*/api/v1/account/billing/balance", ({ request }) => {
      identities.push(request.headers.get("X-AIGCDO-User-ID"));
      return HttpResponse.json({ ok: false, code: "session_changed" }, { status: 409 });
    }));
    mount(<AigcdoAccountPage userId="alice" />);
    await waitFor(() => expect(identities.length).toBeGreaterThan(0));
    expect(identities.every((value) => value === "alice")).toBe(true);
    await screen.findByText("暂时无法加载，请重试");
    expect(screen.queryByLabelText("充值金额（CNY）")).not.toBeInTheDocument();
    expect(identities).toHaveLength(1);
  });

  it("cancels pending reads so they cannot restore payment links after verification", async () => {
    let delayed = false;
    let release!: () => void;
    let entered!: () => void;
    const started = new Promise<void>((resolve) => { entered = resolve; });
    const gate = new Promise<void>((resolve) => { release = resolve; });
    server.use(
      http.post("*/api/v1/account/payments/orders", () => ok({
        order, expected_credits: "2255.0000", policy,
        checkout: { pay_url: "https://cashier.example.test/pay", qr_code: "" },
      })),
      http.get("*/api/v1/account/payments/orders/1", async () => {
        if (delayed) { entered(); await gate; }
        return ok(order);
      }),
      http.post("*/api/v1/account/payments/orders/1/verify", () => ok({
        ...order, status: "COMPLETED", fulfilled: true,
      })),
    );
    mount(<AigcdoAccountPage userId="alice" />);
    fireEvent.change(await screen.findByLabelText("充值金额（CNY）"), { target: { value: "10.25" } });
    fireEvent.click(screen.getByRole("button", { name: "创建充值订单" }));
    await screen.findByRole("link", { name: "前往支付" });
    const panel = screen.getByRole("button", { name: "查询支付结果" }).closest("section")!;
    delayed = true;
    fireEvent.click(within(panel).getByRole("button", { name: "刷新" }));
    await started;
    fireEvent.click(within(panel).getByRole("button", { name: "查询支付结果" }));
    await within(panel).findByText("已到账");
    await act(async () => { release(); await gate; });
    await waitFor(() => expect(within(panel).queryByText("等待支付")).not.toBeInTheDocument());
    expect(within(panel).queryByRole("link", { name: "前往支付" })).not.toBeInTheDocument();
  });
});

describe("AIGCDO payment result", () => {
  it("does not infer success from a payment return hint", async () => {
    mount(<AigcdoPaymentResult userId="alice" orderId="1" />);
    expect(await screen.findByText("等待支付")).toBeInTheDocument();
    expect(screen.queryByText("已到账")).not.toBeInTheDocument();
  });

  it("only displays credited after gateway verification completes", async () => {
    server.use(http.get("*/api/v1/account/payments/orders/1", () => ok({ ...order, status: "PAID" })));
    server.use(http.post("*/api/v1/account/payments/orders/1/verify", async ({ request }) => {
      expect(await request.json()).toEqual({});
      return ok({ ...order, status: "COMPLETED", fulfilled: true });
    }));
    mount(<AigcdoPaymentResult userId="alice" orderId="1" />);
    expect(await screen.findByText("已支付，等待到账")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查询支付结果" }));
    expect(await screen.findByText("已到账")).toBeInTheDocument();
  });

  it("shows recovery guidance for missing order instead of creating an order", () => {
    mount(<AigcdoPaymentResult userId="alice" orderId={null} />);
    expect(screen.getByText("缺少有效订单号，请到账户订单中查询")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "查询支付结果" })).not.toBeInTheDocument();
  });
});
