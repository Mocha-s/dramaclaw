// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  ProviderModelPicker,
  type ModelOption,
} from "@/features/canvas/ui/ProviderModelPicker";

// 用真实中文词条渲染：新增的 modelPicker.* 词条漏配时这里会直接抛错。
vi.mock("react-i18next", async () => {
  const { zhT } = await import("../../helpers/i18n-fixtures");
  return {
    useTranslation: () => ({
      t: (key: string, options?: Record<string, unknown>) => zhT(key, options),
    }),
  };
});
vi.mock("@/features/canvas/hooks/useFreezoneImageModels", () => ({
  useFreezoneImageModels: () => ({ models: [], isLoading: false, isFallback: false }),
  isAuthoritativeEmptyCatalog: () => false,
}));
vi.mock("@/features/canvas/hooks/useFreezoneVideoModels", () => ({
  useFreezoneVideoModels: () => ({ models: [], isLoading: false, isFallback: false }),
}));

const models: ModelOption[] = [
  {
    id: "LingShan-G2",
    providerId: "newapi",
    apiModel: "LingShan-G2",
    label: "LingShan-G2",
    resolutionOptions: ["1K", "2K"],
  },
  {
    id: "seedream-5.0-pro",
    providerId: "newapi",
    apiModel: "seedream-5.0-pro",
    label: "Seedream 5.0 Pro",
  },
  {
    id: "seedance-2.0",
    providerId: "seedance",
    apiModel: "seedance-2.0",
    label: "Seedance2.0",
    minDuration: 4,
    maxDuration: 15,
    supportsGenerateAudio: true,
  },
];

function openPicker() {
  render(
    <ProviderModelPicker
      selectedModelId={models[0].id}
      models={models}
      onChange={() => {}}
      domain="video"
    />,
  );
  // 触发器与选项同名，第一个是触发器。
  fireEvent.click(screen.getAllByRole("button", { name: /LingShan-G2/ })[0]);
  return screen.getByRole("searchbox", { name: "搜索模型" });
}

describe("model picker quick search", () => {
  it("filters the list by model name", () => {
    const box = openPicker();
    expect(screen.getByText("Seedream 5.0 Pro")).toBeInTheDocument();

    fireEvent.change(box, { target: { value: "seedream" } });

    expect(screen.getByText("Seedream 5.0 Pro")).toBeInTheDocument();
    expect(screen.queryByText("Seedance2.0")).not.toBeInTheDocument();
    // 只剩触发器上那个选中模型名，列表项已被过滤掉。
    expect(screen.getAllByText("LingShan-G2")).toHaveLength(1);
  });

  it("matches the upstream model id too", () => {
    const box = openPicker();
    fireEvent.change(box, { target: { value: "seedance-2.0" } });
    expect(screen.getByText("Seedance2.0")).toBeInTheDocument();
    expect(screen.queryByText("Seedream 5.0 Pro")).not.toBeInTheDocument();
  });

  it("says so when nothing matches, instead of looking like an empty catalog", () => {
    const box = openPicker();
    fireEvent.change(box, { target: { value: "zzz" } });
    expect(screen.getByText("没有匹配的模型")).toBeInTheDocument();
    expect(screen.queryByText("暂无可用模型")).not.toBeInTheDocument();
  });

  it("shows each model's usage info under its name", () => {
    openPicker();
    expect(screen.getByText("1K / 2K")).toBeInTheDocument();
    expect(screen.getByText("4-15s · 有声")).toBeInTheDocument();
  });
});
