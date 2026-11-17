import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import QRCode from "qrcode";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  amountWithinLimits, beginCheckoutAttempt, clearCheckoutAttempt, readCheckoutAttempt,
  safeCheckoutLink, safeQrPayload, type CheckoutAttempt,
} from "@/lib/aigcdo-account";
import {
  ACCOUNT_SESSION_CHANGED, AccountApiError, accountApi, accountQueryKey, orderIsCredited, orderIsProcessing,
  type AccountOrder,
} from "@/lib/queries/aigcdo-account";
import { SESSION_EXPIRED_EVENT } from "@/lib/session-expiry";

// Same surface, table and muted-text treatment as the app's own billing views (BillingOrdersTab).
const panel = "rounded-lg border border-white/10 bg-white/[0.03] p-5 text-foreground";
const heading = "text-base font-semibold text-white";
const muted = "text-sm text-white/50";
const queryOptions = { retry: false as const, staleTime: 0, gcTime: 0 };
type Created = Awaited<ReturnType<typeof accountApi.create>>;

// Inside the account dialog the frame is the dialog itself: no page chrome.
const InDialog = createContext(false);

function PageFrame({ title, children }: { title: string; children: React.ReactNode }) {
  const { t } = useTranslation("account");
  if (useContext(InDialog)) return <div className="flex flex-col gap-5">{children}</div>;
  return <main id="main-content" tabIndex={-1} className="h-dvh overflow-y-auto overflow-x-hidden ui-scrollbar bg-background px-6 py-8 text-foreground">
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[28px] font-semibold tracking-tight text-white">{title}</h1>
        <a className="rounded-md border border-white/10 px-3 py-1.5 text-sm text-white/72 transition-colors hover:bg-white/[0.05] hover:text-white" href="/">{t("home")}</a>
      </header>
      {children}
    </div>
  </main>;
}

function Pager({ page, pages, change }: { page: number; pages: number; change: (page: number) => void }) {
  const { t } = useTranslation("account");
  return <div className="mt-3 flex items-center justify-end gap-2 text-sm text-white/50">
    <Button variant="outline" onClick={() => change(page - 1)} disabled={page <= 1}>{t("previous")}</Button>
    <span>{t("page", { page, pages })}</span>
    <Button variant="outline" onClick={() => change(page + 1)} disabled={page >= pages}>{t("next")}</Button>
  </div>;
}

function PaymentQr({ value }: { value: string }) {
  const { t } = useTranslation("account");
  const [image, setImage] = useState("");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    setImage("");
    setFailed(false);
    void QRCode.toDataURL(value, { width: 256, margin: 2 }).then(
      (url) => { if (active) setImage(url); },
      () => { if (active) setFailed(true); },
    );
    return () => { active = false; };
  }, [value]);
  return failed ? <p role="alert">{t("qrError")}</p> :
    image ? <img src={image} alt={t("qr")} className="size-64 max-w-full rounded-md" /> : <p>{t("loading")}</p>;
}

