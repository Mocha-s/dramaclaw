// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import {
  isAudioNode,
  isExportImageNode,
  isImageEditNode,
  isImageGenNode,
  isStoryboardGenNode,
  isUploadNode,
  isVideoNode,
  type CanvasNode,
} from '@/features/canvas/domain/canvasNodes';

/**
 * 视频节点的**素材连线上限**——建边时就拦，而不是等到提交才报错。
 *
 * 这里卡的是「任何模型 / 任何模式都消费不了」的硬顶，不是当前模式那一格：
 * 首帧只吃 1 张图、首尾帧只吃 2 张，但接上第 2 / 第 3 张图时 VideoNode 的 effect
 * 会自动把模式切到全能参考 / 图片参考；同理连音频到 Seedance 1.x 会自动把模型换成
 * 2.0。按当前模式那格拦，等于把这些自动救场全部拦死 —— 用户连不上第二张图，也就
 * 永远触发不了「首帧 → 全能参考」的自动切换。
 *
 * 所以口径取**能力包络**：图 30 / 视频 10 / 音频 10 / 总数 30，与后端 omni-gen 的
 * `validate_omni_reference_limits`（src/novelvideo/freezone/video_node.py）
 * 逐项一致。超出这条线由后端报错提示。
 *
 * 表里更小的那些数字（首帧 1 / 首尾帧 2 / 视频编辑 5 张参考图）继续由「自动切模式」
 * 和提交守卫负责，不在建边这层拦。
 *
 * 30/10/10/30 只是**没有媒体目录配置时的默认值**，不是所有模型的硬上限 ——
 * 见 `videoReferenceEnvelopeForModel`。
 */
export const VIDEO_REFERENCE_ENVELOPE = {
  image: 30,
  video: 10,
  audio: 10,
  total: 30,
} as const;

export interface VideoReferenceEnvelope {
  image: number;
  video: number;
  audio: number;
  total: number;
}

/** 媒体目录里与引用上限相关的那几个字段（`ModelOption` 的子集）。 */
export interface VideoReferenceLimitModel {
  referenceImageMax?: number | null;
  referenceVideoMax?: number | null;
  referenceAudioMax?: number | null;
}

/**
 * 所选模型的**有效**包络：媒体目录配置优先，没配才用 9/3/3/12。
 *
 * 与后端 `_catalog_reference_limits`（api/routes/freezone.py:7004）逐条对齐，包括
 * total 的算法：三项里只要有任意一项来自目录，总数就取三项之和；一项都没配才是 12。
 * 不这么算的话，一个目录里配了 image=10 的合法模型会在第 10 张被前端拦掉，请求永远
 * 到不了本来会接受它的后端 —— 上限比后端严等于把管理员配出来的能力吞掉。
 *
 * 只认非负整数，与后端 `type(value) is int and value >= 0` 同一口径：null / 负数 /
 * 小数一律当作没配。
 */
export function videoReferenceEnvelopeForModel(
  model: VideoReferenceLimitModel | null | undefined,
): VideoReferenceEnvelope {
  const fromCatalog = (value: number | null | undefined): number | null =>
    typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null;

  const image = fromCatalog(model?.referenceImageMax);
  const video = fromCatalog(model?.referenceVideoMax);
  const audio = fromCatalog(model?.referenceAudioMax);
  const resolved = {
    image: image ?? VIDEO_REFERENCE_ENVELOPE.image,
    video: video ?? VIDEO_REFERENCE_ENVELOPE.video,
    audio: audio ?? VIDEO_REFERENCE_ENVELOPE.audio,
  };
  const hasCatalogValue = image !== null || video !== null || audio !== null;
  return {
    ...resolved,
    total: hasCatalogValue
      ? resolved.image + resolved.video + resolved.audio
      : VIDEO_REFERENCE_ENVELOPE.total,
  };
}

/**
 * 建边校验拿不到 React 上下文，模型只能由调用方解析后喂进来。默认值保持 9/3/3/12：
 * 传不进模型时（测试、还没加载出目录）行为与改动之前一致。
 */
export type VideoReferenceEnvelopeResolver = (
  videoNode: CanvasNode,
) => VideoReferenceEnvelope;

const DEFAULT_ENVELOPE_RESOLVER: VideoReferenceEnvelopeResolver = () => ({
  ...VIDEO_REFERENCE_ENVELOPE,
});

export type VideoReferenceMediaKind = 'image' | 'video' | 'audio';

/**
 * 把一个上游节点归类成图片 / 视频 / 音频素材，非素材节点（文本、脚本…）返回 null。
 *
 * 与 VideoNode 里 `upstreamTypeCounts` 同一口径：**按节点类型算，空节点也算**
 * （先连节点后填素材是正常顺序）。唯一的例外是 `data.videoUrl` 优先——资产库选入
 * 的视频是 upload 节点，只看类型会被误当图片。
 */
export function classifyVideoReferenceMedia(
  node: CanvasNode | null | undefined,
): VideoReferenceMediaKind | null {
  if (!node) return null;
  const videoUrl = (node.data as { videoUrl?: unknown }).videoUrl;
  if (isVideoNode(node) || (typeof videoUrl === 'string' && videoUrl.length > 0)) {
    return 'video';
  }
  if (isAudioNode(node)) return 'audio';
  if (
    isImageGenNode(node) ||
    isUploadNode(node) ||
    isImageEditNode(node) ||
    isExportImageNode(node) ||
    isStoryboardGenNode(node)
  ) {
    return 'image';
  }
  return null;
}


/**
 * 建边校验：已放开前端限制，由网关在提交时报错。
 * 调用方保持不变，函数始终返回 null（不拦截）。
 */
export function videoReferenceConnectionRejection(
  _nodes: readonly CanvasNode[],
  _edges: readonly { source: string; target: string }[],
  _connection: { source?: string | null; target?: string | null },
  _resolveEnvelope: VideoReferenceEnvelopeResolver = DEFAULT_ENVELOPE_RESOLVER,
): string | null {
  return null;
}

/**
 * 类型变更后的重算：已放开前端限制，始终返回空（不强删溢出边）。
 * 超限由网关在提交时报错。
 */
export function overflowingVideoReferenceEdgeIds(
  _nodes: readonly CanvasNode[],
  _edges: readonly { id: string; source: string; target: string }[],
  _videoTargetId: string,
  _resolveEnvelope: VideoReferenceEnvelopeResolver = DEFAULT_ENVELOPE_RESOLVER,
): string[] {
  return [];
}
