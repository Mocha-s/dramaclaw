// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/ops", () => ({ uploadFreezoneVideo: vi.fn() }));
vi.mock("@/features/canvas/application/imageData", () => ({
  resolveImageDisplayUrl: (url: string) => `resolved:${url}`,
}));
vi.mock("@/features/canvas/application/videoCrop/cropVideo", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  cropVideoBlob: vi.fn(),
}));

import { uploadFreezoneVideo } from "@/api/ops";
import { cropVideoBlob } from "@/features/canvas/application/videoCrop/cropVideo";
import {
  resetExtendTrimCacheForTest,
  trimAndUploadExtendClip,
} from "@/features/canvas/application/videoExtendTrim";

const options = {
  projectId: "p1",
  videoUrl: "https://oss/src.mp4",
  range: { startMs: 1000, endMs: 4000 },
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async () => ({ ok: true, status: 200, blob: async () => new Blob(["src"]) }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(cropVideoBlob).mockReset();
  vi.mocked(uploadFreezoneVideo).mockReset();
  resetExtendTrimCacheForTest();
});

describe("trimAndUploadExtendClip", () => {
  it("fetches the source bypassing the HTTP cache, trims the range and uploads it", async () => {
    const trimmed = new Blob(["trimmed"], { type: "video/mp4" });
    vi.mocked(cropVideoBlob).mockResolvedValue({ blob: trimmed, width: 720, height: 1280, durationMs: 3000 });
    vi.mocked(uploadFreezoneVideo).mockResolvedValue({ url: "https://oss/extend.mp4", filename: "e.mp4", size: 7 });

    const result = await trimAndUploadExtendClip(options);

    // 同一 URL 正被节点里的 <video> 分段加载，必须绕过 HTTP 缓存（见 runDepthCapture 取源处的说明）。
    expect(fetchMock).toHaveBeenCalledWith("resolved:https://oss/src.mp4", { cache: "no-store" });
    expect(cropVideoBlob).toHaveBeenCalledWith(
      expect.objectContaining({ blob: expect.any(Blob), trim: { startMs: 1000, endMs: 4000 } }),
    );
    expect(uploadFreezoneVideo).toHaveBeenCalledWith(
      "p1",
      trimmed,
      expect.stringMatching(/^video-extend-\d+\.mp4$/),
    );
    expect(result).toEqual({ url: "https://oss/extend.mp4", durationMs: 3000 });
  });

  it("shares one in-flight result per range and forgets it after a failure", async () => {
    vi.mocked(cropVideoBlob).mockRejectedValueOnce(new Error("boom"));
    await expect(trimAndUploadExtendClip(options)).rejects.toThrow("boom");

    const trimmed = new Blob(["trimmed"], { type: "video/mp4" });
    vi.mocked(cropVideoBlob).mockResolvedValue({ blob: trimmed, width: 720, height: 1280, durationMs: 3000 });
    vi.mocked(uploadFreezoneVideo).mockResolvedValue({ url: "https://oss/extend.mp4", filename: "e.mp4", size: 7 });

    const [first, second] = await Promise.all([
      trimAndUploadExtendClip(options),
      trimAndUploadExtendClip(options),
    ]);

    expect(first).toEqual(second);
    // 失败那次重新来过，成功那次被并发的第二个调用复用。
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(uploadFreezoneVideo).toHaveBeenCalledTimes(1);
  });
});
