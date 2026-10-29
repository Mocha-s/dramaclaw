// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { apiCallEnvelope } from "./client";

export type TaskLaneName = "default" | "video" | "world" | "ffmpeg";

export interface TaskLaneLimit {
  globalConcurrency: number;
  globalQueueLimit: number;
  projectActiveLimit: number;
  projectUserActiveLimit: number;
}

export interface TaskLaneRuntimeSnapshot {
  active: number;
  queued: number;
  concurrency: number;
}

export interface TaskLimitsConfig {
  lanes: Record<TaskLaneName, TaskLaneLimit>;
}

export interface TaskLimitsEnvelope {
  ok: boolean;
  data?: TaskLimitsConfig;
  defaults?: TaskLimitsConfig;
  effective?: TaskLimitsConfig;
  runtime?: Partial<Record<TaskLaneName, TaskLaneRuntimeSnapshot>>;
  snapshot?: Partial<Record<TaskLaneName, TaskLaneRuntimeSnapshot>>;
  error?: string;
}

export async function getTaskLimits(
  signal?: AbortSignal,
): Promise<TaskLimitsEnvelope> {
  const response = signal
    ? await apiCallEnvelope<TaskLimitsConfig>("config/task-limits", { signal })
    : await apiCallEnvelope<TaskLimitsConfig>("config/task-limits");
  return response as TaskLimitsEnvelope;
}

export async function saveTaskLimits(
  value: TaskLimitsConfig,
): Promise<TaskLimitsEnvelope> {
  return (await apiCallEnvelope<TaskLimitsConfig>("config/task-limits", {
    method: "PUT",
    json: value,
  })) as TaskLimitsEnvelope;
}
