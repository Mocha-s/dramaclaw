// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsDialog } from "@/components/settings/settings-dialog";

const taskLimitsMocks = vi.hoisted(() => ({
  response: undefined as Record<string, unknown> | undefined,
  save: vi.fn(),
  refetch: vi.fn(),
}));

vi.mock("@/lib/runtime-config", () => ({ isCeRuntime: () => true }));
vi.mock("@/components/settings/freezone-skill-recipe-settings", () => ({
  FreezoneSkillRecipeSettings: () => null,
}));
vi.mock("@/lib/queries/model-gateway", () => ({
  useModelGatewayConfig: () => ({ data: undefined, isLoading: false }),
  useOfficialMediaCatalogStatus: () => ({ data: undefined, isLoading: false }),
  useSaveOfficialMediaCatalogPreferences: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useCheckOfficialMediaCatalog: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useNewApiChannelTypes: () => ({ data: undefined, isLoading: false }),
  useEnableOfficial: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useEnableCustom: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useEnableHybrid: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSetCustomLlmMode: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useEnableBrainClaw: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSaveAgentLlmConfig: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSaveOfficialConfig: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSaveBrainClawConfig: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSaveThirdPartyGatewayConfig: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useFetchThirdPartyModels: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSaveCapabilityDefaults: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useInitCustomNewApi: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSaveCustomChannel: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSaveCustomChannelsBatch: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSaveEmbeddingModel: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSaveMediaModels: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSaveProviderChannels: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useClearComfyUIConfig: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSaveMediaRelayConfig: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSyncProviderChannel: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useChannelModels: () => ({ data: undefined, isFetching: false, isError: false, refetch: vi.fn() }),
}));
vi.mock("@/lib/queries/task-limits", () => ({
  useTaskLimits: () => ({
    data: taskLimitsMocks.response,
    isLoading: false,
    isError: false,
    refetch: taskLimitsMocks.refetch,
  }),
  useSaveTaskLimits: () => ({ mutateAsync: taskLimitsMocks.save, isPending: false }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() } }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string; page?: string }) => {
      const values: Record<string, string> = {
        "settings.title": "设置",
        "settings.close": "关闭",
        "settings.navigationLabel": "设置分类",
        "settings.pages.models": "模型与渠道",
        "settings.pages.storage": "媒体存储",
        "settings.pages.taskLimits": "任务与队列",
        "settings.pages.freezoneSkills": "虾画 Skills",
        "settings.statusConfigured": `${options?.page ?? ""}已配置`,
        "settings.statusNotConfigured": `${options?.page ?? ""}未配置`,
        "settings.taskLimits.title": "任务与队列",
        "settings.taskLimits.description": "实时调整各类任务的并发和排队限制。",
        "settings.taskLimits.lane.default": "默认队列",
        "settings.taskLimits.lane.video": "视频队列",
        "settings.taskLimits.lane.world": "世界队列",
        "settings.taskLimits.lane.ffmpeg": "FFmpeg 队列",
        "settings.taskLimits.fields.globalConcurrency": "全局并发",
        "settings.taskLimits.fields.globalQueueLimit": "等待队列",
        "settings.taskLimits.fields.projectActiveLimit": "项目活动数",
        "settings.taskLimits.fields.projectUserActiveLimit": "用户活动数",
        "settings.taskLimits.headers.active": "活动",
        "settings.taskLimits.headers.queued": "排队",
        "settings.taskLimits.headers.concurrency": "并发",
        "settings.taskLimits.save": "保存队列设置",
        "settings.taskLimits.saved": "队列设置已保存",
        "settings.taskLimits.saving": "保存中…",
        "settings.taskLimits.invalid": "请输入范围内的整数。",
        "settings.taskLimits.loadFailed": "加载队列设置失败",
        "settings.taskLimits.saveFailed": "保存队列设置失败",
        "settings.modelConfig.title": "模型配置",
        "settings.modelConfig.description": "选择模型网关渠道",
      };
      return values[key] ?? options?.defaultValue ?? key;
    },
  }),
}));

