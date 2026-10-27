import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getTaskLimits,
  saveTaskLimits,
  type TaskLimitsConfig,
} from "@/api/taskLimits";

export type { TaskLaneLimit, TaskLaneName, TaskLimitsConfig, TaskLimitsEnvelope } from "@/api/taskLimits";

const taskLimitsQueryKey = ["config", "task-limits"] as const;

export function useTaskLimits(enabled = true) {
  return useQuery({
    queryKey: taskLimitsQueryKey,
    queryFn: ({ signal }) => getTaskLimits(signal),
    enabled,
  });
}

export function useSaveTaskLimits() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (value: TaskLimitsConfig) => saveTaskLimits(value),
    onSuccess: (response) => {
      queryClient.setQueryData(taskLimitsQueryKey, response);
    },
  });
}
