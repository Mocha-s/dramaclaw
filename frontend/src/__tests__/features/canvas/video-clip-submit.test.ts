// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({ apiCall: vi.fn(), apiClient: {} }));
vi.mock("@/api/tasks", () => ({ awaitTaskCompletion: vi.fn() }));
vi.mock("@/lib/url-params", () => ({
  readUrl: () => ({ project: "demo-project", canvas: "default" }),
}));
vi.mock("@/stores/canvasStore", async () => {
  const { create } = await import("zustand");
  const addNode = vi.fn(() => "clip-node-new");
  const addEdge = vi.fn();
  const useCanvasStore = create<{
    nodes: Array<{ id: string; data: Record<string, unknown> }>;
    addNode: typeof addNode;
    addEdge: typeof addEdge;
    findNodePosition: (id: string, width: number, height: number) => { x: number; y: number };
  }>(() => ({
    nodes: [{ id: "source-node", data: { videoUrl: "/static/project/source.mp4" } }],
    addNode,
    addEdge,
    findNodePosition: () => ({ x: 0, y: 0 }),
  }));
  return { useCanvasStore, __mocks: { addNode, addEdge } };
});

import { apiCall } from "@/api/client";
import { awaitTaskCompletion } from "@/api/tasks";
import { submitVideoClip } from "@/features/canvas/application/videoClipSubmit";

async function loadStoreMocks() {
  const mod = (await import("@/stores/canvasStore")) as unknown as {
    __mocks: { addNode: ReturnType<typeof vi.fn>; addEdge: ReturnType<typeof vi.fn> };
  };
  return mod.__mocks;
}

beforeEach(() => {
  vi.mocked(awaitTaskCompletion).mockResolvedValue(undefined as never);
  vi.mocked(apiCall)
    .mockResolvedValueOnce({ task_key: "task-1", job_id: "job-1" })
    .mockResolvedValueOnce({ url: "/static/project/freezone/_outputs/freezone_video_compose/clip.mp4" });
});

afterEach(() => {
  vi.mocked(apiCall).mockReset();
  vi.mocked(awaitTaskCompletion).mockReset();
});

describe("submitVideoClip", () => {
  it("sends the source's native size so the clip keeps the original aspect", async () => {
    const { addNode } = await loadStoreMocks();
    addNode.mockClear();

    const result = await submitVideoClip("source-node", {
      sourceUrl: "/static/project/source.mp4",
      startMs: 1000,
      endMs: 4000,
      quality: "720p",
      outputWidth: 720,
      outputHeight: 1280,
    });

    expect(result.nodeId).toBe("clip-node-new");
    expect(result.error).toBeNull();
    const [endpoint, options] = vi.mocked(apiCall).mock.calls[0] as [string, { json: Record<string, unknown> }];
    expect(endpoint).toBe("projects/demo-project/freezone/video/compose");
    expect(options.json.resolution).toBe("720p");
    expect(options.json.output_width).toBe(720);
    expect(options.json.output_height).toBe(1280);
    expect(addNode).toHaveBeenCalledWith(
      "videoNode",
      { x: 0, y: 0 },
      expect.objectContaining({ videoUrl: expect.stringContaining("clip.mp4") }),
    );
  });

  it("omits the explicit size when the source dimensions are unknown", async () => {
    await submitVideoClip("source-node", {
      sourceUrl: "/static/project/source.mp4",
      startMs: 0,
      endMs: 2000,
      quality: "720p",
    });

    const [, options] = vi.mocked(apiCall).mock.calls[0] as [string, { json: Record<string, unknown> }];
    expect(options.json).not.toHaveProperty("output_width");
    expect(options.json).not.toHaveProperty("output_height");
  });
});