function OrderPanel({ userId, orderId, checkout, onOrder }: {
  userId: string; orderId: string; checkout?: Created["checkout"];
  onOrder?: (order: AccountOrder) => void;
}) {
  const { t } = useTranslation("account");
  const client = useQueryClient();
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState(false);
  const [now, setNow] = useState(Date.now);
  const abort = useRef<AbortController | null>(null);
  const query = useQuery({
    queryKey: accountQueryKey(userId, "order", orderId),
    queryFn: ({ signal }) => accountApi.order(userId, orderId, signal), ...queryOptions,
    enabled: !checking, staleTime: 5000,
    refetchInterval: (q) => checking || q.state.error || !q.state.data || !orderIsProcessing(q.state.data) ? false : 5000,
  });
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => { window.clearInterval(timer); abort.current?.abort(); };
  }, []);
  const order = query.data;
  useEffect(() => {
    if (!order) return;
    onOrder?.(order);
    if (orderIsCredited(order)) {
      void client.invalidateQueries({ queryKey: accountQueryKey(userId, "balance") });
      void client.invalidateQueries({ queryKey: accountQueryKey(userId, "orders") });
    }
  }, [order, onOrder, client, userId]);
  async function verify() {
    if (abort.current) return;
    const controller = new AbortController();
    abort.current = controller;
    setChecking(true);
    setError(false);
    try {
      await client.cancelQueries({ queryKey: accountQueryKey(userId, "order", orderId), exact: true });
      if (controller.signal.aborted) return;
      const next = await accountApi.verify(userId, orderId, controller.signal);
      if (!controller.signal.aborted) client.setQueryData(accountQueryKey(userId, "order", orderId), next);
    } catch {
      if (!controller.signal.aborted) setError(true);
    } finally {
      if (!controller.signal.aborted) setChecking(false);
      abort.current = null;
    }
  }
  async function cancel() {
    if (abort.current) return;
    const controller = new AbortController();
    abort.current = controller;
    setChecking(true);
    setError(false);
    try {
      const next = await accountApi.cancel(userId, orderId, controller.signal);
      if (!controller.signal.aborted) client.setQueryData(accountQueryKey(userId, "order", orderId), next);
      void client.invalidateQueries({ queryKey: accountQueryKey(userId, "orders") });
    } catch {
      if (!controller.signal.aborted) setError(true);
    } finally {
      if (!controller.signal.aborted) setChecking(false);
      abort.current = null;
    }
  }
  const canPay = order?.status === "PENDING" && Date.parse(order.expires_at) > now &&
    !query.isError && !error && !checking;  // not isFetching: the 5 s poll would blank the QR code
  const payUrl = canPay && checkout?.pay_url ? safeCheckoutLink(checkout.pay_url) : null;
  const qr = canPay && checkout?.qr_code ? safeQrPayload(checkout.qr_code) : null;
  return <section className={`${panel} flex flex-col gap-3`} aria-live="polite">
    {query.isPending ? <p>{t("loading")}</p> : null}
    {query.isError || error ? <p role="alert">{t("loadError")}</p> : null}
    {order && !query.isError ? <>
      <h2 className={heading}>
        {order.status === "COMPLETED" && !orderIsCredited(order) ? t("unknown") : t(`status.${order.status}`)}
      </h2>
      <p className="break-all font-mono text-sm">{order.out_trade_no}</p>
      <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div><dt>{t("actualPayment")}</dt><dd>{order.pay_amount} {order.currency}</dd></div>
        <div><dt>{t("creditedAmount")}</dt><dd>{order.credits}</dd></div>
      </dl>
      {payUrl ? <a href={payUrl} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer"
        className="w-fit rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90">{t("pay")}</a> : null}
      {qr ? <PaymentQr value={qr} /> : null}
    </> : null}
    <p className={muted}>{t("authoritative")}</p>
    <div className="flex flex-wrap gap-2">
      <Button variant="outline" disabled={checking || query.isFetching}
        onClick={() => { if (!abort.current) void query.refetch(); }}>{t("retry")}</Button>
      <Button variant="outline" disabled={checking || !order || query.isError || !orderIsProcessing(order)} onClick={() => void verify()}>
        {t("checkPayment")}
      </Button>
      {order?.status === "PENDING" && !query.isError ? <Button variant="outline" disabled={checking} onClick={() => void cancel()}>
        {t("cancelOrder")}
      </Button> : null}
    </div>
  </section>;
}

