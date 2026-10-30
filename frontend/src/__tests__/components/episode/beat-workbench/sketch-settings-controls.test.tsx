// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { mutateAsync } = vi.hoisted(() => ({ mutateAsync: vi.fn() }));

vi.mock("@/lib/queries/sketch-settings", () => ({
  useSketchSettings: () => ({
    data: {
      data: {
        sketch_image_selection: "openrouter_nanobanana2",
        sketch_image_size: "1K",
        options: { openrouter_nanobanana2: "OpenRouter NanoBanana 2" },
      },
    },
    isLoading: false,
  }),
  useUpdateSketchSettings: () => ({ isPending: false, mutateAsync }),
}));

import {
  SketchAspectCheckbox,
  SketchModelSelect,
} from "@/components/episode/beat-workbench/sketch-settings-controls";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      if (key === "episode.sketchSettings.aspectRatio") return "画幅";
      return key;
    },
  }),
}));

describe("SketchAspectCheckbox", () => {
  it("uses a dropdown with explicit 2:3 and 16:9 choices", async () => {
    const user = userEvent.setup();
    const onAspectRatioChange = vi.fn();

    render(
      <SketchAspectCheckbox
        aspectRatio="16:9"
        onAspectRatioChange={onAspectRatioChange}
        flat
      />,
    );

    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "画幅" })).toHaveTextContent("16:9");

    await user.click(screen.getByRole("combobox", { name: "画幅" }));
    expect(await screen.findByRole("option", { name: "2:3" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "16:9" })).toBeInTheDocument();

    await user.click(screen.getByRole("option", { name: "2:3" }));

    expect(onAspectRatioChange).toHaveBeenCalledWith("2:3");
  });
});

describe("SketchModelSelect image size", () => {
  beforeEach(() => mutateAsync.mockReset().mockResolvedValue({ ok: true }));

  it("offers all global image sizes and persists 4K", async () => {
    const user = userEvent.setup();
    render(<SketchModelSelect project="demo" />);

    const sizeSelect = screen.getByRole("combobox", {
      name: "episode.sketchSettings.imageSize",
    });
    expect(sizeSelect).toHaveTextContent("1K");
    await user.click(sizeSelect);

    for (const size of ["1K", "2K", "4K"]) {
      expect(screen.getByRole("option", { name: size })).toBeInTheDocument();
    }
    await user.click(screen.getByRole("option", { name: "4K" }));

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({ sketch_image_size: "4K" }),
    );
  });
});
