// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { useEffect, useRef } from "react";

const SCRIPT = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
type Turnstile = {
  render: (element: HTMLElement, options: Record<string, unknown>) => string;
  remove: (id: string) => void;
};
let loading: Promise<Turnstile> | null = null;

function load(): Promise<Turnstile> {
  loading ??= new Promise<Turnstile>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SCRIPT;
    script.async = true;
    script.onload = () => resolve((window as unknown as { turnstile: Turnstile }).turnstile);
    script.onerror = () => { loading = null; script.remove(); reject(new Error("turnstile")); };
    document.head.append(script);
  });
  return loading;
}

/** Cloudflare's human check. A token is single-use: change `attempt` to get a fresh one. */
export function TurnstileWidget({ siteKey, attempt, onToken, onError }: {
  siteKey: string; attempt: number; onToken: (token: string) => void; onError: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const handlers = useRef({ onToken, onError });
  handlers.current = { onToken, onError };
  useEffect(() => {
    let id: string | null = null;
    let cancelled = false;
    handlers.current.onToken("");
    load().then((turnstile) => {
      if (cancelled || !host.current) return;
      id = turnstile.render(host.current, {
        sitekey: siteKey,
        callback: (token: string) => handlers.current.onToken(token),
        "expired-callback": () => handlers.current.onToken(""),
        "error-callback": () => { handlers.current.onToken(""); handlers.current.onError(); },
      });
    }).catch(() => { if (!cancelled) handlers.current.onError(); });
    return () => {
      cancelled = true;
      if (id) (window as unknown as { turnstile?: Turnstile }).turnstile?.remove(id);
    };
  }, [siteKey, attempt]);
  return <div ref={host} data-testid="turnstile" />;
}
