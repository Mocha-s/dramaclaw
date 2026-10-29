// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab

/** 虾集图片 generation 使用的公开档位；最终是否支持由上游模型决定。 */
export const FREEZONE_IMAGE_RESOLUTIONS = ["1K", "2K", "4K"] as const;

/** 虾集视频 generation 使用的公开档位；最终是否支持由上游模型决定。 */
export const FREEZONE_VIDEO_RESOLUTIONS = [
  "720p",
  "768p",
  "1080p",
  "2k",
  "4k",
] as const;
