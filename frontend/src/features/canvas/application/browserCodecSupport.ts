// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
// 浏览器视频编解码能力探测。WebCodecs（VideoDecoder/VideoEncoder）在 Chromium 是
// [SecureContext]：用 http://局域网IP 这类非安全来源访问时接口整体不存在，深度动作
// 捕捉、画面裁切会在 canDecode 处以 cannotDecode 失败，重试也一样；WebGPU 同理，
// 所以「不支持 WebGPU」的提示多半也是这个原因，而不是浏览器真没有。这里把「环境问题」
// （改用 HTTPS/localhost 就能恢复）和「浏览器太旧」分开，入口才能给出可照做的提示。
export type BrowserCodecBlockReason = "insecureContext" | "unsupported";

/** 返回 null 表示编解码接口可用；否则给出被拦截的原因。 */
export function browserCodecBlockReason(): BrowserCodecBlockReason | null {
  if (typeof VideoDecoder !== "undefined" && typeof VideoEncoder !== "undefined") {
    return null;
  }
  return window.isSecureContext ? "unsupported" : "insecureContext";
}
