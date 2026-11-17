import { describe, expect, it } from "vitest";
import { textGenerationAttempt } from "@/lib/aigcdo-text-attempt";

describe("AIGCDO text attempt recovery", () => {
  it("keeps an uncertain request idempotent across reload and retries", () => {
    const attempt = textGenerationAttempt("write a scene", null);
    expect(textGenerationAttempt("write a scene", JSON.parse(JSON.stringify(attempt)))).toEqual(attempt);
  });
  it("rotates only when the prompt changes or stored state is malformed", () => {
    const attempt = textGenerationAttempt("first", null);
    expect(textGenerationAttempt("second", attempt).key).not.toBe(attempt.key);
    expect(textGenerationAttempt("first", { prompt: "first", key: "bad" }).key).not.toBe("bad");
  });
});
