// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import i18next from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { SketchPromptEditor } from "@/components/episode/beat-workbench/sketch-prompt-editor";

const mutateAsync = vi.fn(async () => ({ ok: true, data: {} }));

vi.mock("@/lib/queries/scripts", () => ({
  useUpdateBeat: () => ({ mutateAsync, isPending: false }),
}));

vi.mock("@/lib/queries/sketches", () => ({
  useSketchBrief: () => ({
    data: {
      ok: true,
      data: {
        beat_number: 10,
        kind: "prop_insert",
        has_characters: false,
        allow_unnamed_people: false,
        no_characters: true,
        description: "寻迹牌 [XJP_885e]上的山脊纹样泛起微光",
        prop_anchor_lines: ["寻迹牌 — FORM: 横向山形木牌，单手可握"],
        attach_prop_refs: true,
      },
    },
    isLoading: false,
  }),
}));

const i18n = i18next.createInstance();

beforeAll(async () => {
  await i18n.use(initReactI18next).init({
    lng: "zh",
    fallbackLng: "zh",
    interpolation: { escapeValue: false },
    resources: {
      zh: {
        translation: {
          episode: {
            workbench: {
              sketch: {
                promptEditorTitle: "草图提示词",
                promptEditorPlaceholder: "补充或覆盖本拍的草图描述",
                promptModeAppend: "追加",
                promptModeOverride: "覆盖",
                promptPreviewLabel: "最终面板文本",
                promptKindNormal: "普通",
                promptKindBlack: "黑场",
                promptKindTitleCard: "字幕卡",
                promptKindPropInsert: "道具特写",
                promptKindNoCharacters: "无人物",
                promptKindUnnamedPeople: "仅无名人物",
                promptSave: "保存",
                promptSaved: "草图提示词已保存",
                promptSaveFailed: "草图提示词保存失败",
              },
            },
          },
        },
      },
    },
  });
});

function renderEditor() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <I18nextProvider i18n={i18n}>
        <SketchPromptEditor
          project="demo"
          episode={1}
          beat={{ beat_number: 10, narration_segment: "", visual_description: "[[寻迹牌]]泛起微光", sketch_prompt: "", sketch_prompt_mode: "append" }}
        />
      </I18nextProvider>
    </QueryClientProvider>,
  );
}

describe("SketchPromptEditor", () => {
  it("shows the brief preview with kind badges", async () => {
    renderEditor();
    await userEvent.click(screen.getByRole("button", { name: "草图提示词" }));

    expect(screen.getByText("道具特写")).toBeInTheDocument();
    expect(screen.getByText("无人物")).toBeInTheDocument();
    expect(screen.getByText(/寻迹牌 \[XJP_885e\]上的山脊纹样泛起微光/)).toBeInTheDocument();
    expect(screen.getByText(/FORM: 横向山形木牌/)).toBeInTheDocument();
  });

  it("saves prompt text and mode through useUpdateBeat", async () => {
    renderEditor();
    await userEvent.click(screen.getByRole("button", { name: "草图提示词" }));
    await userEvent.type(screen.getByPlaceholderText("补充或覆盖本拍的草图描述"), "巴掌大小的木牌挂件");
    await userEvent.click(screen.getByRole("button", { name: "覆盖" }));
    expect(screen.getByRole("button", { name: "覆盖" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(mutateAsync).toHaveBeenCalledWith({
      beatNum: 10,
      data: { sketch_prompt: "巴掌大小的木牌挂件", sketch_prompt_mode: "override" },
    });
  });
});