function makeResponse(defaultConcurrency = 8, active = 1, queued = 2) {
  const data = {
    lanes: {
      default: { globalConcurrency: defaultConcurrency, globalQueueLimit: 512, projectActiveLimit: 12, projectUserActiveLimit: 12 },
      video: { globalConcurrency: 2, globalQueueLimit: 128, projectActiveLimit: 4, projectUserActiveLimit: 4 },
      world: { globalConcurrency: 1, globalQueueLimit: 64, projectActiveLimit: 2, projectUserActiveLimit: 2 },
      ffmpeg: { globalConcurrency: 1, globalQueueLimit: 64, projectActiveLimit: 2, projectUserActiveLimit: 2 },
    },
  };
  return {
    ok: true,
    data,
    defaults: data,
    snapshot: {
      default: { active, queued, concurrency: defaultConcurrency },
      video: { active: 0, queued: 1, concurrency: 2 },
      world: { active: 0, queued: 0, concurrency: 1 },
      ffmpeg: { active: 0, queued: 0, concurrency: 1 },
    },
  };
}

function renderSettingsDialog() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <SettingsDialog open onOpenChange={vi.fn()} />
    </QueryClientProvider>,
  );
}

function openTaskLimits() {
  fireEvent.click(screen.getByRole("button", { name: "任务与队列" }));
}

beforeEach(() => {
  taskLimitsMocks.response = makeResponse();
  taskLimitsMocks.save.mockReset();
  taskLimitsMocks.refetch.mockReset().mockResolvedValue({ data: taskLimitsMocks.response });
});

describe("SettingsDialog task limits", () => {
  it("renders all four queue lanes with four editable limits and live counts", () => {
    renderSettingsDialog();
    openTaskLimits();

    expect(screen.getByRole("heading", { name: "任务与队列" })).toBeInTheDocument();
    for (const lane of ["default", "video", "world", "ffmpeg"]) {
      expect(within(screen.getByTestId(`task-limits-lane-${lane}`)).getAllByRole("spinbutton")).toHaveLength(4);
    }
    expect(screen.getByTestId("task-limits-active-default")).toHaveTextContent("1");
    expect(screen.getByTestId("task-limits-queued-default")).toHaveTextContent("2");
  });

  it("blocks invalid values and restores the saved value after a server error", async () => {
    renderSettingsDialog();
    openTaskLimits();
    const row = screen.getByTestId("task-limits-lane-video");
    const concurrency = within(row).getAllByRole("spinbutton")[0];
    fireEvent.change(concurrency, { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "保存队列设置" }));
    expect(taskLimitsMocks.save).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("请输入范围内的整数。");

    taskLimitsMocks.save.mockRejectedValueOnce(new Error("server rejected"));
    fireEvent.change(concurrency, { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "保存队列设置" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("server rejected"));
    expect(concurrency).toHaveValue(2);
  });

  it("refreshes the effective snapshot after saving", async () => {
    const refreshed = makeResponse(10, 3, 7);
    taskLimitsMocks.save.mockResolvedValue({ ok: true, data: refreshed.data, effective: refreshed.data, snapshot: refreshed.snapshot });
    taskLimitsMocks.refetch.mockResolvedValue({ data: refreshed });
    renderSettingsDialog();
    openTaskLimits();
    const row = screen.getByTestId("task-limits-lane-default");
    const concurrency = within(row).getAllByRole("spinbutton")[0];
    fireEvent.change(concurrency, { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "保存队列设置" }));
    await waitFor(() => expect(taskLimitsMocks.refetch).toHaveBeenCalled());
    expect(concurrency).toHaveValue(10);
    expect(screen.getByTestId("task-limits-active-default")).toHaveTextContent("3");
    expect(screen.getByTestId("task-limits-queued-default")).toHaveTextContent("7");
    expect(screen.getByRole("status")).toHaveTextContent("队列设置已保存");
  });

  it("keeps successful PUT values when the follow-up snapshot refresh fails", async () => {
    const saved = makeResponse(10, 3, 7);
    taskLimitsMocks.save.mockResolvedValue({
      ok: true,
      data: saved.data,
      effective: saved.data,
      snapshot: saved.snapshot,
    });
    taskLimitsMocks.refetch.mockResolvedValue({
      error: new Error("snapshot refresh failed"),
    });

    renderSettingsDialog();
    openTaskLimits();
    const row = screen.getByTestId("task-limits-lane-default");
    const concurrency = within(row).getAllByRole("spinbutton")[0];
    fireEvent.change(concurrency, { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "保存队列设置" }));

    expect(await screen.findByRole("status")).toHaveTextContent("队列设置已保存");
    expect(concurrency).toHaveValue(10);
    expect(screen.getByTestId("task-limits-active-default")).toHaveTextContent("3");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
