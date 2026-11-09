// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { describe, expect, it } from "vitest";

import {
  CANVAS_NODE_TYPES,
  type CanvasNode,
  type CanvasNodeType,
} from "@/features/canvas/domain/canvasNodes";
import {
  VIDEO_REFERENCE_ENVELOPE,
  classifyVideoReferenceMedia,
  videoReferenceEnvelopeForModel,
} from "@/features/canvas/domain/videoReferenceLimits";
import { videoReferenceEnvelopeForNode } from "@/features/canvas/application/videoReferenceEnvelope";
import type { ModelOption } from "@/features/canvas/ui/ProviderModelPicker";

function node(
  id: string,
  type: CanvasNodeType,
  data: Record<string, unknown> = {},
): CanvasNode {
  return { id, type, position: { x: 0, y: 0 }, data } as CanvasNode;
}

describe("classifyVideoReferenceMedia — 素材归类", () => {
  it("按节点类型归类，空节点也算（先连节点后填素材是正常顺序）", () => {
    expect(classifyVideoReferenceMedia(node("a", CANVAS_NODE_TYPES.imageGen))).toBe("image");
    expect(classifyVideoReferenceMedia(node("a", CANVAS_NODE_TYPES.upload))).toBe("image");
    expect(classifyVideoReferenceMedia(node("a", CANVAS_NODE_TYPES.video))).toBe("video");
    expect(classifyVideoReferenceMedia(node("a", CANVAS_NODE_TYPES.audio))).toBe("audio");
  });

  // 资产库选入的视频是 upload 节点，地址写在 data.videoUrl —— 只看类型会被误当图片。
  it("带 videoUrl 的 upload 节点算视频，不算图片", () => {
    expect(
      classifyVideoReferenceMedia(
        node("a", CANVAS_NODE_TYPES.upload, { videoUrl: "/a.mp4" }),
      ),
    ).toBe("video");
  });

  it("非素材节点（文本 / 空）不计数", () => {
    expect(classifyVideoReferenceMedia(node("a", CANVAS_NODE_TYPES.textAnnotation))).toBeNull();
    expect(classifyVideoReferenceMedia(null)).toBeNull();
  });
});

// 9/3/3/12 只是「目录没配」时的默认值。媒体目录允许把 referenceImageMax 等配成任意
// 非负整数，后端 _catalog_reference_limits（api/routes/freezone.py:7004）会采用它们；
// 前端要是把默认值当硬上限，一个配了 image=10 的合法模型会在第 10 张被拦掉，请求永远
// 到不了本来会接受它的后端 —— 前端比后端严 = 把管理员配出来的能力吞掉。
describe("videoReferenceEnvelopeForModel — 目录配置优先", () => {
  it("没配任何目录值时用默认包络", () => {
    expect(videoReferenceEnvelopeForModel(undefined)).toEqual(VIDEO_REFERENCE_ENVELOPE);
    expect(videoReferenceEnvelopeForModel({})).toEqual(VIDEO_REFERENCE_ENVELOPE);
  });

  // total 的算法与后端 omni 调用点（freezone.py:7857-7868）一致：三项里只要有任意
  // 一项来自目录，总数就取三项之和；一项都没配才回落到 12。
  it("配了任意一项就按三项之和算总数", () => {
    expect(videoReferenceEnvelopeForModel({ referenceImageMax: 10 })).toEqual({
      image: 10,
      video: VIDEO_REFERENCE_ENVELOPE.video,
      audio: VIDEO_REFERENCE_ENVELOPE.audio,
      total: 10 + VIDEO_REFERENCE_ENVELOPE.video + VIDEO_REFERENCE_ENVELOPE.audio,
    });
    expect(
      videoReferenceEnvelopeForModel({
        referenceImageMax: 4,
        referenceVideoMax: 1,
        referenceAudioMax: 0,
      }),
    ).toEqual({ image: 4, video: 1, audio: 0, total: 5 });
  });

  // 与后端 `type(value) is int and value >= 0` 同一口径。
  it("null / 负数 / 小数一律当作没配", () => {
    expect(
      videoReferenceEnvelopeForModel({
        referenceImageMax: null,
        referenceVideoMax: -1,
        referenceAudioMax: 2.5,
      }),
    ).toEqual(VIDEO_REFERENCE_ENVELOPE);
  });
});

describe("videoReferenceEnvelopeForNode — 从节点解析出所选模型的包络", () => {
  const catalog: ModelOption[] = [
    { id: 'first', providerId: 'seedance', apiModel: 'first', label: 'First' },
    {
      id: 'wide',
      providerId: 'seedance',
      apiModel: 'wide',
      label: 'Wide',
      referenceImageMax: 10,
    },
  ];

  it("按 data.model 在目录里查", () => {
    const videoNode = node("v", CANVAS_NODE_TYPES.video, { model: 'wide' });
    expect(videoReferenceEnvelopeForNode(videoNode, catalog).image).toBe(10);
  });

  // 兜底必须和 VideoNode 的 selectedVideoModel 一致（没存 model 时显示列表第一个），
  // 否则会出现「界面按 A 模型显示上限、建边按 B 模型拦」。
  it("没存 model / 目录里查不到时回落到列表第一个", () => {
    expect(videoReferenceEnvelopeForNode(node("v", CANVAS_NODE_TYPES.video), catalog).image).toBe(
      VIDEO_REFERENCE_ENVELOPE.image,
    );
    expect(
      videoReferenceEnvelopeForNode(
        node("v", CANVAS_NODE_TYPES.video, { model: 'gone' }),
        catalog,
      ).image,
    ).toBe(VIDEO_REFERENCE_ENVELOPE.image);
  });

  it("目录还没加载出来（空列表）时退回默认包络", () => {
    expect(videoReferenceEnvelopeForNode(node("v", CANVAS_NODE_TYPES.video), [])).toEqual(
      VIDEO_REFERENCE_ENVELOPE,
    );
  });
});