function Recharge({ userId }: { userId: string }) {
  const { t } = useTranslation("account");
  const client = useQueryClient();
  const [saved] = useState(() => {
    try { return { attempt: readCheckoutAttempt(userId), error: false }; }
    catch { return { attempt: null, error: true }; }
  });
  const [attempt, setAttempt] = useState<CheckoutAttempt | null>(saved.attempt);
  const [amount, setAmount] = useState(saved.attempt?.amount ?? "");
  const [method, setMethod] = useState<"alipay" | "wxpay">(saved.attempt?.paymentType ?? "alipay");
  const [created, setCreated] = useState<Created | null>(null);
  const [latestOrder, setLatestOrder] = useState<AccountOrder | null>(null);
  const [error, setError] = useState(saved.error ? "storageError" : "");
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);
  const query = useQuery({
    queryKey: accountQueryKey(userId, "checkout"),
    queryFn: ({ signal }) => accountApi.checkout(userId, signal), ...queryOptions,
  });
  const methods = query.data?.methods ?? {};
  const available = (["alipay", "wxpay"] as const).filter((m) => methods[m]?.payment_type === m);
  const selected = available.includes(method) ? method : available[0];
  const currency = methods[attempt?.paymentType ?? selected]?.currency;

  async function submit() {
    if (abort.current || saved.error) return;
    let pending = attempt;
    if (!pending) {
      if (!query.data || !selected || query.data.balance_disabled) return;
      try {
        if (!amountWithinLimits(amount, query.data.global_min, query.data.global_max)) {
          setError("invalidAmount"); return;
        }
      } catch { setError("invalidAmount"); return; }
      try { pending = beginCheckoutAttempt(userId, amount, selected); }
      catch { setError("storageError"); return; }
      setAttempt(pending);
    }
    const controller = new AbortController();
    abort.current = controller;
    setBusy(true);
    setError("");
    try {
      const result = await accountApi.create(userId, pending, controller.signal);
      if (controller.signal.aborted) return;
      setCreated(result);
      setLatestOrder(result.order);
      client.setQueryData(accountQueryKey(userId, "order", result.order.id), result.order);
      void client.invalidateQueries({ queryKey: accountQueryKey(userId, "orders") });
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof AccountApiError && error.code === "payment_not_submitted") {
        try { clearCheckoutAttempt(userId); } catch { setError("storageError"); return; }
        setAttempt(null);
        setError("requestError");
        void query.refetch();
        return;
      }
      if (error instanceof AccountApiError && error.status === 429) {
        // The gateway refused outright (too many unpaid orders): nothing was created.
        try { clearCheckoutAttempt(userId); } catch { setError("storageError"); return; }
        setAttempt(null);
        setError("tooManyPending");
        return;
      }
      // Even a client timeout can occur after the order was created.
      setError("pending");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      abort.current = null;
    }
  }
  function reset() {
    if (!latestOrder || orderIsProcessing(latestOrder)) return;
    try { clearCheckoutAttempt(userId); } catch { setError("storageError"); return; }
    setAttempt(null); setCreated(null); setLatestOrder(null); setError("");
  }
  return <section className={`${panel} flex flex-col gap-3`}>
    <h2 className={heading}>{t("recharge")}</h2>
    {query.isPending ? <p>{t("loading")}</p> : null}
    {query.isError ? <div><p role="alert">{t("loadError")}</p>
      <Button variant="outline" disabled={query.isFetching} onClick={() => void query.refetch()}>{t("retry")}</Button></div> : null}
    {query.data?.balance_disabled || (!query.isPending && !query.isError && available.length === 0)
      ? <p>{t("disabled")}</p> : null}
    {currency ? <form className="flex flex-col gap-3" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
      <label htmlFor="aigcdo-amount" className={muted}>{t("amount", { currency })}</label>
      <Input id="aigcdo-amount" value={amount} inputMode="decimal" autoComplete="off"
        disabled={Boolean(attempt) || busy} onChange={(e) => setAmount(e.target.value)} />
      <fieldset disabled={Boolean(attempt) || busy} className="flex flex-wrap gap-2">
        <legend className={`mb-2 ${muted}`}>{t("method")}</legend>
        {available.map((m) => <Button key={m} type="button"
          variant={(attempt?.paymentType ?? selected) === m ? "default" : "outline"}
          aria-pressed={(attempt?.paymentType ?? selected) === m} onClick={() => setMethod(m)}>{t(m)}</Button>)}
      </fieldset>
      <p className={muted}>{t("priceNote")}</p>
      <Button type="submit" disabled={busy || saved.error || query.isError ||
        (!attempt && (query.data?.balance_disabled || !selected))}>
        {busy ? t("creating") : attempt ? t("retryAttempt") : t("create")}
      </Button>
    </form> : attempt ? <Button onClick={() => void submit()} disabled={busy || saved.error}>{t("retryAttempt")}</Button> : null}
    {attempt && !created && !busy ? <Button type="button" variant="outline" size="sm" className="w-fit" onClick={() => {
      // An unpaid order charges nothing, so abandoning an unconfirmed attempt is safe for the user.
      try { clearCheckoutAttempt(userId); } catch { setError("storageError"); return; }
      setAttempt(null); setError("");
    }}>{t("abandonAttempt")}</Button> : null}
    {error ? <p role="alert" className="text-sm text-destructive">{t(error)}</p> : null}
    {created ? <>
      <OrderPanel key={created.order.id} userId={userId} orderId={created.order.id}
        checkout={created.checkout} onOrder={setLatestOrder} />
      {latestOrder && !orderIsProcessing(latestOrder) ? <Button variant="outline" onClick={reset}>{t("newOrder")}</Button> : null}
    </> : null}
  </section>;
}

