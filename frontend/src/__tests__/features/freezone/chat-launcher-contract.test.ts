import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const source = readFileSync("src/features/freezone/FreezoneShell.tsx", "utf8");

describe("freezone xia-dao launcher contract", () => {
  it("shows the assistant's name as text, not the upstream branded video", () => {
    expect(source).not.toContain("xia-dao-launcher.mp4");
    expect(source).toContain("const CHAT_LAUNCHER_VISUAL_WIDTH = 96");
    expect(source).toContain("const CHAT_LAUNCHER_HIT_HEIGHT = 44");
  });

  it("keeps the existing click and drag interactions", () => {
    expect(source).toContain("onPointerDown={handlePointerDown}");
    expect(source).toContain("onClick={handleClick}");
    expect(source).toContain("onClick();");
  });
});
