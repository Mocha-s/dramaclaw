// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  type AssetImageSourceKind,
  type AssetImageGenerationPatch,
  useAssetImageSourceSelection,
  useUpdateAssetImageSourceSelection,
} from "@/lib/queries/character-image-selection";
import {
  IMAGE_QUALITY_OPTIONS,
  IMAGE_SIZE_OPTIONS,
} from "@/features/canvas/nodes/shared/imageGenerationOptions";
import { cn } from "@/lib/utils";

export type CharacterImageSourceSelectProps = {
  project: string;
  kind?: AssetImageSourceKind;
  className?: string;
  disabled?: boolean;
  onSelectionChange?: (selection: string) => void;
};

function AssetImageParameterSelect({
  label,
  value,
  options,
  disabled,
  onValueChange,
}: {
  label: string;
  value: string;
  options: readonly string[];
  disabled: boolean;
  onValueChange: (value: string | null) => void;
}) {
  return (
    <Select value={value} disabled={disabled} onValueChange={onValueChange}>
      <SelectTrigger
        aria-label={label}
        className="h-8 rounded-[8px] border-white/10 bg-transparent px-3 text-xs font-normal shadow-none hover:bg-white/[0.04] dark:bg-transparent"
        disabled={disabled}
      >
        <span className="mr-2 text-muted-foreground">{label}</span>
        <SelectValue />
      </SelectTrigger>
      <SelectContent
        alignItemWithTrigger={false}
        className="rounded-md border border-white/10 bg-popover p-1 shadow-xl shadow-black/20 ring-0"
      >
        {options.map((option) => (
          <SelectItem
            key={option}
            value={option}
            className="min-h-8 gap-2 rounded-sm px-2 py-1.5 text-xs focus:bg-white/8 focus:text-current"
          >
            {option}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function CharacterImageSourceSelect({
  project,
  kind = "character",
  className,
  disabled,
  onSelectionChange,
}: CharacterImageSourceSelectProps) {
  const { t } = useTranslation();
  const selectionQuery = useAssetImageSourceSelection(project, kind);
  const updateSelection = useUpdateAssetImageSourceSelection(project, kind);
  const selection = selectionQuery.data?.data.image_source_selection ?? "";
  const options = selectionQuery.data?.data.options ?? {};
  const optionEntries = Object.entries(options);
  const selectedLabel = options[selection] ?? selection;
  const imageSize = selectionQuery.data?.data.image_size ?? "2K";
  const imageQuality = selectionQuery.data?.data.image_quality ?? "medium";
  const isDisabled =
    disabled ||
    selectionQuery.isLoading ||
    (selectionQuery.isFetching && !selectionQuery.data) ||
    updateSelection.isPending;

  const handleValueChange = async (patch: AssetImageGenerationPatch) => {
    if (updateSelection.isPending) return;
    if (Object.keys(patch).length === 0) return;
    try {
      await updateSelection.mutateAsync(patch);
      if (patch.image_source_selection) {
        onSelectionChange?.(patch.image_source_selection);
      }
    } catch {
      toast.error(t("characters.imageSource.saveFailed"));
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        value={selection}
        disabled={isDisabled}
        onValueChange={(value) => {
          if (value && value !== selection) void handleValueChange({ image_source_selection: value });
        }}
      >
        <SelectTrigger
          aria-label={t("characters.imageSource.label")}
          className={cn(
            "h-8 gap-0 rounded-[8px] border-white/10 bg-transparent px-3 text-xs font-normal shadow-none hover:bg-white/[0.04] dark:bg-transparent",
            className,
          )}
          disabled={isDisabled}
        >
          <span className="shrink-0 text-muted-foreground">
            {t("characters.imageSource.label")}
          </span>
          <span className="shrink-0 text-muted-foreground/50">&nbsp;·&nbsp;</span>
          <SelectValue>
            {selectedLabel || t("characters.imageSource.loading")}
          </SelectValue>
        </SelectTrigger>
        <SelectContent
          alignItemWithTrigger={false}
          className="rounded-md border border-white/10 bg-popover p-1 shadow-xl shadow-black/20 ring-0"
        >
          {optionEntries.map(([value, label]) => (
            <SelectItem
              key={value}
              value={value}
              className="min-h-8 gap-2 rounded-sm px-2 py-1.5 text-xs focus:bg-white/8 focus:text-current"
            >
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <AssetImageParameterSelect
        label={t("characters.imageSource.sizeLabel")}
        value={imageSize}
        options={IMAGE_SIZE_OPTIONS}
        disabled={isDisabled}
        onValueChange={(value) => {
          if (value && value !== imageSize) {
            void handleValueChange({ image_size: value });
          }
        }}
      />
      <AssetImageParameterSelect
        label={t("characters.imageSource.qualityLabel")}
        value={imageQuality}
        options={IMAGE_QUALITY_OPTIONS.map(({ value }) => value)}
        disabled={isDisabled}
        onValueChange={(value) => {
          if (value && value !== imageQuality) {
            void handleValueChange({ image_quality: value });
          }
        }}
      />
    </div>
  );
}
