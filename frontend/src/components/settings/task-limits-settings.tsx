// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";

import type {
  TaskLaneLimit,
  TaskLaneName,
  TaskLimitsConfig,
  TaskLimitsEnvelope,
} from "@/api/taskLimits";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSaveTaskLimits, useTaskLimits } from "@/lib/queries/task-limits";

const LANES: readonly TaskLaneName[] = ["default", "video", "world", "ffmpeg"];
const FIELDS = [
  { key: "globalConcurrency", min: 1, max: 32 },
  { key: "globalQueueLimit", min: 1, max: 4096 },
  { key: "projectActiveLimit", min: 1, max: 256 },
  { key: "projectUserActiveLimit", min: 1, max: 256 },
] as const satisfies readonly {
  key: keyof TaskLaneLimit;
  min: number;
  max: number;
}[];

type Draft = Record<TaskLaneName, Record<keyof TaskLaneLimit, string>>;

function toDraft(config: TaskLimitsConfig): Draft {
  return Object.fromEntries(
    LANES.map((lane) => [
      lane,
      Object.fromEntries(
        FIELDS.map(({ key }) => [key, String(config.lanes[lane][key])]),
      ),
    ]),
  ) as Draft;
}

function draftIsValid(draft: Draft): boolean {
  return LANES.every((lane) =>
    FIELDS.every(({ key, min, max }) => {
      const value = Number(draft[lane][key]);
      return Number.isInteger(value) && value >= min && value <= max;
    }),
  );
}

function toConfig(draft: Draft): TaskLimitsConfig {
  return {
    lanes: Object.fromEntries(
      LANES.map((lane) => [
        lane,
        Object.fromEntries(
          FIELDS.map(({ key }) => [key, Number(draft[lane][key])]),
        ),
      ]),
    ) as unknown as TaskLimitsConfig["lanes"],
  };
}

function messageFromError(error: unknown, fallback: string): string {
  if (
    error &&
    typeof error === "object" &&
    "message" in error &&
    typeof error.message === "string" &&
    error.message.trim()
  ) {
    return error.message.trim();
  }
  return fallback;
}

function snapshotFrom(response: TaskLimitsEnvelope | undefined) {
  return response?.runtime ?? response?.snapshot ?? undefined;
}

