// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { z } from "zod";
import type { BrowserModelSourceConfig } from "@/features/canvas/application/browserModelSource";

export const RuntimeConfigResponse = z.object({
  ok: z.literal(true),
  data: z.object({
    edition: z.enum(["ce", "ee"]),
    auth_required: z.boolean(),
    auth_provider: z.enum(["legacy", "aigcdo"]).optional(),
    instance_id: z.string().optional(),
    mcp_direct_canvas_apply: z.boolean().optional(),
    browser_model_asset_base: z.string().nullable().optional(),
    browser_model_hf_endpoint: z.string().nullable().optional(),
    browser_ort_wasm_base: z.string().nullable().optional(),
  }),
});

const AuthUiConfigResponse = z.object({
  ok: z.literal(true),
  data: z.object({
    phone_otp_entry_visible: z.boolean(),
    auth_provider: z.enum(["legacy", "aigcdo"]).optional(),
  }),
});

export interface RuntimeConfig {
  edition: "ce" | "ee";
  authRequired: boolean;
  authProvider?: "legacy" | "aigcdo" | "unavailable";
  phoneOtpEntryVisible: boolean;
  instanceId?: string;
  mcpDirectCanvasApply: boolean;
  /** 浏览器端推理模型与 wasm 的来源；全为 null 表示走 transformers.js 默认源。 */
  browserModelSource: BrowserModelSourceConfig;
}

const DEFAULT_BROWSER_MODEL_SOURCE: BrowserModelSourceConfig = {
  assetBase: null,
  hfEndpoint: null,
  ortWasmBase: null,
};

let runtimeConfig: RuntimeConfig = {
  edition: "ee",
  authRequired: true,
  mcpDirectCanvasApply: false,
  phoneOtpEntryVisible: false,
  browserModelSource: DEFAULT_BROWSER_MODEL_SOURCE,
};

function fallbackRuntimeConfig(): RuntimeConfig {
  return {
    edition: import.meta.env.VITE_EDITION === "ce" ? "ce" : "ee",
    authRequired: true,
    authProvider: "unavailable",
    phoneOtpEntryVisible: false,
    mcpDirectCanvasApply: false,
    browserModelSource: DEFAULT_BROWSER_MODEL_SOURCE,
  };
}

async function loadAuthUiConfig(): Promise<z.infer<typeof AuthUiConfigResponse>["data"] | null> {
  try {
    const response = await fetch("/api/v1/auth/ui-config", {
      credentials: "include",
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`GET /api/v1/auth/ui-config -> ${response.status}`);
    const body = await response.json();
    return AuthUiConfigResponse.parse(body).data;
  } catch (error) {
    // Older or temporarily unavailable EE backends must keep the entry dark.
    // eslint-disable-next-line no-console
    console.warn("[runtime-config] auth UI config load failed:", error);
    return null;
  }
}

export async function loadRuntimeConfig(): Promise<void> {
  try {
    const response = await fetch("/api/v1/config", { credentials: "include", cache: "no-store" });
    if (!response.ok) throw new Error(`GET /api/v1/config -> ${response.status}`);
    const body = await response.json();
    const parsed = RuntimeConfigResponse.parse(body);
    const authUi = parsed.data.auth_required
      ? await loadAuthUiConfig() : { phone_otp_entry_visible: false };
    runtimeConfig = {
      edition: parsed.data.edition,
      authRequired: parsed.data.auth_required,
      phoneOtpEntryVisible: authUi?.phone_otp_entry_visible ?? false,
      authProvider: parsed.data.auth_provider ?? authUi?.auth_provider ?? (authUi ? "legacy" : "unavailable"),
      instanceId: parsed.data.instance_id,
      mcpDirectCanvasApply: parsed.data.mcp_direct_canvas_apply ?? false,
      browserModelSource: {
        assetBase: parsed.data.browser_model_asset_base || null,
        hfEndpoint: parsed.data.browser_model_hf_endpoint || null,
        ortWasmBase: parsed.data.browser_ort_wasm_base || null,
      },
    };
  } catch (error) {
    // eslint-disable-next-line no-console
    console.warn("[runtime-config] load failed:", error);
    runtimeConfig = fallbackRuntimeConfig();
  }
}

export function isCeRuntime(): boolean {
  return runtimeConfig.edition === "ce";
}

export function authRequired(): boolean {
  return runtimeConfig.authRequired;
}

export function mcpDirectCanvasApplyEnabled(): boolean {
  return runtimeConfig.mcpDirectCanvasApply;
}

export function phoneOtpEntryVisible(): boolean {
  return runtimeConfig.phoneOtpEntryVisible;
}

export function authProvider(): "legacy" | "aigcdo" | "unavailable" {
  return runtimeConfig.authProvider ?? "legacy";
}

let adminSession = false;

/** Set by the /admin page once the operator administrator has signed in. */
export function setAdminSession(value: boolean): void {
  adminSession = value;
}

/** Model keys, channels and task limits belong to the single-user owner or the AIGCDO administrator. */
export function localModelSettingsEnabled(): boolean {
  return isCeRuntime() && (authProvider() === "legacy" || adminSession);
}

export function browserModelSource(): BrowserModelSourceConfig {
  return runtimeConfig.browserModelSource;
}
