// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
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

describe("model picker price order and automatic selection", () => {
  const pricedModels: ModelOption[] = [
    { ...models[0], priceValue: 0.8 },
    { ...models[1], priceValue: 0.2 },
    { ...models[2], priceValue: 0.1 },
  ];

  function openControlledPicker(
    options = pricedModels,
    domain: "image" | "video" = "image",
    getOptionDisabledReason?: (model: ModelOption) => string | null,
  ) {
    const onChange = vi.fn();
    function Picker() {
      const [selectedModelId, setSelectedModelId] = useState(options[0].id);
      return (
        <ProviderModelPicker
          selectedModelId={selectedModelId}
          models={options}
          domain={domain}
          getOptionDisabledReason={getOptionDisabledReason}
          onChange={(id) => {
            onChange(id);
            setSelectedModelId(id);
          }}
        />
      );
    }
    render(<Picker />);
    const trigger = screen.getByRole("button");
    fireEvent.click(trigger);
    return { box: screen.getByRole("searchbox"), trigger, onChange };
  }

  it("sorts by default price, keeps equal prices stable, and puts unknown prices last", () => {
    const options: ModelOption[] = [
      { ...models[0], id: "unknown", label: "Unknown price" },
      { ...models[0], id: "costly", label: "Costly", priceValue: 2 },
      { ...models[0], id: "free", label: "Free", priceValue: 0 },
      { ...models[0], id: "cheap", label: "Cheap", priceValue: 0.1 },
      {
        ...models[0], id: "tied", label: "Same price", priceValue: 0.1,
        priceTiers: [{ label: "1K", value: 0.1 }, { label: "4K", value: 4 }],
      },
    ];
    const { trigger, onChange } = openControlledPicker(options);

    const buttons = screen.getAllByRole("button").slice(1);
    ["Free", "Cheap", "Same price", "Costly", "Unknown price"].forEach((label, i) => {
      expect(buttons[i]).toHaveTextContent(label);
    });
    expect(options.map((model) => model.id)).toEqual(["unknown", "costly", "free", "cheap", "tied"]);
    expect(trigger).toHaveTextContent("Unknown price");
    expect(onChange).not.toHaveBeenCalled();
  });

  it.each(["image", "video"] as const)("selects the cheapest matching %s model as the query changes", (domain) => {
    const { box, trigger, onChange } = openControlledPicker(pricedModels, domain);

    fireEvent.change(box, { target: { value: "  SEED  " } });
    expect(trigger).toHaveTextContent("Seedance2.0");
    expect(onChange).toHaveBeenLastCalledWith("seedance-2.0");
    expect(screen.getAllByRole("button")[1]).toHaveTextContent("Seedance2.0");
    expect(box).toHaveFocus();

    fireEvent.change(box, { target: { value: "seedr" } });
    expect(trigger).toHaveTextContent("Seedream 5.0 Pro");
    expect(onChange).toHaveBeenLastCalledWith("seedream-5.0-pro");
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it("skips disabled matches and preserves the selection when no enabled match exists", () => {
    const { box, trigger, onChange } = openControlledPicker(
      pricedModels,
      "video",
      (model) => model.id === "seedance-2.0" ? "需要连接视频节点" : null,
    );

    fireEvent.change(box, { target: { value: "seed" } });
    expect(trigger).toHaveTextContent("Seedream 5.0 Pro");
    expect(screen.getByRole("button", { name: /Seedance2.0/ })).toHaveAttribute("aria-disabled", "true");

    fireEvent.change(box, { target: { value: "seedance" } });
    expect(trigger).toHaveTextContent("Seedream 5.0 Pro");
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("preserves the selected model for empty and unmatched queries without reselecting it", () => {
    const { box, trigger, onChange } = openControlledPicker();
    fireEvent.change(box, { target: { value: "seed" } });
    expect(trigger).toHaveTextContent("Seedance2.0");

    for (const query of ["seedance", "zzz", "   ", ""]) {
      fireEvent.change(box, { target: { value: query } });
      expect(trigger).toHaveTextContent("Seedance2.0");
    }
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("keeps a manual selection when the picker closes and reopens", () => {
    const { box, trigger, onChange } = openControlledPicker();
    fireEvent.change(box, { target: { value: "seed" } });
    expect(trigger).toHaveTextContent("Seedance2.0");

    fireEvent.click(screen.getByRole("button", { name: /Seedream 5.0 Pro/ }));
    expect(trigger).toHaveTextContent("Seedream 5.0 Pro");
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    expect(screen.getByRole("searchbox")).toHaveValue("");
    expect(trigger).toHaveTextContent("Seedream 5.0 Pro");
    expect(onChange).toHaveBeenCalledTimes(2);
  });
});

describe("model picker usage info", () => {
  function openWith(models: ModelOption[], domain: "image" | "video" = "image") {
    render(
      <ProviderModelPicker
        selectedModelId={models[0].id}
        models={models}
        onChange={() => {}}
        domain={domain}
      />,
    );
    fireEvent.click(screen.getAllByRole("button", { name: new RegExp(models[0].label) })[0]);
  }

  it("shows the upstream description and the per-image price", () => {
    openWith([
      {
        id: "gpt-image-2-4k",
        providerId: "newapi",
        apiModel: "gpt-image-2-4k",
        label: "GPT Image 2 4K",
        description: "图片创作与参考编辑，固定档位一次 1 张",
        priceValue: 0.11,
        priceUnit: "image",
      },
    ]);

    expect(screen.getByText("图片创作与参考编辑，固定档位一次 1 张")).toBeInTheDocument();
    expect(screen.getByText("$0.110/张")).toBeInTheDocument();
  });

  it("marks a lowest-tier price as a starting price and uses per-second units", () => {
    openWith([
      {
        id: "sd16-seedance-2.0",
        providerId: "newapi",
        apiModel: "sd16-seedance-2.0",
        label: "SD16 Seedance",
        priceValue: 24,
        priceUnit: "request",
        priceFrom: true,
      },
      {
        id: "seedance2.0-720p",
        providerId: "newapi",
        apiModel: "seedance2.0-720p",
        label: "Seedance 720p",
        priceValue: 0.1,
        priceUnit: "second",
      },
    ]);

    expect(screen.getByText("起 $24.000/次")).toBeInTheDocument();
    expect(screen.getByText("$0.100/秒")).toBeInTheDocument();
  });

  it("lists every tier price instead of one number, and keeps the unit at the end", () => {
    openWith([
      {
        id: "flux-3-image",
        providerId: "newapi",
        apiModel: "flux-3-image",
        label: "Flux 3 Image",
        priceValue: 0.7577,
        priceUnit: "image",
        priceTiers: [
          { label: "768sq", value: 0.7577 },
          { label: "1k", value: 0.887 },
          { label: "2k", value: 1.848 },
        ],
      },
    ]);

    // 换行后整行仍挂在 title 上，可悬停查看。
    expect(screen.getByTitle("768sq $0.758 · 1k $0.887 · 2k $1.848/张")).toBeInTheDocument();
    // 档位名是次要样式，档位价跟单价格同款。
    expect(screen.getByText("768sq").className).toContain("text-text-muted/80");
    expect(screen.getByText("$0.758").className).toContain("text-[11px]");
    expect(screen.getByText("/张")).toBeInTheDocument();
  });

  it("styles a tier price exactly like a single price", () => {
    openWith([
      {
        id: "gpt-image-2-4k",
        providerId: "newapi",
        apiModel: "gpt-image-2-4k",
        label: "GPT Image 2 4K",
        priceValue: 0.106,
        priceUnit: "image",
      },
      {
        id: "flux-3-image",
        providerId: "newapi",
        apiModel: "flux-3-image",
        label: "Flux 3 Image",
        priceValue: 0.758,
        priceUnit: "image",
        priceTiers: [
          { label: "768sq", value: 0.758 },
          { label: "1k", value: 0.887 },
        ],
      },
    ]);

    for (const price of [screen.getByText("$0.106/张"), screen.getByText("$0.758")]) {
      expect(price.className).toContain("text-[11px]");
      expect(price.className).toContain("font-medium");
      expect(price.className).toContain("text-text-dark/90");
    }
  });

  it("shows nothing extra when the plaza has no price for the model", () => {
    openWith([
      {
        id: "sd8-seedance-2.5-s",
        providerId: "newapi",
        apiModel: "sd8-seedance-2.5-s",
        label: "Seedance 2.5 S",
      },
    ]);

    expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
  });
});
