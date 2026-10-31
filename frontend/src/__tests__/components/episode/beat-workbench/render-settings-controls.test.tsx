// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { mutateAsync } = vi.hoisted(() => ({ mutateAsync: vi.fn() }));

vi.mock("@/lib/queries/render-settings", () => ({
  useRenderSettings: () => ({
    data: {
      data: {
        render_image_selection: "gpt-image-2",
        render_image_size: "1K",
        image_quality: "medium",
        options: { "gpt-image-2": "GPT Image 2" },
        sketch_aspect_padding: true,
      },
    },
    isLoading: false,
  }),
  useUpdateRenderSettings: () => ({ isPending: false, mutateAsync }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { RenderModelSelect } from "@/components/episode/beat-workbench/render-settings-controls";

describe("RenderModelSelect image quality", () => {
  beforeEach(() => mutateAsync.mockReset().mockResolvedValue({ ok: true }));

  it("shows all global image qualities and persists max", async () => {
    const user = userEvent.setup();
    render(<RenderModelSelect project="demo" />);

    const qualityButton = screen.getByRole("combobox", {
      name: "episode.renderSettings.quality",
    });
    expect(qualityButton).toHaveTextContent("episode.renderSettings.qualityOptions.medium");

    await user.click(qualityButton);
    for (const quality of ["auto", "low", "medium", "high", "xhigh", "max"]) {
      expect(
        screen.getByRole("option", {
          name: `episode.renderSettings.qualityOptions.${quality}`,
        }),
      ).toBeInTheDocument();
    }
    await user.click(screen.getByRole("option", {
      name: "episode.renderSettings.qualityOptions.max",
    }));

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({ image_quality: "max" }),
    );
  });

  it("shows render image sizes and persists 2K", async () => {
    const user = userEvent.setup();
    render(<RenderModelSelect project="demo" />);

    const sizeButton = screen.getByRole("combobox", {
      name: "episode.renderSettings.imageSize",
    });
    expect(sizeButton).toHaveTextContent("1K");

    await user.click(sizeButton);
    await user.click(screen.getByRole("option", { name: "2K" }));

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({ render_image_size: "2K" }),
    );
  });
});
