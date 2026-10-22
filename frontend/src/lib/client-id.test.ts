import { afterEach, describe, expect, it, vi } from 'vitest';

import { generateClientId } from './client-id';

describe('generateClientId', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('uses randomUUID when the browser provides it', () => {
    const randomUUID = vi.fn(() => 'native-id');
    vi.stubGlobal('crypto', { randomUUID });

    expect(generateClientId()).toBe('native-id');
    expect(randomUUID).toHaveBeenCalledOnce();
  });

  it('falls back when randomUUID is unavailable', () => {
    vi.stubGlobal('crypto', undefined);

    const id = generateClientId();

    expect(id).toMatch(/^client-[a-z0-9]+-[a-z0-9]+$/);
  });
});
