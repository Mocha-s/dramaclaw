// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { beforeEach, describe, expect, it, vi } from 'vitest';

const fetchFreezoneImageModels = vi.hoisted(() => vi.fn());

vi.mock('@/api/ops', () => ({ fetchFreezoneImageModels }));
vi.mock('@/lib/url-params', () => ({ readUrl: () => ({ project: null }) }));
vi.mock('@/features/canvas/ui/ProviderModelPicker', () => ({
  SHARED_MODELS: [{
    id: 'legacy-default',
    providerId: 'newapi',
    apiModel: 'legacy-default',
    label: 'Legacy fallback',
  }],
}));

import { waitForFreezoneImageModels } from '@/features/canvas/hooks/useFreezoneImageModels';

describe('waitForFreezoneImageModels', () => {
  beforeEach(() => {
    fetchFreezoneImageModels.mockReset();
  });

  it('waits for the project catalog instead of returning the legacy fallback while it loads', async () => {
    const catalogModel = {
      catalogId: 'catalog-lingshan',
      id: 'LingShan-G2',
      providerId: 'newapi',
      apiModel: 'LingShan-G2',
      label: 'LingShan-G2',
    };
    let resolveCatalog: (models: typeof catalogModel[]) => void = () => undefined;
    fetchFreezoneImageModels.mockReturnValue(
      new Promise<typeof catalogModel[]>((resolve) => {
        resolveCatalog = resolve;
      }),
    );

    let settled = false;
    const result = waitForFreezoneImageModels('project-catalog-loading').then((value) => {
      settled = true;
      return value;
    });

    await Promise.resolve();
    expect(settled).toBe(false);

    resolveCatalog([catalogModel]);
    await expect(result).resolves.toMatchObject({
      models: [catalogModel],
      isLoading: false,
      isFallback: false,
    });
    expect(fetchFreezoneImageModels).toHaveBeenCalledWith('project-catalog-loading');
  });

  it('does not expose hardcoded models when the project catalog request fails', async () => {
    fetchFreezoneImageModels.mockRejectedValueOnce(new Error('catalog unavailable'));

    await expect(waitForFreezoneImageModels('project-catalog-failed')).resolves.toMatchObject({
      models: [],
      isLoading: false,
      isFallback: true,
    });
  });
});
