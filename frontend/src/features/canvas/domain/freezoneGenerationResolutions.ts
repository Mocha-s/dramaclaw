// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab

/** 藏境图片 generation 使用的公开档位；最终是否支持由上游模型决定。 */
export const FREEZONE_IMAGE_RESOLUTIONS = ["1K", "2K", "4K"] as const;

/** 藏境视频 generation 使用的公开档位；最终是否支持由上游模型决定。 */
export const FREEZONE_VIDEO_RESOLUTIONS = [
  "480p",
  "720p",
  "768p",
  "1080p",
  "2k",
  "4k",
] as const;

/** 档位之外允许手填的清晰度；与后端 `_CUSTOM_VIDEO_RESOLUTION_RE` 保持一致（后端先转小写）。 */
export const CUSTOM_VIDEO_RESOLUTION_PATTERN = /^(\d{3,4}p|\dk|\d{3,4}x\d{3,4})$/i;

// 节点上存着的旧值可能是 "720P"，目录里现在写的是 "720p"：大小写不敏感地对上，
// 别把用户选过的档位当非法值重置掉。手填的自定义清晰度原样保留；公开档位但不在
// 调用方选项里（助手审批卡按模型给选项）仍回落到调用方的默认档。
export function normalizeVideoQuality(
  value: string | undefined,
  options: readonly string[],
): string {
  const lowered = value?.toLowerCase();
  const configured = options.find((option) => option.toLowerCase() === lowered);
  if (configured) return configured;
  const isPublicTier = FREEZONE_VIDEO_RESOLUTIONS.some((tier) => tier === lowered);
  if (value && !isPublicTier && CUSTOM_VIDEO_RESOLUTION_PATTERN.test(value)) return value;
  return options.find((option) => option.toLowerCase() === "720p") ?? options[0] ?? "720p";
}
