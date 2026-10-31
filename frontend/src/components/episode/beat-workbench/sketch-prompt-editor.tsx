// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import type { TFunction } from "i18next";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { queryKeys } from "@/lib/query-keys";
import { useUpdateBeat } from "@/lib/queries/scripts";
import { useSketchBrief, type SketchBriefData } from "@/lib/queries/sketches";
import { cn } from "@/lib/utils";
import type { Beat } from "@/types/episode";

type PromptMode = "append" | "override";

interface SketchPromptEditorProps {
  project: string;
  episode: number;
  beat: Beat;
}

function kindLabels(brief: SketchBriefData, t: TFunction): string[] {
  const labels: string[] = [];
  if (brief.kind === "black") labels.push(t("episode.workbench.sketch.promptKindBlack"));
  else if (brief.kind === "title_card") labels.push(t("episode.workbench.sketch.promptKindTitleCard"));
  else if (brief.kind === "prop_insert") labels.push(t("episode.workbench.sketch.promptKindPropInsert"));
  else labels.push(t("episode.workbench.sketch.promptKindNormal"));
  if (brief.no_characters) labels.push(t("episode.workbench.sketch.promptKindNoCharacters"));
  else if (brief.allow_unnamed_people && !brief.has_characters) {
    labels.push(t("episode.workbench.sketch.promptKindUnnamedPeople"));
  }
  return labels;
}

export function SketchPromptEditor({ project, episode, beat }: SketchPromptEditorProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const update = useUpdateBeat(project, episode);
  const briefQuery = useSketchBrief(project, episode, beat.beat_number);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(beat.sketch_prompt ?? "");
  const [mode, setMode] = useState<PromptMode>(beat.sketch_prompt_mode === "override" ? "override" : "append");

  useEffect(() => {
    setDraft(beat.sketch_prompt ?? "");
    setMode(beat.sketch_prompt_mode === "override" ? "override" : "append");
  }, [beat.beat_number, beat.sketch_prompt, beat.sketch_prompt_mode]);

  const savedMode: PromptMode = beat.sketch_prompt_mode === "override" ? "override" : "append";
  const dirty = draft !== (beat.sketch_prompt ?? "") || mode !== savedMode;
  const brief = briefQuery.data?.ok ? briefQuery.data.data : null;

  const handleSave = async () => {
    try {
      await update.mutateAsync({
        beatNum: beat.beat_number,
        data: { sketch_prompt: draft, sketch_prompt_mode: mode },
      });
      await qc.invalidateQueries({ queryKey: queryKeys.sketchBrief(project, episode, beat.beat_number) });
      toast.success(t("episode.workbench.sketch.promptSaved"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("episode.workbench.sketch.promptSaveFailed"));
    }
  };

  return (
    <div className="col-span-2 flex flex-col gap-2 pt-1">
      <Button size="xs" variant="ghost" className="w-fit gap-1" onClick={() => setOpen((v) => !v)}>
        {open ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
        {t("episode.workbench.sketch.promptEditorTitle")}
      </Button>
      {open && (
        <div className="flex flex-col gap-2 rounded-md border border-white/10 bg-white/[0.03] p-2">
          <div className="flex items-center gap-1.5">
            {(["append", "override"] as PromptMode[]).map((value) => (
              <Button
                key={value}
                size="xs"
                variant={mode === value ? "default" : "outline"}
                onClick={() => setMode(value)}
              >
                {value === "append"
                  ? t("episode.workbench.sketch.promptModeAppend")
                  : t("episode.workbench.sketch.promptModeOverride")}
              </Button>
            ))}
            <Button
              size="xs"
              className="ml-auto"
              disabled={!dirty || update.isPending}
              onClick={() => void handleSave()}
            >
              {update.isPending ? <Loader2 className="size-3 animate-spin" /> : null}
              {t("episode.workbench.sketch.promptSave")}
            </Button>
          </div>
          <Textarea
            rows={3}
            maxLength={500}
            value={draft}
            placeholder={t("episode.workbench.sketch.promptEditorPlaceholder")}
            onChange={(event) => setDraft(event.target.value)}
          />
          {brief && (
            <div className="flex flex-col gap-1 text-xs text-muted-foreground">
              <div className="flex flex-wrap items-center gap-1">
                <span>{t("episode.workbench.sketch.promptPreviewLabel")}</span>
                {kindLabels(brief, t).map((label) => (
                  <Badge key={label} variant="outline">
                    {label}
                  </Badge>
                ))}
              </div>
              <p className={cn("whitespace-pre-wrap break-words text-foreground/80")}>{brief.description}</p>
              {brief.prop_anchor_lines.map((line) => (
                <p key={line}>{line}</p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
