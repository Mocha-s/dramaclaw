import { describe, expect, it } from "vitest";

import { dedupeImageGenerationPrompt } from "@/features/canvas/nodes/shared/imageGenerationPrompt";

describe("dedupeImageGenerationPrompt", () => {
  it("keeps identical upstream and node prompt text only once", () => {
    expect(dedupeImageGenerationPrompt("same prompt", "  same   prompt ")).toBe(
      "same   prompt",
    );
  });

  it("does not append upstream text already contained in the node prompt", () => {
    expect(
      dedupeImageGenerationPrompt("portrait prompt", "portrait prompt, cinematic lighting"),
    ).toBe("portrait prompt, cinematic lighting");
  });
});
