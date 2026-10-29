// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { describe, expect, it } from 'vitest';

import type { MediaModelParameterDefinition } from '@/api/ops';
import {
  filterMediaModelParamsForMode,
  userSelectableMediaModelParameters,
} from '@/features/canvas/ui/MediaModelParameterChip';

const parameters: MediaModelParameterDefinition[] = [
  {
    key: 'thinking_level',
    label: '思考等级',
    control: 'select',
    requestPath: 'thinking_level',
    options: ['low', 'medium', 'high'],
    default: 'low',
    userSelectable: true,
  },
  {
    key: 'style',
    label: '风格',
    control: 'select',
    requestPath: 'style',
    options: ['natural', 'vivid'],
    default: 'natural',
  },
  {
    key: 'only_edit',
    label: '仅编辑',
    control: 'select',
    requestPath: 'edit_only',
    options: ['on', 'off'],
    modes: ['image_to_image'],
  },
];

describe('media model parameter visibility', () => {
  it('shows thinking level only when the catalog marks it user selectable', () => {
    expect(userSelectableMediaModelParameters(parameters, 'text_to_image').map((item) => item.key)).toEqual([
      'thinking_level',
      'style',
    ]);
    expect(
      userSelectableMediaModelParameters(
        parameters.map((item) => ({ ...item, userSelectable: item.key !== 'thinking_level' })),
      ).map((item) => item.key),
    ).toEqual(['style']);
  });

  it('filters stored thinking level when the catalog does not allow it', () => {
    expect(
      filterMediaModelParamsForMode(
        parameters,
        { thinking_level: 'high', style: 'vivid', only_edit: 'on', removed: true },
        'text_to_image',
      ),
    ).toEqual({ thinking_level: 'high', style: 'vivid' });
    expect(
      filterMediaModelParamsForMode(
        parameters,
        { only_edit: 'on', style: 'vivid' },
        'image_to_image',
      ),
    ).toEqual({ only_edit: 'on', style: 'vivid' });
    expect(
      filterMediaModelParamsForMode(
        parameters.map((item) => ({ ...item, userSelectable: item.key !== 'thinking_level' })),
        { thinking_level: 'high', style: 'vivid' },
        'text_to_image',
      ),
    ).toEqual({ style: 'vivid' });
  });
});
