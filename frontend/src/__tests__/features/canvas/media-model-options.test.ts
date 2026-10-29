// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab

import { describe, expect, it } from 'vitest';

import {
  formatResolutionLabel,
  modelSupportsQuality,
  pickAllowedOption,
  resolveModelQualityOptions,
  resolveModelAspectOptions,
  resolveModelSizeOptions,
  resolveVideoModelResolutionOptions,
} from '@/features/canvas/domain/mediaModelOptions';

describe('媒体模型公共选项归一化', () => {
  it('把历史 adaptive 比例收敛为唯一的 auto 选项', () => {
    expect(
      resolveModelAspectOptions({ ratioOptions: ['adaptive', 'Auto', '16:9'] }),
    ).toEqual(['auto', '16:9']);
  });

  it('keeps global image sizes even when a catalog advertises a narrow subset', () => {
    expect(resolveModelSizeOptions({ resolutionOptions: ['720p', '1080p'] })).toEqual([
      '1K',
      '2K',
      '4K',
    ]);
  });

  it('uses all product video resolution tiers when catalog omits them', () => {
    expect(resolveVideoModelResolutionOptions({ resolutionOptions: ['720p'] })).toEqual(['720p', '768p', '1080p', '2k', '4k']);
    expect(resolveVideoModelResolutionOptions({ resolutionOptions: ['720p', '1080p'] })).toEqual(['720p', '768p', '1080p', '2k', '4k']);
    expect(resolveVideoModelResolutionOptions({})).toEqual(['720p', '768p', '1080p', '2k', '4k']);
  });

  it('虾集图片和视频分辨率档位独立于模型目录并覆盖产品档位', async () => {
    const { FREEZONE_IMAGE_RESOLUTIONS, FREEZONE_VIDEO_RESOLUTIONS } =
      await import('@/features/canvas/domain/freezoneGenerationResolutions');
    expect(FREEZONE_IMAGE_RESOLUTIONS).toEqual(['1K', '2K', '4K']);
    expect(FREEZONE_VIDEO_RESOLUTIONS).toEqual([
      '720p', '768p', '1080p', '2k', '4k',
    ]);
  });

  it('uses catalog image quality options when present and global options otherwise', () => {
    const model = { qualityOptions: ['draft', 'studio'] };
    const options = resolveModelQualityOptions(model);
    expect(options).toEqual(['auto', 'low', 'medium', 'high', 'xhigh', 'max']);
    expect(modelSupportsQuality(model)).toBe(true);
    expect(pickAllowedOption('max', options, 'draft')).toBe('max');
    expect(resolveModelQualityOptions({})).toEqual(['auto', 'low', 'medium', 'high', 'xhigh', 'max']);
    expect(modelSupportsQuality({})).toBe(true);
  });

  it('分辨率只在显示层统一成小写', () => {
    expect(formatResolutionLabel('4K')).toBe('4k');
    expect(formatResolutionLabel('1080P')).toBe('1080p');
  });
});
