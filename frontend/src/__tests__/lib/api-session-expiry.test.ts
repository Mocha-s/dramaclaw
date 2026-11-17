// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/__mocks__/msw/server";

const mocks = vi.hoisted(() => ({
  logout: vi.fn<() => Promise<void>>(),
  resetUserSessionState: vi.fn(),
}));

vi.mock("@/stores/auth-store", () => ({
  useAuthStore: {
    getState: () => ({ logout: mocks.logout }),
  },
}));
vi.mock("@/lib/nav-lock", () => ({
  tryAcquireNavLock: () => true,
}));
vi.mock("@/lib/reset-region-state", () => ({
  resetRegionState: vi.fn(),
  resetUserSessionState: mocks.resetUserSessionState,
}));

import { api, handleSessionExpired, setApiQueryClient } from "@/lib/api";
import { SESSION_EXPIRED_EVENT } from "@/lib/session-expiry";

afterEach(() => {
  mocks.logout.mockReset();
  mocks.resetUserSessionState.mockReset();
  window.history.replaceState({}, "", "/");
});

describe("handleSessionExpired", () => {
  it.each(["login", "login/2fa", "register"])("keeps rejected %s in the watch-page modal", async (endpoint) => {
    window.history.replaceState({}, "", "/watch/example");
    mocks.logout.mockImplementation(async () => { window.history.replaceState({}, "", "/login"); });
    server.use(http.post(`*/api/v1/auth/${endpoint}`, () => HttpResponse.json(
      { ok: false, code: "authentication_failed" }, { status: 401 },
    )));
    const response = await api.extend({ prefix: "" })(`http://localhost:3000/api/v1/auth/${endpoint}`, {
      method: "POST", json: {}, throwHttpErrors: false, retry: 0,
    });
    expect(response.status).toBe(401);
    expect(mocks.logout).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe("/watch/example");
  });

  it("coalesces concurrent 401 teardown into one logout and one reset", async () => {
    let resolveLogout!: () => void;
    mocks.logout.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveLogout = resolve;
      }),
    );
    const queryClient = {} as Parameters<typeof setApiQueryClient>[0];
    setApiQueryClient(queryClient);
    const sessionExpired = vi.fn();
    window.addEventListener(SESSION_EXPIRED_EVENT, sessionExpired);

    const first = handleSessionExpired();
    const second = handleSessionExpired();

    expect(second).toBe(first);
    expect(sessionExpired).toHaveBeenCalledOnce();
    expect(mocks.logout).toHaveBeenCalledOnce();
    expect(mocks.resetUserSessionState).not.toHaveBeenCalled();

    // Keep jsdom on the same target URL so assigning location.href does not
    // emit its unsupported cross-document navigation warning.
    window.history.replaceState({}, "", "/login");
    resolveLogout();
    await first;

    expect(mocks.resetUserSessionState).toHaveBeenCalledOnce();
    expect(mocks.resetUserSessionState).toHaveBeenCalledWith({ queryClient });
    window.removeEventListener(SESSION_EXPIRED_EVENT, sessionExpired);
    window.history.replaceState({}, "", "/");
  });

  it("still expires sessions on protected API rejection", async () => {
    window.history.replaceState({}, "", "/watch/example");
    mocks.logout.mockImplementation(async () => { window.history.replaceState({}, "", "/login"); });
    server.use(http.get("*/api/v1/account/billing/balance", () => HttpResponse.json(
      { ok: false }, { status: 401 },
    )));
    const response = await api.extend({ prefix: "" })("http://localhost:3000/api/v1/account/billing/balance", {
      throwHttpErrors: false, retry: 0,
    });
    expect(response.status).toBe(401);
    expect(mocks.logout).toHaveBeenCalledOnce();
    expect(window.location.pathname).toBe("/login");
  });
});