export function TaskLimitsSettings({ open }: { open: boolean }) {
  const { t } = useTranslation();
  const query = useTaskLimits(open);
  const save = useSaveTaskLimits();
  const config = query.data?.data ?? query.data?.defaults;
  const [draft, setDraft] = useState<Draft | null>(null);
  const [savedConfig, setSavedConfig] = useState<TaskLimitsConfig | null>(null);
  const [snapshotOverride, setSnapshotOverride] = useState<
    ReturnType<typeof snapshotFrom> | null
  >(null);
  const [saveError, setSaveError] = useState("");
  const [saveSuccess, setSaveSuccess] = useState(false);

  useEffect(() => {
    if (config) {
      setSavedConfig(config);
      setDraft(toDraft(config));
    }
  }, [config]);

  const valid = draft ? draftIsValid(draft) : false;
  const snapshot = snapshotOverride ?? snapshotFrom(query.data);

  const updateField = (
    lane: TaskLaneName,
    field: keyof TaskLaneLimit,
    value: string,
  ) => {
    setDraft((current) => {
      const base = current ?? (config ? toDraft(config) : null);
      if (!base) return current;
      return {
        ...base,
        [lane]: { ...base[lane], [field]: value },
      };
    });
    setSaveError("");
  };

  const handleSave = async () => {
    if (!draft || !valid) return;
    setSaveError("");
    setSaveSuccess(false);
    try {
      const saved = await save.mutateAsync(toConfig(draft));
      const refreshed = await query.refetch();
      const effective =
        (refreshed.error ? undefined : refreshed.data?.data) ??
        saved.effective ??
        saved.data;
      if (!effective) throw new Error(t("settings.taskLimits.saveFailed"));
      setSavedConfig(effective);
      setDraft(toDraft(effective));
      setSnapshotOverride(
        (refreshed.error ? undefined : snapshotFrom(refreshed.data)) ??
          snapshotFrom(saved) ??
          null,
      );
      setSaveSuccess(true);
    } catch (error) {
      if (savedConfig) setDraft(toDraft(savedConfig));
      setSaveSuccess(false);
      setSaveError(
        messageFromError(error, t("settings.taskLimits.saveFailed")),
      );
    }
  };

  if (query.isLoading && !config) {
    return (
      <section
        className="flex h-full items-center justify-center"
        aria-live="polite"
      >
        <Loader2
          className="size-4 animate-spin text-muted-foreground"
          aria-label={t("settings.taskLimits.loading")}
        />
      </section>
    );
  }

  if (query.isError && !config) {
    return (
      <section className="px-5 py-5">
        <p role="alert" className="text-sm text-destructive">
          {messageFromError(
            query.error,
            t("settings.taskLimits.loadFailed"),
          )}
        </p>
      </section>
    );
  }

  if (!draft) return null;

  return (
    <section className="space-y-4 px-5 py-5">
      <div>
        <h3 className="font-heading text-sm font-medium text-foreground">
          {t("settings.taskLimits.title")}
        </h3>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          {t("settings.taskLimits.description")}
        </p>
      </div>

      {LANES.map((lane) => (
        <section
          key={lane}
          data-testid={`task-limits-lane-${lane}`}
          aria-labelledby={`task-limits-heading-${lane}`}
          className="rounded-md border border-border/70 p-3"
        >
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h4
              id={`task-limits-heading-${lane}`}
              className="text-xs font-medium text-foreground"
            >
              {t(`settings.taskLimits.lane.${lane}`)}
            </h4>
            <dl className="flex gap-3 text-[11px] text-muted-foreground">
              <div className="flex gap-1">
                <dt>{t("settings.taskLimits.headers.active")}</dt>
                <dd data-testid={`task-limits-active-${lane}`}>
                  {snapshot?.[lane]?.active ?? "—"}
                </dd>
              </div>
              <div className="flex gap-1">
                <dt>{t("settings.taskLimits.headers.queued")}</dt>
                <dd data-testid={`task-limits-queued-${lane}`}>
                  {snapshot?.[lane]?.queued ?? "—"}
                </dd>
              </div>
              <div className="flex gap-1">
                <dt>{t("settings.taskLimits.headers.concurrency")}</dt>
                <dd>{snapshot?.[lane]?.concurrency ?? "—"}</dd>
              </div>
            </dl>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {FIELDS.map(({ key, min, max }) => {
              const id = `task-limit-${lane}-${key}`;
              const value = draft[lane][key];
              const number = Number(value);
              const invalid =
                value.trim() === "" ||
                !Number.isInteger(number) ||
                number < min ||
                number > max;
              return (
                <div key={key} className="space-y-1.5">
                  <Label
                    htmlFor={id}
                    className="text-[11px] text-muted-foreground"
                  >
                    {t(`settings.taskLimits.fields.${key}`)}
                  </Label>
                  <Input
                    id={id}
                    type="number"
                    min={min}
                    max={max}
                    step={1}
                    value={value}
                    aria-invalid={invalid}
                    aria-describedby={
                      invalid ? "task-limits-validation" : undefined
                    }
                    onChange={(event) =>
                      updateField(lane, key, event.target.value)
                    }
                  />
                </div>
              );
            })}
          </div>
        </section>
      ))}

      {!valid ? (
        <p
          id="task-limits-validation"
          role="alert"
          className="text-xs text-destructive"
        >
          {t("settings.taskLimits.invalid")}
        </p>
      ) : null}
      {saveError ? (
        <p role="alert" className="text-xs text-destructive">
          {saveError}
        </p>
      ) : null}
      {saveSuccess ? (
        <p role="status" aria-live="polite" className="text-xs text-emerald-300">
          {t("settings.taskLimits.saved")}
        </p>
      ) : null}
      <div className="flex justify-end">
        <Button
          type="button"
          size="sm"
          onClick={() => void handleSave()}
          disabled={!valid || save.isPending || query.isLoading}
        >
          {save.isPending ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
          ) : null}
          {save.isPending
            ? t("settings.taskLimits.saving")
            : t("settings.taskLimits.save")}
        </Button>
      </div>
    </section>
  );
}
