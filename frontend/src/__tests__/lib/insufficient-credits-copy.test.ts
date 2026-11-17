// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TFunction } from "i18next";

afterEach(() => {
  vi.doUnmock("@/lib/runtime-config");
  vi.resetModules();
});

async function messagesFor(provider: "legacy" | "aigcdo") {
  vi.resetModules();
  vi.doMock("@/lib/runtime-config", () => ({ authProvider: () => provider }));
  const errors = await import("@/lib/api-errors");
  const { taskErrorMessage } = await import("@/task-center/task-errors");
  const t = vi.fn(
    (key: string, options?: { context?: string }) => `${key}:${options?.context ?? "default"}`,
  ) as unknown as TFunction;
  return [
    errors.backendErrorToastMessage(errors.errorFromBackendBody(402, null, "x"), t),
    taskErrorMessage({ error: "x", error_code: "INSUFFICIENT_CREDITS" } as never, t),
  ];
}

describe("insufficient credits copy by auth provider", () => {
  it("points AIGCDO users at their own top-up instead of an administrator", async () => {
    expect(await messagesFor("aigcdo")).toEqual([
      "common.insufficientCredits:aigcdo",
      "common.insufficientCredits:aigcdo",
    ]);
  });

  it("keeps the administrator copy for the single-user install", async () => {
    expect(await messagesFor("legacy")).toEqual([
      "common.insufficientCredits:default",
      "common.insufficientCredits:default",
    ]);
  });
});
