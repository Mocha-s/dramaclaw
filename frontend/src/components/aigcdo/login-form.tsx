import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { aigcdoAuthApi, type AuthenticatedAccount } from "@/lib/queries/aigcdo-auth";
import { AccountApiError } from "@/lib/queries/aigcdo-account";
import { useAuthStore } from "@/stores/auth-store";
import { TurnstileWidget } from "./turnstile";

export function AigcdoLoginForm({ onReady }: { onReady: () => void }) {
  const { t } = useTranslation("account");
  const [mode, setMode] = useState<"login" | "register" | "secondFactor">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [acceptedRevision, setAcceptedRevision] = useState<string | null>(null);
  const [user, setUser] = useState<AuthenticatedAccount | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [turnstile, setTurnstile] = useState("");
  const [attempt, setAttempt] = useState(0);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  const query = useQuery({
    queryKey: ["aigcdo-auth-ui"], queryFn: ({ signal }) => aigcdoAuthApi.config(signal),
    retry: false, gcTime: 0, staleTime: 0, refetchOnWindowFocus: "always",
  });
  const config = query.data;
  const registration = config?.registration_enabled && config.registration_supported;
  const accepted = config && (!config.login_agreement_enabled || acceptedRevision === config.login_agreement_revision);
  // The gateway checks the human proof on login and registration, not on the second factor.
  const humanCheck = mode !== "secondFactor" && config?.turnstile_site_key ? config.turnstile_site_key : "";

  function authenticated(next: AuthenticatedAccount) {
    setPassword(""); setCode("");
    useAuthStore.getState().reset();
    setUser(next);
    if (next.application?.status === "ready") onReady();
  }

  async function submit() {
    if (pending.current || !accepted || query.isError || !config?.login_supported) return;
    if (humanCheck && !turnstile) return;
    if (mode === "register" && !registration) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true); setError("");
    let submitted = false;
    try {
      const fresh = (await query.refetch({ throwOnError: true })).data;
      if (controller.signal.aborted) return;
      if (!fresh) { setError("auth.configError"); return; }
      if (!fresh.login_supported || (mode === "register" && !fresh.registration_supported)) {
        setError("auth.unsupported"); return;
      }
      if (mode === "register" && !fresh.registration_enabled) {
        setError("auth.registrationClosed"); return;
      }
      if (fresh.login_agreement_enabled && acceptedRevision !== fresh.login_agreement_revision) {
        setError("auth.agreementChanged"); return;
      }
      submitted = true;
      const result = mode === "secondFactor"
        ? await aigcdoAuthApi.secondFactor(code, controller.signal)
        : mode === "register"
          ? await aigcdoAuthApi.register(email, password, controller.signal, turnstile)
          : await aigcdoAuthApi.login(email, password, controller.signal, turnstile);
      if (controller.signal.aborted) return;
      if ("requires_2fa" in result) {
        setPassword(""); setMode("secondFactor");
      } else authenticated(result);
    } catch (failure) {
      if (controller.signal.aborted) return;
      if (!submitted) {
        setError("auth.configError");
      } else if (mode === "register" && (!(failure instanceof AccountApiError) || failure.status >= 500)) {
        setMode("login");
        setPassword("");
        setError("auth.registrationUncertain");
      } else setError(failure instanceof AccountApiError && failure.status === 429 ? "auth.rateLimited" : "auth.failed");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      pending.current = null;
      // A proof is spent by the request that carried it, whatever the outcome.
      if (submitted) setAttempt((value) => value + 1);
    }
  }

  async function recover() {
    if (pending.current || !user) return;
    const controller = new AbortController();
    pending.current = controller; setBusy(true); setError("");
    try {
      const application = await aigcdoAuthApi.application(user.id, controller.signal);
      if (!controller.signal.aborted) authenticated({ ...user, application });
    } catch (failure) {
      if (controller.signal.aborted) return;
      if (failure instanceof AccountApiError && (failure.code === "session_changed" || failure.status === 401)) {
        setUser(null); setMode("login"); setAcceptedRevision(null);
        useAuthStore.getState().reset();
        setError("auth.sessionChanged");
      } else setError("auth.failed");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      pending.current = null;
    }
  }

  if (user) return <div className="flex flex-col gap-3 text-sm" aria-live="polite">
    <p>{t(user.application?.status === "blocked" ? "auth.blocked" : "auth.pending")}</p>
    <Button disabled={busy} onClick={() => void recover()}>{t("auth.retryApplication")}</Button>
    <a href="/account" className="underline">{t("account")}</a>
    {error ? <p role="alert">{t(error)}</p> : null}
  </div>;

  if (query.isPending) return <p role="status">{t("loading")}</p>;
  if (query.isError || !config) return <div className="flex flex-col gap-3">
    <p role="alert">{t("auth.configError")}</p>
    <Button disabled={query.isFetching} onClick={() => void query.refetch()}>{t("retry")}</Button>
  </div>;
  if (!config.login_supported) return <p role="alert">{t("auth.unsupported")}</p>;

  return <form className="flex flex-col gap-3 text-sm" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
    {mode !== "secondFactor" ? <>
      <label htmlFor="aigcdo-email">{t("auth.email")}</label>
      <Input id="aigcdo-email" type="email" autoComplete="username" required maxLength={254}
        value={email} disabled={busy} onChange={(event) => setEmail(event.target.value)} />
      <label htmlFor="aigcdo-password">{t("auth.password")}</label>
      <Input id="aigcdo-password" type="password" autoComplete={mode === "register" ? "new-password" : "current-password"}
        required minLength={mode === "register" ? 6 : 1} maxLength={4096} value={password}
        disabled={busy} onChange={(event) => setPassword(event.target.value)} />
    </> : <>
      <label htmlFor="aigcdo-totp">{t("auth.secondFactor")}</label>
      <Input id="aigcdo-totp" autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{6}"
        required maxLength={6} value={code} disabled={busy} onChange={(event) => setCode(event.target.value)} />
    </>}
    {config.login_agreement_enabled ? <>
      <div className="max-h-40 overflow-y-auto ui-scrollbar rounded-md border border-border p-3">
        {config.login_agreement_documents.map((document) => <details key={document.id}>
          <summary className="cursor-pointer py-1">{document.title}</summary>
          <p className="whitespace-pre-wrap break-words">{document.content_md}</p>
        </details>)}
      </div>
      <label className="flex items-start gap-2">
        <Checkbox checked={acceptedRevision === config.login_agreement_revision} disabled={busy}
          onCheckedChange={(checked) => setAcceptedRevision(checked ? config.login_agreement_revision : null)} />
        {t("auth.agree")}
      </label>
    </> : null}
    {humanCheck ? <TurnstileWidget siteKey={humanCheck} attempt={attempt}
      onToken={setTurnstile} onError={() => setError("auth.humanCheckFailed")} /> : null}
    <Button type="submit"
      disabled={busy || !accepted || (mode === "register" && !registration) || Boolean(humanCheck && !turnstile)}>
      {t(busy ? "auth.working" : mode === "register" ? "auth.create" : mode === "secondFactor" ? "auth.verify" : "auth.signIn")}
    </Button>
    {mode === "login" ? registration
      ? <Button type="button" variant="ghost" disabled={busy}
        onClick={() => { setMode("register"); setPassword(""); setError(""); }}>{t("auth.register")}</Button>
      : <p>{t(config.registration_enabled ? "auth.unsupported" : "auth.registrationClosed")}</p>
      : <Button type="button" variant="ghost" disabled={busy}
        onClick={() => { setMode("login"); setPassword(""); setCode(""); setError(""); }}>{t("auth.backToLogin")}</Button>}
    {error ? <p role="alert">{t(error)}</p> : null}
  </form>;
}
