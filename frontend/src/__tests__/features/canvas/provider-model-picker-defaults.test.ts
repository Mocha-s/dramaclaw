import { describe, expect, it } from "vitest";

import {
  DEFAULT_SHARED_MODEL_ID,
  SHARED_MODELS,
} from "@/features/canvas/ui/ProviderModelPicker";

describe("ProviderModelPicker image model defaults", () => {
  it("uses the current NewAPI image model as the static fallback default", () => {
    expect(DEFAULT_SHARED_MODEL_ID).toBe("gpt-image-2");
  });

  it("keeps static fallback labels aligned with the current backend model names", () => {
    expect(SHARED_MODELS).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "gpt-image-2",
          label: "LingShan-G2",
        }),
        expect.objectContaining({
          id: "nano-banana-2",
          label: "LingShan-NB-2",
        }),
      ]),
    );
  });
});
