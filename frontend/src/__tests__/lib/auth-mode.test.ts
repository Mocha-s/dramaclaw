// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ensureAuthenticatedForAppRoute, isLocalAuthMode } from "@/lib/auth-mode";
import { useAuthStore } from "@/stores/auth-store";

const runtimeState = vi.hoisted(() => ({ authRequired: true, provider: "legacy" }));

vi.mock("@/lib/runtime-config", () => ({
  authRequired: () => runtimeState.authRequired,
  authProvider: () => runtimeState.provider,
}));

beforeEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  runtimeState.authRequired = true;
  runtimeState.provider = "legacy";
  useAuthStore.getState().reset();
  localStorage.clear();
});

describe("auth mode", () => {
  it("defaults to cookie mode", () => {
    vi.stubEnv("VITE_AUTH_MODE", "cookie");

    expect(isLocalAuthMode()).toBe(false);
  });

  it("does not authenticate an empty auth-required runtime session", async () => {
    vi.stubEnv("VITE_AUTH_MODE", "cookie");
    runtimeState.authRequired = true;

    expect(await ensureAuthenticatedForAppRoute()).toBe(false);
  });

  it("uses /auth/me to establish a no-auth runtime session without showing login", async () => {
    vi.stubEnv("VITE_AUTH_MODE", "cookie");
    runtimeState.authRequired = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          ok: true,
          data: { username: "local", role: "owner", credit_balance: 0 },
        }),
      })),
    );

    await expect(ensureAuthenticatedForAppRoute()).resolves.toBe(true);
    expect(useAuthStore.getState().username).toBe("local");
    expect(useAuthStore.getState().role).toBe("owner");
  });

  it("restores an AIGCDO Cookie session after a full navigation with no persisted username", async () => {
    runtimeState.provider = "aigcdo";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ok: true, data: { id: "alice", username: "aigcdo_alice", role: "user" } }),
    }));
    expect(await ensureAuthenticatedForAppRoute()).toBe(true);
    expect(useAuthStore.getState().username).toBe("aigcdo_alice");
  });

  it("does not trust a persisted AIGCDO username when the Cookie is rejected", async () => {
    runtimeState.provider = "aigcdo";
    useAuthStore.setState({ username: "old-user", role: "admin" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 401 }));
    expect(await ensureAuthenticatedForAppRoute()).toBe(false);
    expect(useAuthStore.getState().username).toBeNull();
  });

  it.each(["aigcdo", "unavailable"])("cannot override %s with local build-time authentication", (provider) => {
    runtimeState.provider = provider;
    vi.stubEnv("VITE_AUTH_MODE", "local");
    expect(isLocalAuthMode()).toBe(false);
  });
});
