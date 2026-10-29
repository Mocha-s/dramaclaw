// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import type { MediaModelParameterDefinition } from "@/api/ops";

const SERVER_MANAGED_PARAMETER_KEYS = new Set(["thinking_level"]);
const MODE_ALIASES: Record<string, string> = {
  textToVideo: "text_to_video",
  firstFrame: "first_frame",
  imageToVideo: "image_to_video",
  firstLastFrame: "first_last_frame",
  imageReference: "image_reference",
  allReference: "all_reference",
  videoEdit: "video_edit",
  videoExtend: "video_extend",
};

export function userSelectableMediaModelParameters(
  parameters: MediaModelParameterDefinition[] | undefined,
  mode?: string,
): MediaModelParameterDefinition[] {
  const normalizedMode = mode ? MODE_ALIASES[mode] ?? mode : "";
  return (parameters ?? []).filter((item) => {
    if (item.userSelectable === false) return false;
    if (
      SERVER_MANAGED_PARAMETER_KEYS.has(item.key) &&
      item.userSelectable !== true
    ) {
      return false;
    }
    if (!item.modes?.length) return true;
    return Boolean(
      mode && (item.modes.includes(mode) || item.modes.includes(normalizedMode)),
    );
  });
}

export function filterMediaModelParamsForMode(
  parameters: MediaModelParameterDefinition[] | undefined,
  values: Record<string, unknown> | undefined,
  mode: string,
): Record<string, unknown> {
  const allowed = new Set(
    userSelectableMediaModelParameters(parameters, mode).map((item) => item.key),
  );
  return Object.fromEntries(
    Object.entries(values ?? {}).filter(([key]) => allowed.has(key)),
  );
}