function AccountContent({ userId }: { userId: string }) {
  const { t } = useTranslation("account");
  const [usagePage, setUsagePage] = useState(1);
  const [orderPage, setOrderPage] = useState(1);
  const balance = useQuery({ queryKey: accountQueryKey(userId, "balance"),
    queryFn: ({ signal }) => accountApi.balance(userId, signal), ...queryOptions });
  const usage = useQuery({ queryKey: accountQueryKey(userId, "usage", usagePage),
    queryFn: ({ signal }) => accountApi.usage(userId, usagePage, signal), ...queryOptions });
  const orders = useQuery({ queryKey: accountQueryKey(userId, "orders", orderPage),
    queryFn: ({ signal }) => accountApi.orders(userId, orderPage, signal), ...queryOptions });
  return <PageFrame title={t("title")}>
    <section className={panel} aria-live="polite">
      {balance.isPending ? <p>{t("loading")}</p> : null}
      {balance.isError ? <p role="alert">{t("balanceError")}</p> : balance.data ? <dl className="grid gap-4 sm:grid-cols-2">
        <div><dt className={muted}>{t("available")}</dt><dd className="mt-1 break-all text-[32px] font-semibold leading-none tabular-nums text-white">{balance.data.available_credits}</dd></div>
        <div><dt className={muted}>{t("frozen")}</dt><dd className="mt-1 break-all text-[32px] font-semibold leading-none tabular-nums text-white/60">{balance.data.frozen_credits}</dd></div>
      </dl> : null}
      <Button variant="outline" size="sm" className="mt-4" disabled={balance.isFetching} onClick={() => void balance.refetch()}>{t("retry")}</Button>
    </section>
    <Recharge userId={userId} />
    <section className={panel}>
      <h2 className={`mb-3 ${heading}`}>{t("orders")}</h2>
      {orders.isError ? <p role="alert">{t("loadError")}</p> : orders.isPending ? <p>{t("loading")}</p> :
        orders.data?.items.length ? <ul className="divide-y divide-white/8 rounded-lg border border-white/10">
          {orders.data.items.map((order) => <li key={order.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm">
            <a className="break-all font-mono text-xs text-white/82 hover:text-white hover:underline" href={`/payment/result?order_id=${encodeURIComponent(order.id)}`}>{order.out_trade_no}</a>
            <span>{order.pay_amount} {order.currency}</span>
            <span>{order.status === "COMPLETED" && !orderIsCredited(order) ? t("unknown") : t(`status.${order.status}`)}</span>
            {order.status === "PENDING" ? <Button size="sm" variant="outline" onClick={() => {
              void accountApi.cancel(userId, order.id).catch(() => undefined).then(() => orders.refetch());
            }}>{t("cancelOrder")}</Button> : null}
          </li>)}
        </ul> : <p>{t("empty")}</p>}
      <Button className="mt-3" size="sm" variant="outline" disabled={orders.isFetching} onClick={() => void orders.refetch()}>{t("retry")}</Button>
      <Pager page={orderPage} pages={orders.data?.pages ?? orderPage} change={setOrderPage} />
    </section>
    <section className={panel}>
      <h2 className={`mb-3 ${heading}`}>{t("usage")}</h2>
      {usage.isError ? <p role="alert">{t("loadError")}</p> : usage.isPending ? <p>{t("loading")}</p> :
        usage.data?.items.length ? <div className="overflow-x-auto rounded-lg border border-white/10"><table className="w-full text-left text-sm">
          <thead className="bg-white/[0.045] text-xs text-white/40"><tr><th className="px-4 py-3 font-medium">{t("model")}</th><th className="px-4 py-3 font-medium">{t("time")}</th>
            <th className="px-4 py-3 text-right font-medium">{t("walletDebit")}</th></tr></thead>
          <tbody>{usage.data.items.map((item) => <tr key={item.id} className="border-t border-white/8">
            <td className="px-4 py-3 font-medium">{item.model}<span className="block text-xs font-normal text-white/40">{t(item.billing_type)}</span></td>
            <td className="px-4 py-3 text-xs tabular-nums text-white/48">{new Date(item.occurred_at).toLocaleString()}</td>
            <td className="px-4 py-3 text-right font-medium tabular-nums">{item.wallet_debit_credits}</td>
          </tr>)}</tbody>
        </table></div> : <p>{t("empty")}</p>}
      <Button className="mt-3" size="sm" variant="outline" disabled={usage.isFetching} onClick={() => void usage.refetch()}>{t("retry")}</Button>
      <Pager page={usagePage} pages={usage.data?.pages ?? usagePage} change={setUsagePage} />
    </section>
  </PageFrame>;
}

function AccountIdentityBoundary({ userId, children }: {
  userId: string; children: (id: string) => React.ReactNode;
}) {
  const { t } = useTranslation("account");
  const client = useQueryClient();
  const [identity, setIdentity] = useState<string | null>(userId);
  const [failed, setFailed] = useState(false);
  const current = useRef(userId);
  const pending = useRef<AbortController | null>(null);

  async function refresh(event?: Event) {
    if (pending.current) return;
    const previous = current.current;
    const controller = new AbortController();
    pending.current = controller;
    setIdentity(null);
    setFailed(false);
    await client.cancelQueries({ queryKey: accountQueryKey(previous) });
    client.removeQueries({ queryKey: accountQueryKey(previous) });
    try {
      const next = await accountApi.identity(controller.signal);
      if (controller.signal.aborted) return;
      // A persistent mismatch with unchanged /me must fail closed, not remount in a loop.
      if (event?.type === ACCOUNT_SESSION_CHANGED && next.id === previous) {
        setFailed(true);
      } else {
        current.current = next.id;
        setIdentity(next.id);
      }
    } catch {
      if (!controller.signal.aborted) setFailed(true);
    } finally {
      if (pending.current === controller) pending.current = null;
    }
  }
  useEffect(() => {
    const listener = (event: Event) => { void refresh(event); };
    const events = ["focus", "storage", ACCOUNT_SESSION_CHANGED, SESSION_EXPIRED_EVENT];
    events.forEach((event) => window.addEventListener(event, listener));
    return () => {
      events.forEach((event) => window.removeEventListener(event, listener));
      pending.current?.abort();
    };
  }, [client]);

  if (identity) return children(identity);
  return <PageFrame title={t("title")}>
    <p role={failed ? "alert" : "status"}>{t(failed ? "loadError" : "loading")}</p>
    {failed ? <Button onClick={() => void refresh()}>{t("retry")}</Button> : null}
  </PageFrame>;
}

export function AigcdoAccountPage({ userId }: { userId: string }) {
  return <AccountIdentityBoundary key={userId} userId={userId}>
    {(id) => <AccountContent key={id} userId={id} />}
  </AccountIdentityBoundary>;
}

/** Balance, top-up, orders and usage in a floating window, like Settings. */
export function AigcdoAccountDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation("account");
  const identity = useQuery({
    queryKey: ["aigcdo-account-dialog-identity"], queryFn: ({ signal }) => accountApi.identity(signal),
    enabled: open, ...queryOptions,
  });
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent showCloseButton
      className="flex h-[min(82vh,760px)] max-w-[calc(100%-2rem)] flex-col gap-0 overflow-hidden rounded-lg border border-border bg-black p-0 ring-0 sm:max-w-[880px]">
      <DialogHeader className="border-b border-border px-5 py-4"><DialogTitle>{t("title")}</DialogTitle></DialogHeader>
      <div className="ui-scrollbar min-h-0 flex-1 overflow-y-auto p-5">
        <InDialog.Provider value>
          {identity.data ? <AigcdoAccountPage userId={identity.data.id} />
            : <p role={identity.isError ? "alert" : "status"}>{t(identity.isError ? "loadError" : "loading")}</p>}
        </InDialog.Provider>
      </div>
    </DialogContent>
  </Dialog>;
}

export function AigcdoPaymentResult({ userId, orderId }: { userId: string; orderId: string | null }) {
  return <AccountIdentityBoundary key={userId} userId={userId}>
    {(id) => <PaymentResultContent key={id} userId={id} orderId={orderId} />}
  </AccountIdentityBoundary>;
}

function PaymentResultContent({ userId, orderId }: { userId: string; orderId: string | null }) {
  const { t } = useTranslation("account");
  return <PageFrame title={t("result")}>
    {orderId ? <OrderPanel key={`${userId}:${orderId}`} userId={userId} orderId={orderId} /> :
      <p role="alert">{t("missingOrder")}</p>}
    <a href="/account" className="text-sm text-white/72 hover:text-white hover:underline">{t("account")}</a>
  </PageFrame>;
}
