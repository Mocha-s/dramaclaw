// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { afterEach, describe, expect, it } from "vitest";
import { browserCodecBlockReason } from "@/features/canvas/application/browserCodecSupport";

// jsdom 不带 WebCodecs；用例手工挂/摘全局，再复原 isSecureContext。
const secureDescriptor = Object.getOwnPropertyDescriptor(window, "isSecureContext");

function defineGlobal(name: string, value: unknown): void {
  Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
}

function setSecureContext(value: boolean): void {
  Object.defineProperty(window, "isSecureContext", { value, configurable: true });
}

afterEach(() => {
  delete (globalThis as Record<string, unknown>).VideoDecoder;
  delete (globalThis as Record<string, unknown>).VideoEncoder;
  if (secureDescriptor) {
    Object.defineProperty(window, "isSecureContext", secureDescriptor);
  } else {
    delete (window as unknown as Record<string, unknown>).isSecureContext;
  }
});

describe("browserCodecBlockReason", () => {
  it("blames the insecure origin when WebCodecs is missing over http", () => {
    setSecureContext(false);
    expect(browserCodecBlockReason()).toBe("insecureContext");
  });

  it("blames the browser when WebCodecs is missing in a secure context", () => {
    setSecureContext(true);
    expect(browserCodecBlockReason()).toBe("unsupported");
  });

  it("passes when decoder and encoder are both present", () => {
    defineGlobal("VideoDecoder", function VideoDecoder() {});
    defineGlobal("VideoEncoder", function VideoEncoder() {});
    setSecureContext(true);
    expect(browserCodecBlockReason()).toBeNull();
  });

  it("still blocks when only the decoder exists", () => {
    defineGlobal("VideoDecoder", function VideoDecoder() {});
    setSecureContext(true);
    expect(browserCodecBlockReason()).toBe("unsupported");
  });
});
