// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { p } from "@/lib/api-path";
import { queryKeys } from "@/lib/query-keys";
import type { ErrorResponse, OkResponse } from "@/types/api";
import { FREEZONE_IMAGE_RESOLUTIONS } from "@/features/canvas/domain/freezoneGenerationResolutions";

export type ImageQuality = "auto" | "low" | "medium" | "high" | "xhigh" | "max";
export type RenderImageSize = (typeof FREEZONE_IMAGE_RESOLUTIONS)[number];

export interface RenderSettingsData {
  render_image_selection: string;
  render_image_size: RenderImageSize;
  options: Record<string, string>;
  sketch_aspect_padding: boolean;
  image_quality: ImageQuality;
}

export interface RenderSettingsUpdate {
  render_image_selection?: string;
  render_image_size?: RenderImageSize;
  sketch_aspect_padding?: boolean;
  image_quality?: ImageQuality;
}

export function useRenderSettings(project: string) {
  return useQuery({
    queryKey: queryKeys.renderSettings(project),
    queryFn: ({ signal }) =>
      api
        .get(p`api/v1/projects/${project}/render-settings`, { signal })
        .json<OkResponse<RenderSettingsData>>(),
    enabled: !!project,
  });
}

export function useUpdateRenderSettings(project: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: RenderSettingsUpdate) =>
      api
        .patch(p`api/v1/projects/${project}/render-settings`, { json: params })
        .json<OkResponse<RenderSettingsData> | ErrorResponse>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.renderSettings(project) });
    },
  });
}
