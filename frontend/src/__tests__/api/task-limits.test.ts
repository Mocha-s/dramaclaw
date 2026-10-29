// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({ call: vi.fn() }));

vi.mock("@/api/client", () => ({
  apiCallEnvelope: apiMocks.call,
}));

import { getTaskLimits, saveTaskLimits } from "@/api/taskLimits";

describe("task limits API client", () => {
  beforeEach(() => apiMocks.call.mockReset());

  it("reads limits and their effective queue snapshot from the protected config route", async () => {
    const response = { ok: true, data: { lanes: {} }, snapshot: {} };
    apiMocks.call.mockResolvedValue(response);

    await expect(getTaskLimits()).resolves.toBe(response);
    expect(apiMocks.call).toHaveBeenCalledWith("config/task-limits");
  });

  it("writes all lane limits with PUT to the protected config route", async () => {
    const value = { lanes: { default: { globalConcurrency: 8 } } };
    const response = { ok: true, data: value, effective: value, snapshot: {} };
    apiMocks.call.mockResolvedValue(response);

    await expect(saveTaskLimits(value as never)).resolves.toBe(response);
    expect(apiMocks.call).toHaveBeenCalledWith("config/task-limits", {
      method: "PUT",
      json: value,
    });
  });
});
