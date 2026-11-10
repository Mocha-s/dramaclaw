// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  AlertTriangle,
  Cpu,
  Eye,
  EyeOff,
  ExternalLink,
  HardDrive,
  ListChecks,
  Loader2,
  Package,
  Plus,
  RotateCw,
  Trash2,
} from "lucide-react";

import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import {
  FEATURE_MODEL_GROUPS,
} from "@/lib/feature-models";
import {
  useModelGatewayConfig,
  useOfficialMediaCatalogStatus,
  useSaveOfficialMediaCatalogPreferences,
  useCheckOfficialMediaCatalog,
  useEnableOfficial,
  useEnableCustom,
  useEnableHybrid,
  useSetCustomLlmMode,
  useEnableBrainClaw,
  useSaveAgentLlmConfig,
  useSaveOfficialConfig,
  useSaveBrainClawConfig,
  useSaveThirdPartyGatewayConfig,
  useFetchThirdPartyModels,
  useSaveCapabilityDefaults,
  useInitCustomNewApi,
  useSaveMediaRelayConfig,
  type GatewayMode,
  type AgentLlmMode,
  type CustomLlmMode,
  type ModelGatewayConfig,
  type NewApiChannelType,
  type ThirdPartyCapability,
  type ThirdPartyGatewayGroup,
  type ThirdPartyModelMapping,
  type ThirdPartyVideoEndpoint,
} from "@/lib/queries/model-gateway";
import {
  useSettingsStore,
  type AliyunOssStorageConfig,
  type CloudinaryStorageConfig,
  type MinioStorageConfig,
  type FeatureModelEntry,
  type FeatureModelSettings,
  type FeatureModelProvider,
  type MediaStorageProvider,
} from "@/stores/settingsStore";
import { isCeRuntime } from "@/lib/runtime-config";
import { FreezoneSkillRecipeSettings } from "./freezone-skill-recipe-settings";
import { TaskLimitsSettings } from "./task-limits-settings";

interface SettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const MEDIA_STORAGE_PROVIDERS: MediaStorageProvider[] = [
  "aliyun_oss",
  "cloudinary",
  "minio",
];

// Codex 本地桥接暂时隐藏（保留组件代码，后端就绪后改回 true 即可恢复）。
const SHOW_CODEX_BRIDGE = false;
const MODEL_CONFIGURATION_GUIDE_URL =
  "https://github.com/dramaclaw/dramaclaw/blob/main/docs/en/getting-started/configuring-models.md";

export function SettingsDialog({ open, onOpenChange }: SettingsDialogProps) {
  const { t } = useTranslation();
  const ceRuntime = isCeRuntime();
  const [page, setPage] = useState<
    "models" | "storage" | "task-limits" | "freezone-skills" | "freezone-recipes"
  >(
    () => (ceRuntime ? "models" : "freezone-skills"),
  );
  const statusQuery = useModelGatewayConfig(open && ceRuntime);
  const settingsStatus = statusQuery.data?.data;
  const modelConfigured = Boolean(settingsStatus?.effective.configured);
  const mediaStorageConfigured = Boolean(
    settingsStatus?.mediaRelay?.configured,
  );

  useEffect(() => {
    if (
      !ceRuntime &&
      (page === "models" || page === "storage" || page === "task-limits")
    ) {
      setPage("freezone-skills");
    }
  }, [ceRuntime, page]);

  const pageStatus = (configured: boolean, label: string) => {
    if (statusQuery.isLoading) {
      return (
        <Loader2
          className="absolute top-1 right-1 size-3 animate-spin text-muted-foreground sm:static sm:ml-auto sm:size-3.5"
          aria-hidden
        />
      );
    }
    if (configured) {
      return (
        <span
          className="absolute top-1 right-1 size-2 shrink-0 rounded-full bg-emerald-400 sm:static sm:ml-auto"
          aria-label={t("settings.statusConfigured", { page: label })}
          title={t("settings.statusConfigured", { page: label })}
        />
      );
    }
    return (
      <AlertTriangle
        className="absolute top-1 right-1 size-3.5 shrink-0 text-amber-400 sm:static sm:ml-auto sm:size-4"
        aria-label={t("settings.statusNotConfigured", { page: label })}
      />
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton
        className="flex h-[min(82vh,760px)] max-w-[calc(100%-2rem)] flex-col gap-0 overflow-hidden rounded-lg border border-border bg-black p-0 ring-0 sm:max-w-[1120px]"
      >
        <DialogHeader className="border-b border-border px-5 py-4">
          <DialogTitle>{t("settings.title")}</DialogTitle>
        </DialogHeader>

        <div className="flex min-h-0 flex-1">
          <nav
            aria-label={t("settings.navigationLabel")}
            className="flex w-14 shrink-0 flex-col gap-1 border-r border-border px-2 py-4 sm:w-44 sm:px-3"
          >
            {ceRuntime ? (
              <>
                <button
                  type="button"
                  aria-current={page === "models" ? "page" : undefined}
                  onClick={() => setPage("models")}
                  className={cn(
                    "relative flex h-10 items-center justify-center gap-2 rounded-md px-2 text-sm font-medium transition-colors sm:justify-start sm:px-3",
                    page === "models"
                      ? "bg-white/[0.09] text-foreground"
                      : "text-muted-foreground hover:bg-white/[0.05] hover:text-foreground",
                  )}
                >
                  <Cpu className="size-4" aria-hidden />
                  <span className="hidden sm:inline">{t("settings.pages.models")}</span>
                  {pageStatus(modelConfigured, t("settings.pages.models"))}
                </button>
                <button
                  type="button"
                  aria-current={page === "task-limits" ? "page" : undefined}
                  onClick={() => setPage("task-limits")}
                  className={cn(
                    "relative flex h-10 items-center justify-center gap-2 rounded-md px-2 text-sm font-medium transition-colors sm:justify-start sm:px-3",
                    page === "task-limits"
                      ? "bg-white/[0.09] text-foreground"
                      : "text-muted-foreground hover:bg-white/[0.05] hover:text-foreground",
                  )}
                >
                  <ListChecks className="size-4" aria-hidden />
                  <span className="hidden sm:inline">
                    {t("settings.pages.taskLimits")}
                  </span>
                </button>
                <button
                  type="button"
                  aria-current={page === "storage" ? "page" : undefined}
                  onClick={() => setPage("storage")}
                  className={cn(
                    "relative flex h-10 items-center justify-center gap-2 rounded-md px-2 text-sm font-medium transition-colors sm:justify-start sm:px-3",
                    page === "storage"
                      ? "bg-white/[0.09] text-foreground"
                      : "text-muted-foreground hover:bg-white/[0.05] hover:text-foreground",
                  )}
                >
                  <HardDrive className="size-4" aria-hidden />
                  <span className="hidden sm:inline">{t("settings.pages.storage")}</span>
                  {pageStatus(mediaStorageConfigured, t("settings.pages.storage"))}
                </button>
              </>
            ) : null}
            <button
              type="button"
              aria-current={page === "freezone-skills" || page === "freezone-recipes" ? "page" : undefined}
              onClick={() => setPage("freezone-skills")}
              className={cn(
                "relative flex h-10 items-center justify-center gap-2 rounded-md px-2 text-sm font-medium transition-colors sm:justify-start sm:px-3",
                page === "freezone-skills" || page === "freezone-recipes"
                  ? "bg-white/[0.09] text-foreground"
                  : "text-muted-foreground hover:bg-white/[0.05] hover:text-foreground",
              )}
            >
              <Package className="size-4" aria-hidden />
              <span className="hidden sm:inline">{t("settings.pages.freezoneSkills")}</span>
            </button>
          </nav>

          {page === "models" ? (
            <div className="min-w-0 flex-1">
              <ScrollArea className="h-full [&_[data-slot=scroll-area-scrollbar]]:!w-1 [&_[data-slot=scroll-area-scrollbar]]:!border-l-0 [&_[data-slot=scroll-area-scrollbar]]:!p-0">
                <ModelConfigSection open={open && page === "models"} />
                {SHOW_CODEX_BRIDGE && <CodexBridgeSection />}
              </ScrollArea>
            </div>
          ) : page === "storage" ? (
            <div className="min-w-0 flex-1">
              <ScrollArea className="h-full [&_[data-slot=scroll-area-scrollbar]]:!w-1 [&_[data-slot=scroll-area-scrollbar]]:!border-l-0 [&_[data-slot=scroll-area-scrollbar]]:!p-0">
                <MediaStorageSection />
              </ScrollArea>
            </div>
          ) : page === "task-limits" ? (
            <div className="min-w-0 flex-1">
              <ScrollArea className="h-full [&_[data-slot=scroll-area-scrollbar]]:!w-1 [&_[data-slot=scroll-area-scrollbar]]:!border-l-0 [&_[data-slot=scroll-area-scrollbar]]:!p-0">
                <TaskLimitsSettings open={open && page === "task-limits"} />
              </ScrollArea>
            </div>
          ) : (
            <div className="min-w-0 flex-1">
              <ScrollArea className="h-full [&_[data-slot=scroll-area-scrollbar]]:!w-1 [&_[data-slot=scroll-area-scrollbar]]:!border-l-0 [&_[data-slot=scroll-area-scrollbar]]:!p-0">
                <FreezoneSkillRecipeSettings
                  kind={page === "freezone-skills" ? "skills" : "recipes"}
                  onBackToSkills={() => setPage("freezone-skills")}
                  onOpenRecipes={() => setPage("freezone-recipes")}
                  open={open && (page === "freezone-skills" || page === "freezone-recipes")}
                />
              </ScrollArea>
            </div>
          )}
        </div>

        <div className="flex justify-end border-t border-border px-5 py-3.5">
          <DialogClose render={<Button variant="outline" size="sm" />}>
            {t("settings.close")}
          </DialogClose>
        </div>
      </DialogContent>
    </Dialog>
  );
}

const GATEWAY_MODES: GatewayMode[] = ["official", "custom", "hybrid"];


async function getRequestErrorMessage(
  error: unknown,
  fallback: string,
): Promise<string> {
  const response = (error as { response?: Response } | null)?.response;
  if (response) {
    const body = await response
      .clone()
      .json()
      .catch(() => null);
    if (body && typeof body === "object") {
      const data = body as {
        detail?: unknown;
        error?: unknown;
        message?: unknown;
      };
      for (const value of [data.detail, data.error, data.message]) {
        if (typeof value === "string" && value.trim()) return value.trim();
      }
    }
    const text = await response
      .clone()
      .text()
      .catch(() => "");
    if (text.trim()) return text.trim();
  }
  const message = (error as { message?: unknown } | null)?.message;
  return typeof message === "string" && message.trim()
    ? message.trim()
    : fallback;
}

function getResponseErrorMessage(response: unknown, fallback: string): string {
  if (response && typeof response === "object") {
    const data = response as {
      detail?: unknown;
      error?: unknown;
      message?: unknown;
    };
    for (const value of [data.detail, data.error, data.message]) {
      if (typeof value === "string" && value.trim()) return value.trim();
    }
    const payload = (data as { data?: unknown }).data;
    if (payload && typeof payload === "object") {
      const result = (payload as { result?: unknown }).result;
      if (result && typeof result === "object") {
        const error = (result as { error?: unknown }).error;
        if (typeof error === "string" && error.trim()) return error.trim();
      }
      const results = (payload as { results?: unknown }).results;
      if (Array.isArray(results)) {
        const failed = results.find(
          (item) =>
            item &&
            typeof item === "object" &&
            typeof (item as { error?: unknown }).error === "string" &&
            Boolean(((item as { error?: string }).error ?? "").trim()),
        ) as { error?: unknown } | undefined;
        if (typeof failed?.error === "string" && failed.error.trim()) {
          return failed.error.trim();
        }
      }
    }
    if (Array.isArray(data.detail)) {
      const first = data.detail.find(
        (item) => item && typeof item === "object",
      ) as { msg?: unknown } | undefined;
      if (typeof first?.msg === "string" && first.msg.trim())
        return first.msg.trim();
    }
  }
  return fallback;
}

function ModelConfigSection({ open }: { open: boolean }) {
  const { t } = useTranslation();
  const configQuery = useModelGatewayConfig(open);
  const config = configQuery.data?.data;
  const loading = configQuery.isLoading;
  const enableOfficialMode = useEnableOfficial();
  const enableCustomMode = useEnableCustom();
  const enableHybridMode = useEnableHybrid();
  const modelGatewayMissing = config
    ? !config.effective.configured || !config.llmEffective.configured
    : false;

  const [mode, setMode] = useState<GatewayMode>("official");
  const modeChosenByUser = useRef(false);
  // 配置加载后，把激活的 tab 同步到服务端当前 mode。
  const serverMode = config?.mode;
  useEffect(() => {
    if (serverMode && !modeChosenByUser.current) {
      const normalizedMode = serverMode === "sub2api" ? "custom" : serverMode;
      setMode((current) => (current === normalizedMode ? current : normalizedMode));
    }
  }, [serverMode]);
  const selectedModeConfigured =
    mode === "official"
      ? Boolean(config?.official?.configured)
      : mode === "custom"
        ? Boolean(config?.custom?.configured)
        : mode === "hybrid"
          ? Boolean(config?.official?.configured && config?.thirdParty?.configured)
          : Boolean(config?.thirdParty?.configured || config?.sub2api?.configured);
  const activatingMode =
    enableOfficialMode.isPending ||
    enableCustomMode.isPending ||
    enableHybridMode.isPending ||
    false;

  const handleActivateMode = async () => {
    const mutation =
      mode === "official"
        ? enableOfficialMode
        : mode === "custom"
          ? enableCustomMode
            : enableHybridMode;
    try {
      const response = await mutation.mutateAsync();
      if (!response.ok) {
        toast.error(
          getResponseErrorMessage(
            response,
            t("settings.modelConfig.requestFailed"),
          ),
        );
        return;
      }
      toast.success(
        t("settings.modelConfig.modeActivated", {
          mode: t(`settings.modelConfig.modes.${mode}`),
        }),
      );
    } catch (error) {
      toast.error(
        await getRequestErrorMessage(
          error,
          t("settings.modelConfig.requestFailed"),
        ),
      );
    }
  };

  return (
    <section className="px-5 py-5">
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "size-1.5 rounded-full",
            modelGatewayMissing ? "bg-amber-400" : "bg-emerald-400",
          )}
        />
        <h3 className="font-heading text-sm font-medium text-foreground">
          {t("settings.modelConfig.title")}
        </h3>
        {modelGatewayMissing ? (
          <AlertTriangle
            className="size-3.5 text-amber-400"
            aria-label={t("settings.modelConfig.gatewayWarningIconLabel")}
          />
        ) : null}
        {config ? (
          <span className="ml-1 rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            {t("settings.modelConfig.effectiveBadge", {
              channel: t(
                `settings.modelConfig.modes.${config.effective.source}`,
                {
                  defaultValue: config.effective.source,
                },
              ),
            })}
          </span>
        ) : null}
        <a
          href={MODEL_CONFIGURATION_GUIDE_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-auto inline-flex items-center gap-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
        >
          {t("settings.modelConfig.guide")}
          <ExternalLink className="size-3" aria-hidden />
        </a>
      </div>

      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
        {t("settings.modelConfig.description")}
      </p>
      {modelGatewayMissing ? (
        <div className="mt-3 flex gap-2 rounded-md border border-amber-500/35 bg-amber-500/10 px-3 py-2 text-[11px] leading-relaxed text-amber-100">
          <AlertTriangle
            className="mt-0.5 size-3.5 shrink-0 text-amber-300"
            aria-hidden
          />
          <p>{t("settings.modelConfig.gatewayNotConfiguredImpact")}</p>
        </div>
      ) : null}

      <AgentLlmPanel config={config} loading={loading} />

      <Tabs
        className="mt-4"
        value={mode}
        onValueChange={(value) => {
          const nextMode = value as GatewayMode;
          modeChosenByUser.current = true;
          setMode(nextMode);
        }}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <TabsList>
            {GATEWAY_MODES.map((m) => (
              <TabsTrigger key={m} value={m}>
                {t(`settings.modelConfig.modes.${m}`)}
              </TabsTrigger>
            ))}
          </TabsList>
          {mode !== serverMode ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={handleActivateMode}
              disabled={!selectedModeConfigured || activatingMode}
              title={
                selectedModeConfigured
                  ? t("settings.modelConfig.activateMode")
                  : t("settings.modelConfig.configureBeforeActivate")
              }
            >
              {activatingMode ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : null}
              {t("settings.modelConfig.activateMode")}
            </Button>
          ) : null}
        </div>
      </Tabs>

      <div className="mt-4">
        {mode === "official" || mode === "hybrid" ? (
          <OfficialGatewayPanel
            config={config}
            loading={loading}
            activateHybrid={mode === "hybrid"}
          />
        ) : null}
      </div>
      {mode === "custom" || mode === "hybrid" ? (
        <ThirdPartyGatewayPanel config={config} loading={loading} />
      ) : null}
      {mode === "custom" ? (
        <CustomLlmSettings config={config} loading={loading} />
      ) : null}
    </section>
  );
}

const THIRD_PARTY_CAPABILITIES: readonly ThirdPartyCapability[] = ["text", "embedding", "image", "video", "audio"];

type ThirdPartyGroupDraft = ThirdPartyGatewayGroup & {
  apiKey: string;
};

function newThirdPartyGroup(): ThirdPartyGroupDraft {
  return {
    id: globalThis.crypto?.randomUUID?.() ?? `third-party-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    name: "",
    protocol: "openai",
    baseUrl: "",
    apiKey: "",
    apiKeyPreview: "",
    capabilities: ["text"],
    modelMappings: [],
  };
}

function ThirdPartyGatewayPanel({
  config,
  loading,
}: {
  config: ModelGatewayConfig | undefined;
  loading: boolean;
}) {
  const { t } = useTranslation();
  const saveConfig = useSaveThirdPartyGatewayConfig();
  const fetchModels = useFetchThirdPartyModels();
  const saved = config?.thirdParty ?? (config?.sub2api ? { ...config.sub2api } : undefined);
  const autoFetchLastAt = config?.thirdParty?.autoFetchLastAt ?? "";
  const [groups, setGroups] = useState<ThirdPartyGroupDraft[]>([]);
  const [openGroupIds, setOpenGroupIds] = useState<string[]>([]);
  const [modelsByGroup, setModelsByGroup] = useState<Record<string, string[]>>({});

  useEffect(() => {
    setGroups(
      (saved?.groups ?? []).map((group) => ({ ...group, apiKey: "" })),
    );
    setModelsByGroup({});
    setOpenGroupIds([]);
  }, [saved?.groups]);

  const canSave = groups.length === 0 || groups.every((group) => {
    const previous = saved?.groups.find((candidate) => candidate.id === group.id);
    const endpointChanged = previous && previous.baseUrl !== group.baseUrl.trim().replace(/\/+$/, "");
    return Boolean(
      group.name.trim() &&
      group.baseUrl.trim() &&
      group.capabilities.length > 0 &&
      group.modelMappings.length > 0 && group.modelMappings.every((mapping) => mapping.requestPattern.trim() && mapping.upstreamModel.trim()) &&
      (group.apiKey.trim() || (previous?.apiKeyPreview && !endpointChanged)),
    );
  });

  const handleSave = async () => {
    try {
      const response = await saveConfig.mutateAsync({
        groups: groups.map((group) => ({
          id: group.id,
          name: group.name.trim(),
          protocol: group.protocol,
          baseUrl: group.baseUrl.trim().replace(/\/+$/, ""),
          capabilities: group.capabilities,
          modelMappings: group.modelMappings.map((mapping) => ({
            requestPattern: mapping.requestPattern.trim(),
            upstreamModel: mapping.upstreamModel.trim(),
            ...(mapping.auto ? { auto: true } : {}),
            ...(group.capabilities.includes("video")
              ? { videoEndpoint: mapping.videoEndpoint ?? "videos" }
              : {}),
            ...(group.capabilities.includes("video") && mapping.supportedModes?.length
              ? { supportedModes: mapping.supportedModes }
              : {}),
            ...(group.capabilities.includes("video") && mapping.resolutionOptions?.length
              ? { resolutionOptions: mapping.resolutionOptions }
              : {}),
          })),
          ...(group.apiKey.trim() ? { apiKey: group.apiKey.trim() } : {}),
          ...(group.autoFetch ? { autoFetch: true } : {}),
        })),
      });
      if (!response.ok) {
        toast.error(
          getResponseErrorMessage(response, t("settings.modelConfig.requestFailed")),
        );
        return;
      }
      toast.success(t("settings.modelConfig.thirdParty.saved"));
    } catch (error) {
      toast.error(
        await getRequestErrorMessage(error, t("settings.modelConfig.requestFailed")),
      );
    }
  };

  return (
    <div className="mt-4 space-y-3">
      <h4 className="text-xs font-medium text-foreground">{t("settings.modelConfig.thirdParty.title")}</h4>
      <p className="text-xs leading-relaxed text-muted-foreground">
        {t("settings.modelConfig.thirdParty.description")}
      </p>
      {(config?.migrationWarnings ?? config?.thirdParty?.migrationWarnings ?? []).map((warning, index) => (
        <p key={index} role="status" className="rounded-md border border-amber-500/35 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">{warning}</p>
      ))}
      {autoFetchLastAt ? (
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          {t("settings.modelConfig.thirdParty.autoFetchLastAt", {
            time: new Date(autoFetchLastAt).toLocaleString(),
          })}
        </p>
      ) : null}
      <div className="space-y-3">
        {groups.map((group) => (
          <ThirdPartyGroupCard
            key={group.id}
            group={group}
            onChange={(next) => setGroups((current) => current.map((item) => item.id === next.id ? next : item))}
            onRemove={() => setGroups((current) => current.filter((item) => item.id !== group.id))}
            expanded={openGroupIds.includes(group.id)}
            onExpandedChange={(expanded) => setOpenGroupIds((current) => expanded ? [...current, group.id] : current.filter((id) => id !== group.id))}
            availableModels={modelsByGroup[group.id] ?? []}
            fetchPending={fetchModels.isPending}
            onFetchModels={async () => {
              try {
                const response = await fetchModels.mutateAsync({
                  id: group.id,
                  protocol: group.protocol,
                  baseUrl: group.baseUrl,
                  ...(group.apiKey ? { apiKey: group.apiKey } : {}),
                });
                if (!response.ok) {
                  toast.error(getResponseErrorMessage(response, t("settings.modelConfig.thirdParty.fetchFailed")));
                  return;
                }
                setModelsByGroup((current) => ({ ...current, [group.id]: response.data.models }));
                // A fresh list is the source of truth: drop mappings whose upstream model is gone.
                setGroups((current) => current.map((item) => item.id === group.id ? {
                  ...item,
                  modelMappings: item.modelMappings.filter((mapping) => mapping.requestPattern.trim() === "*" || response.data.models.includes(mapping.upstreamModel.trim())),
                } : item));
              } catch (error) {
                toast.error(await getRequestErrorMessage(error, t("settings.modelConfig.thirdParty.fetchFailed")));
              }
            }}
          />
        ))}
        <Button type="button" variant="outline" size="sm" onClick={() => { const group = newThirdPartyGroup(); setGroups((current) => [...current, group]); setOpenGroupIds((current) => [...current, group.id]); }}>
          <Plus className="size-3.5" />
          {t("settings.modelConfig.thirdParty.addGroup")}
        </Button>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          {t("settings.modelConfig.thirdParty.keyHint")}
        </p>
        <div className="flex justify-end">
          <Button
            type="button"
            size="sm"
            onClick={handleSave}
            disabled={loading || saveConfig.isPending || !canSave}
            title={
              canSave
                ? t("settings.modelConfig.thirdParty.save")
                : t("settings.modelConfig.thirdParty.missingFields")
            }
          >
            {saveConfig.isPending ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : null}
            {t("settings.modelConfig.thirdParty.save")}
          </Button>
        </div>
      </div>
    </div>
  );
}

function ThirdPartyGroupCard({
  group,
  onChange,
  onRemove,
  expanded,
  onExpandedChange,
  availableModels,
  fetchPending,
  onFetchModels,
}: {
  group: ThirdPartyGroupDraft;
  onChange: (group: ThirdPartyGroupDraft) => void;
  onRemove: () => void;
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
  availableModels: string[];
  fetchPending: boolean;
  onFetchModels: () => void;
}) {
  const { t } = useTranslation();
  const modelsId = useId();
  const [modelSearch, setModelSearch] = useState("");
  const filteredModels = availableModels.filter((model) =>
    model.toLowerCase().includes(modelSearch.trim().toLowerCase()),
  );
  const textRouteOptions = Array.from(
    new Set([
      ...group.modelMappings.map((mapping) => mapping.upstreamModel.trim()),
      ...availableModels,
    ]),
  ).filter(Boolean);
  const wildcardMapping = group.modelMappings.find(
    (mapping) => mapping.requestPattern.trim() === "*",
  );
  const noUnifiedRoute = "__no_unified_text_route__";
  return (
    <section role="group" className="rounded-md border border-border/70 p-3">
      <button type="button" aria-expanded={expanded} onClick={() => onExpandedChange(!expanded)} className="w-full cursor-pointer text-left text-xs font-medium text-foreground">
        {group.name || t("settings.modelConfig.thirdParty.newGroup")}
      </button>
      {expanded ? <div className="mt-3 space-y-3">
      <div className="flex items-center justify-between gap-3 rounded-md border border-border/70 px-2.5 py-2">
        <div className="min-w-0">
          <Label className="text-[11px] font-normal text-foreground">
            {t("settings.modelConfig.thirdParty.autoFetch")}
          </Label>
          <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
            {t("settings.modelConfig.thirdParty.autoFetchHint")}
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={group.autoFetch === true}
          aria-label={t("settings.modelConfig.thirdParty.autoFetch")}
          onClick={() => onChange({ ...group, autoFetch: !group.autoFetch })}
          className={cn(
            "relative h-5 w-9 shrink-0 rounded-full border transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none",
            group.autoFetch ? "border-primary bg-primary" : "border-input bg-muted",
          )}
        >
          <span
            className={cn(
              "absolute top-0.5 left-0.5 size-4 rounded-full bg-white shadow-sm transition-transform",
              group.autoFetch ? "translate-x-4" : "translate-x-0",
            )}
          />
        </button>
      </div>
      <div className="flex justify-end">
          <Button type="button" size="sm" variant="ghost" onClick={onRemove} aria-label={t("settings.modelConfig.thirdParty.removeGroup")}>
          <Trash2 className="size-3.5" />
          {t("settings.modelConfig.thirdParty.removeGroup")}
        </Button>
      </div>
      <FieldRow
        label={t("settings.modelConfig.thirdParty.groupName")}
        name={`third-party-${group.id}-name`}
        value={group.name}
        onChange={(name) => onChange({ ...group, name })}
        placeholder="openai-main"
      />
      <div className="grid grid-cols-[120px_1fr] items-center gap-3">
        <Label htmlFor={`${modelsId}-protocol`} className="text-[11px] text-muted-foreground uppercase">{t("settings.modelConfig.thirdParty.protocol")}</Label>
        <Select
          value={group.protocol}
          onValueChange={(protocol) => onChange({
            ...group,
            protocol: protocol as ThirdPartyGroupDraft["protocol"],
            ...(protocol === "anthropic" && !group.baseUrl.trim()
              ? { baseUrl: "https://api.anthropic.com" }
              : {}),
          })}
        >
          <SelectTrigger id={`${modelsId}-protocol`} size="sm" className="h-9 w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent alignItemWithTrigger={false}>
            <SelectItem value="openai">OpenAI</SelectItem>
            <SelectItem value="gemini">Gemini</SelectItem>
            <SelectItem value="anthropic">Claude / Anthropic</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <FieldRow
        label={t("settings.modelConfig.thirdParty.baseUrl")}
        name={`third-party-${group.id}-base-url`}
        value={group.baseUrl}
        onChange={(baseUrl) => onChange({ ...group, baseUrl })}
        placeholder="https://api.example.com/v1"
      />
      <FieldRow
        secret
        label={t("settings.modelConfig.thirdParty.apiKey")}
        name={`third-party-${group.id}-key`}
        value={group.apiKey}
        onChange={(apiKey) => onChange({ ...group, apiKey })}
        savedPreview={group.apiKeyPreview}
        placeholder={t("settings.modelConfig.thirdParty.keyPlaceholder")}
      />
      <div className="space-y-1.5">
        <p className="text-[11px] font-medium text-muted-foreground">{t("settings.modelConfig.thirdParty.capabilitiesLabel")}</p>
        <div className="flex flex-wrap gap-x-4 gap-y-2">
          {THIRD_PARTY_CAPABILITIES.map((capability) => (
            <label key={capability} className="inline-flex items-center gap-1.5 text-xs text-foreground">
              <input
                type="checkbox"
                checked={group.capabilities.includes(capability)}
                onChange={(event) => onChange({
                  ...group,
                  capabilities: event.target.checked
                    ? [...group.capabilities, capability]
                    : group.capabilities.filter((item) => item !== capability),
                })}
              />
              {t(`settings.modelConfig.thirdParty.capabilities.${capability}`)}
            </label>
          ))}
        </div>
      </div>
      {group.capabilities.includes("text") ? (
        <div className="space-y-1.5 rounded-md border border-primary/20 bg-primary/[0.03] px-2.5 py-2">
          <Label className="text-[11px] text-muted-foreground">
            {t("settings.modelConfig.thirdParty.unifiedRoute", {
              defaultValue: "统一文本路由",
            })}
          </Label>
          <Select
            value={wildcardMapping?.upstreamModel.trim() || noUnifiedRoute}
            onValueChange={(value) => {
              const exactMappings = group.modelMappings.filter(
                (mapping) => mapping.requestPattern.trim() !== "*",
              );
              if (value === noUnifiedRoute) {
                onChange({ ...group, modelMappings: exactMappings });
                return;
              }
              const nextWildcardMapping: ThirdPartyModelMapping = {
                requestPattern: "*",
                upstreamModel: String(value),
                ...(wildcardMapping?.videoEndpoint
                  ? { videoEndpoint: wildcardMapping.videoEndpoint }
                  : {}),
              };
              onChange({
                ...group,
                modelMappings: [
                  ...exactMappings,
                  nextWildcardMapping,
                ],
              });
            }}
          >
            <SelectTrigger
              aria-label={t("settings.modelConfig.thirdParty.unifiedRoute", {
                defaultValue: "统一文本路由",
              })}
              size="sm"
              className="h-8 w-full"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent alignItemWithTrigger={false}>
              <SelectItem value={noUnifiedRoute}>
                {t("settings.modelConfig.thirdParty.unifiedRouteNone", {
                  defaultValue: "不使用统一路由",
                })}
              </SelectItem>
              {textRouteOptions.map((model) => (
                <SelectItem key={model} value={model}>
                  {model}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-[10px] leading-relaxed text-muted-foreground">
            {t("settings.modelConfig.thirdParty.unifiedRouteHint", {
              defaultValue: "保存为 * → 上游模型；精确规则优先。",
            })}
          </p>
        </div>
      ) : null}
      <div className="space-y-1.5">
        <Label htmlFor={modelsId} className="text-[11px] text-muted-foreground">{t("settings.modelConfig.thirdParty.models")}</Label>
        <div className="flex gap-2">
          <Input
            value={modelSearch}
            onChange={(event) => setModelSearch(event.target.value)}
            placeholder={t("settings.modelConfig.thirdParty.modelSearch")}
            aria-label={t("settings.modelConfig.thirdParty.modelSearch")}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onFetchModels}
             disabled={fetchPending || !group.baseUrl.trim() || (!group.apiKey.trim() && !group.apiKeyPreview)}
          >
            {fetchPending ? <Loader2 className="size-3.5 animate-spin" /> : null}
            {t("settings.modelConfig.thirdParty.fetchModels")}
          </Button>
        </div>
        {availableModels.length > 0 ? (
          <div
            className="max-h-36 space-y-1 overflow-auto rounded-md border border-border/70 p-2"
            aria-label={t("settings.modelConfig.thirdParty.availableModels")}
          >
            {filteredModels.length === 0 ? (
              <p className="text-xs text-muted-foreground">{t("settings.modelConfig.thirdParty.noModels")}</p>
            ) : filteredModels.map((model) => (
              <label key={model} className="flex items-center gap-2 text-xs text-foreground">
                <input
                  type="checkbox"
                  checked={group.modelMappings.some((mapping) => mapping.upstreamModel === model)}
                  onChange={(event) => onChange({
                    ...group,
                    modelMappings: event.target.checked
                      ? [
                          ...group.modelMappings,
                          {
                             requestPattern: model,
                            upstreamModel: model,
                            videoEndpoint: "videos",
                          },
                        ]
                      : group.modelMappings.filter((mapping) => mapping.upstreamModel !== model),
                  })}
                />
                <span className="font-mono">{model}</span>
              </label>
            ))}
          </div>
        ) : null}
        <div className="space-y-2" id={modelsId}>
          {group.modelMappings.map((mapping, index) => (
            <div key={`${mapping.upstreamModel}-${index}`} className="space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <Input
                  aria-label={t("settings.modelConfig.thirdParty.requestModel")}
                  value={mapping.requestPattern}
                  onChange={(event) => onChange({
                    ...group,
                    modelMappings: group.modelMappings.map((item, itemIndex) => itemIndex === index ? { ...item, requestPattern: event.target.value } : item),
                  })}
                  placeholder="DC-codex-agent-LLM"
                />
                <Input
                  aria-label={t("settings.modelConfig.thirdParty.upstreamModel")}
                  value={mapping.upstreamModel}
                  onChange={(event) => onChange({
                    ...group,
                    modelMappings: group.modelMappings.map((item, itemIndex) => itemIndex === index ? { ...item, upstreamModel: event.target.value } : item),
                  })}
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                {group.capabilities.includes("image") ? <span /> : null}
                {group.capabilities.includes("video") ? (
                    <label className="grid grid-cols-[120px_1fr] items-center gap-2 text-[11px] text-muted-foreground">
                      <span>{t("settings.modelConfig.thirdParty.videoEndpoint")}</span>
                     <Select
                       value={mapping.videoEndpoint ?? "videos"}
                       onValueChange={(videoEndpoint) => onChange({
                         ...group,
                         modelMappings: group.modelMappings.map((item, itemIndex) => itemIndex === index
                           ? { ...item, videoEndpoint: videoEndpoint as ThirdPartyVideoEndpoint }
                           : item),
                       })}
                     >
                       <SelectTrigger size="sm" className="h-9 w-full" aria-label={t("settings.modelConfig.thirdParty.videoEndpoint")}>
                         <SelectValue />
                       </SelectTrigger>
                       <SelectContent alignItemWithTrigger={false}>
                         <SelectItem value="videos">{t("settings.modelConfig.thirdParty.videoEndpoints.videos")}</SelectItem>
                         <SelectItem value="video/generations">{t("settings.modelConfig.thirdParty.videoEndpoints.legacy")}</SelectItem>
                       </SelectContent>
                     </Select>
                  </label>
                ) : null}
              </div>
              {group.capabilities.includes("video") ? (
                <div className="space-y-2">
                  <div className="grid grid-cols-[120px_1fr] items-start gap-2 text-[11px] text-muted-foreground">
                    <span>{t("settings.modelConfig.thirdParty.supportedModes")}</span>
                    <div className="flex flex-wrap gap-1">
                      {THIRD_PARTY_VIDEO_MODE_TOGGLES.map((modeOption) => {
                        const active = (mapping.supportedModes ?? []).includes(modeOption.value);
                        return (
                          <button
                            key={modeOption.value}
                            type="button"
                            aria-pressed={active}
                            className={
                              active
                                ? "rounded-full border border-primary bg-primary/10 px-2 py-0.5 text-[11px] text-primary"
                                : "rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted"
                            }
                            onClick={() => onChange({
                              ...group,
                              modelMappings: group.modelMappings.map((item, itemIndex) => itemIndex === index
                                ? {
                                    ...item,
                                    supportedModes: active
                                      ? (item.supportedModes ?? []).filter((value) => value !== modeOption.value)
                                      : [...(item.supportedModes ?? []), modeOption.value],
                                  }
                                : item),
                            })}
                          >
                            {t(modeOption.labelKey)}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <div className="grid grid-cols-[120px_1fr] items-center gap-2 text-[11px] text-muted-foreground">
                    <span>{t("settings.modelConfig.thirdParty.upscaleResolutions")}</span>
                    <Input
                      aria-label={t("settings.modelConfig.thirdParty.upscaleResolutions")}
                      value={(mapping.resolutionOptions ?? []).join(", ")}
                      placeholder="1080p, 2k, 4k"
                      onChange={(event) => onChange({
                        ...group,
                        modelMappings: group.modelMappings.map((item, itemIndex) => itemIndex === index
                          ? {
                              ...item,
                              resolutionOptions: event.target.value
                                .split(",")
                                .map((value) => value.trim())
                                .filter(Boolean),
                            }
                          : item),
                      })}
                    />
                  </div>
                </div>
              ) : null}
            </div>
          ))}
        </div>
        <p id={`${modelsId}-hint`} className="text-[11px] text-muted-foreground">{t("settings.modelConfig.thirdParty.modelsHint")}</p>
      </div>
      </div> : null}
    </section>
  );
}

const THIRD_PARTY_VIDEO_MODE_TOGGLES: ReadonlyArray<{ value: string; labelKey: string }> = [
  { value: "text_to_video", labelKey: "settings.modelConfig.thirdParty.modes.textToVideo" },
  { value: "image_to_video", labelKey: "settings.modelConfig.thirdParty.modes.imageToVideo" },
  { value: "image_reference", labelKey: "settings.modelConfig.thirdParty.modes.imageReference" },
  { value: "first_frame", labelKey: "settings.modelConfig.thirdParty.modes.firstFrame" },
  { value: "all_reference", labelKey: "settings.modelConfig.thirdParty.modes.allReference" },
  { value: "video_upscale", labelKey: "settings.modelConfig.thirdParty.modes.videoUpscale" },
  { value: "video_frame_rate", labelKey: "settings.modelConfig.thirdParty.modes.videoFrameRate" },
  { value: "video_edit", labelKey: "settings.modelConfig.thirdParty.modes.videoEdit" },
  { value: "video_extend", labelKey: "settings.modelConfig.thirdParty.modes.videoExtend" },
];

function CustomLlmSettings({
  config,
  loading,
}: {
  config: ModelGatewayConfig | undefined;
  loading: boolean;
}) {
  const { t } = useTranslation();
  const [llmMode, setLlmMode] = useState<CustomLlmMode>(config?.custom?.llmMode ?? "relayclaw_brainclaw");
  const updateMode = useSetCustomLlmMode();
  useEffect(() => {
    if (config?.custom?.llmMode) setLlmMode(config.custom.llmMode);
  }, [config?.custom?.llmMode]);
  const automaticThirdPartyTextRoute = Boolean(
    config?.thirdParty?.groups.some((group) => group.capabilities.includes("text")),
  );
  const onModeChange = async (value: string) => {
    const next = value as CustomLlmMode;
    setLlmMode(next);
    if (next === "advanced") await updateMode.mutateAsync(next);
  };
  return (
    <div className="mt-5 space-y-3">
      <Tabs value={llmMode} onValueChange={onModeChange}>
        <TabsList>
          <TabsTrigger value="relayclaw_brainclaw">{t("settings.modelConfig.brainclaw.tab")}</TabsTrigger>
          <TabsTrigger value="advanced">{t("settings.modelConfig.brainclaw.advancedTab")}</TabsTrigger>
        </TabsList>
      </Tabs>
      {llmMode === "relayclaw_brainclaw" ? (
        automaticThirdPartyTextRoute ? (
          <p role="status" className="rounded-md border border-primary/25 bg-primary/[0.04] px-3 py-2 text-xs leading-relaxed text-muted-foreground">
            {t("settings.modelConfig.brainclaw.autoDescription")}
          </p>
        ) : (
          <BrainClawGatewayPanel config={config} loading={loading} />
        )
      ) : (
        <CapabilityModelDefaultsBlock config={config} />
      )}
    </div>
  );
}

function CapabilityModelDefaultsBlock({ config }: { config: ModelGatewayConfig | undefined }) {
  const { t } = useTranslation();
  const saveDefaults = useSaveCapabilityDefaults();
  const textReasoningEfforts = ["low", "medium", "high", "xhigh", "max"] as const;
  const textModels = useMemo(
    () => (config?.thirdParty?.groups ?? [])
      .filter((group) => group.capabilities.includes("text"))
      .flatMap((group) => group.modelMappings.map((mapping) => ({
        value: `${group.id}::${mapping.upstreamModel.trim()}`,
        label: `${mapping.upstreamModel.trim()} · ${group.name}`,
      })))
      .filter((item) => item.label.trim().length > 0),
    [config?.thirdParty?.groups],
  );
  const embeddingModels = useMemo(
    () => (config?.thirdParty?.groups ?? [])
      .filter((group) => group.capabilities.includes("embedding"))
      .flatMap((group) => group.modelMappings.map((mapping) => ({
        value: `${group.id}::${mapping.upstreamModel.trim()}`,
        label: `${mapping.upstreamModel.trim()} · ${group.name}`,
      })))
      .filter((item) => item.label.trim().length > 0),
    [config?.thirdParty?.groups],
  );
  const [textModel, setTextModel] = useState(config?.capabilityDefaults?.textGroupId && config.capabilityDefaults.textModel ? `${config.capabilityDefaults.textGroupId}::${config.capabilityDefaults.textModel}` : textModels[0]?.value ?? "");
  const [textReasoningEffort, setTextReasoningEffort] = useState<
    (typeof textReasoningEfforts)[number]
  >(config?.capabilityDefaults?.textReasoningEffort ?? "low");
  const [embeddingModel, setEmbeddingModel] = useState(config?.capabilityDefaults?.embeddingGroupId && config.capabilityDefaults.embeddingModel ? `${config.capabilityDefaults.embeddingGroupId}::${config.capabilityDefaults.embeddingModel}` : embeddingModels[0]?.value ?? "");
  useEffect(() => {
    const savedText = config?.capabilityDefaults?.textGroupId && config.capabilityDefaults.textModel ? `${config.capabilityDefaults.textGroupId}::${config.capabilityDefaults.textModel}` : "";
    const savedEmbedding = config?.capabilityDefaults?.embeddingGroupId && config.capabilityDefaults.embeddingModel ? `${config.capabilityDefaults.embeddingGroupId}::${config.capabilityDefaults.embeddingModel}` : "";
    setTextModel(textModels.some((item) => item.value === savedText) ? savedText : textModels[0]?.value ?? "");
    setTextReasoningEffort(config?.capabilityDefaults?.textReasoningEffort ?? "low");
    setEmbeddingModel(embeddingModels.some((item) => item.value === savedEmbedding) ? savedEmbedding : embeddingModels[0]?.value ?? "");
  }, [config?.capabilityDefaults, config?.llmEffective.model, textModels, embeddingModels]);
  const save = async () => {
    const [textGroupId, selectedTextModel] = textModel.split("::");
    const [embeddingGroupId, selectedEmbeddingModel] = embeddingModel.split("::");
    const response = await saveDefaults.mutateAsync({
      textGroupId: textGroupId || undefined,
      textModel: selectedTextModel || undefined,
      textReasoningEffort,
      embeddingGroupId: embeddingGroupId || undefined,
      embeddingModel: selectedEmbeddingModel || undefined,
    });
    if (!response.ok) toast.error(t("settings.modelConfig.requestFailed"));
    else toast.success(t("settings.modelConfig.thirdParty.saved"));
  };

  return (
    <section className="mt-4 rounded-md border border-border/70 p-3">
      <h4 className="text-xs font-medium text-foreground">
        {t("settings.modelConfig.capabilityDefaults.title", { defaultValue: "能力默认模型" })}
      </h4>
      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
        {t("settings.modelConfig.capabilityDefaults.description", { defaultValue: "虾集文本和视觉功能共用文本网关模型；Embedding 和媒体模型从已配置的第三方组读取。" })}
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <CapabilityDefaultRow
          label={t("settings.modelConfig.capabilityDefaults.text", { defaultValue: "文本 / 视觉模型" })}
          model={textModels[0]?.label || ""}
          available={textModels}
          value={textModel}
          onChange={setTextModel}
        />
        <div className="rounded-md border border-border/60 px-3 py-2.5">
          <div className="text-[11px] text-muted-foreground">
            {t("settings.modelConfig.capabilityDefaults.reasoning", {
              defaultValue: "文本思考级别",
            })}
          </div>
          <Select
            value={textReasoningEffort}
            onValueChange={(value) => {
              if (textReasoningEfforts.includes(value as (typeof textReasoningEfforts)[number])) {
                setTextReasoningEffort(value as (typeof textReasoningEfforts)[number]);
              }
            }}
          >
            <SelectTrigger
              aria-label={t("settings.modelConfig.capabilityDefaults.reasoning", {
                defaultValue: "文本思考级别",
              })}
              size="sm"
              className="mt-1 h-8 w-full font-mono text-xs"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent alignItemWithTrigger={false}>
              {textReasoningEfforts.map((effort) => (
                <SelectItem key={effort} value={effort}>
                  {effort}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="mt-1 text-[10px] text-muted-foreground">
            {t("settings.modelConfig.capabilityDefaults.reasoningHint", {
              defaultValue: "仅作用于第三方文本 / 视觉理解请求。",
            })}
          </div>
        </div>
        <CapabilityDefaultRow
          label={t("settings.modelConfig.capabilityDefaults.embedding", { defaultValue: "Embedding 模型" })}
          model={embeddingModels[0]?.label || ""}
          available={embeddingModels}
          optional
          value={embeddingModel}
          onChange={setEmbeddingModel}
        />
      </div>
      <div className="mt-3 flex justify-end">
        <Button type="button" size="sm" onClick={save} disabled={saveDefaults.isPending || textModels.length === 0}>
          {t("settings.modelConfig.thirdParty.save")}
        </Button>
      </div>
    </section>
  );
}

function CapabilityDefaultRow({
  label,
  model,
  available,
  optional = false,
  value,
  onChange,
}: {
  label: string;
  model: string;
  available: Array<{ value: string; label: string }>;
  optional?: boolean;
  value: string;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="rounded-md border border-border/60 px-3 py-2.5">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      {available.length > 0 ? (
        <Select value={value} onValueChange={(next) => { if (next) onChange(next); }}>
          <SelectTrigger size="sm" className="mt-1 h-8 w-full font-mono text-xs"><SelectValue /></SelectTrigger>
          <SelectContent alignItemWithTrigger={false}>
            {available.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
          </SelectContent>
        </Select>
      ) : <div className="mt-1 font-mono text-xs text-foreground">{model || t(optional ? "settings.modelConfig.capabilityDefaults.notConfiguredOptional" : "settings.modelConfig.capabilityDefaults.notConfigured")}</div>}
      {available.length > 1 ? (
        <div className="mt-1 text-[10px] text-muted-foreground">{t("settings.modelConfig.capabilityDefaults.discoveredUpstream", { n: available.length })}</div>
      ) : null}
    </div>
  );
}

function AgentLlmPanel({
  config,
  loading,
}: {
  config: ModelGatewayConfig | undefined;
  loading: boolean;
}) {
  const { t } = useTranslation();
  const saveAgent = useSaveAgentLlmConfig();
  const saved = config?.agent;
  const [mode, setMode] = useState<AgentLlmMode>(saved?.mode ?? "inherit");
  const [baseUrl, setBaseUrl] = useState(saved?.baseUrl ?? "");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(saved?.model ?? "");
  const [revealKey, setRevealKey] = useState(false);

  useEffect(() => {
    if (!saved) return;
    setMode(saved.mode);
    setBaseUrl(saved.baseUrl);
    setModel(saved.model);
  }, [saved]);

  const endpointChanged = Boolean(
    saved?.baseUrl && baseUrl.trim() && baseUrl.trim().replace(/\/$/, "") !== saved.baseUrl.replace(/\/$/, ""),
  );
  const thirdPartyReady = Boolean(
    baseUrl.trim() &&
      model.trim() &&
      (apiKey.trim() || (saved?.apiKeyPreview && !endpointChanged)),
  );

  const handleSave = async () => {
    try {
      const response = await saveAgent.mutateAsync(
        mode === "inherit"
          ? { mode }
          : {
              mode,
              baseUrl: baseUrl.trim(),
              model: model.trim(),
              ...(apiKey.trim() ? { apiKey: apiKey.trim() } : {}),
            },
      );
      if (!response.ok) {
        toast.error(
          getResponseErrorMessage(response, t("settings.modelConfig.requestFailed")),
        );
        return;
      }
      setApiKey("");
      setRevealKey(false);
      toast.success(t("settings.modelConfig.agent.saved"));
    } catch (error) {
      toast.error(
        await getRequestErrorMessage(error, t("settings.modelConfig.requestFailed")),
      );
    }
  };

  return (
    <div className="mt-4 rounded-md border border-border/70 px-3 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 className="text-xs font-medium text-foreground">
            {t("settings.modelConfig.agent.title")}
          </h4>
          <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
            {t("settings.modelConfig.agent.description")}
          </p>
        </div>
        <Tabs value={mode} onValueChange={(value) => setMode(value as AgentLlmMode)}>
          <TabsList>
            <TabsTrigger value="inherit">
              {t("settings.modelConfig.agent.inherit")}
            </TabsTrigger>
            <TabsTrigger value="third_party">
              {t("settings.modelConfig.agent.thirdParty")}
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {mode === "third_party" ? (
        <div className="mt-3 space-y-2.5">
          <div className="grid grid-cols-[120px_1fr] items-center gap-3">
            <Label className="justify-start text-[11px] font-normal tracking-wide text-muted-foreground uppercase">
              {t("settings.modelConfig.fields.gatewayBaseUrl")}
            </Label>
            <Input
              name="agent-third-party-base-url"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="https://api.example.com/v1"
              autoCapitalize="none"
              spellCheck={false}
              className="h-9"
            />
          </div>
          <div className="grid grid-cols-[120px_1fr] items-center gap-3">
            <Label className="justify-start text-[11px] font-normal tracking-wide text-muted-foreground uppercase">
              {t("settings.modelConfig.fields.apiKey")}
            </Label>
            <div className="relative">
              <Input
                name="agent-third-party-api-key"
                autoComplete="new-password"
                data-1p-ignore="true"
                data-lpignore="true"
                type={revealKey ? "text" : "password"}
                value={apiKey}
                onChange={(event) => {
                  setApiKey(event.target.value);
                  if (!event.target.value) setRevealKey(false);
                }}
                placeholder={
                  saved?.apiKeyPreview
                    ? t("settings.secretSavedPlaceholder", {
                        preview: saved.apiKeyPreview,
                      })
                    : "sk-..."
                }
                autoCapitalize="none"
                spellCheck={false}
                className={cn(
                  "h-9",
                  apiKey ? "pr-9" : saved?.apiKeyPreview ? "pr-16" : "",
                )}
              />
              {apiKey ? (
                <button
                  type="button"
                  onClick={() => setRevealKey((value) => !value)}
                  aria-label={
                    revealKey
                      ? t("settings.mediaStorage.hideSecret")
                      : t("settings.mediaStorage.showSecret")
                  }
                  className="absolute top-1/2 right-2 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
                >
                  {revealKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              ) : saved?.apiKeyPreview ? (
                <span className="absolute top-1/2 right-2 -translate-y-1/2 rounded bg-emerald-400/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400">
                  {t("settings.secretSavedBadge")}
                </span>
              ) : null}
            </div>
          </div>
          <div className="grid grid-cols-[120px_1fr] items-center gap-3">
            <Label className="justify-start text-[11px] font-normal tracking-wide text-muted-foreground uppercase">
              {t("settings.modelConfig.agent.model")}
            </Label>
            <Input
              name="agent-third-party-model"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              placeholder="gpt-5.2-codex"
              autoCapitalize="none"
              spellCheck={false}
              className="h-9"
            />
          </div>
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            {t("settings.modelConfig.agent.thirdPartyHint")}
          </p>
        </div>
      ) : null}

      <div className="mt-3 flex justify-end">
        <Button
          type="button"
          size="sm"
          onClick={handleSave}
          disabled={
            loading ||
            saveAgent.isPending ||
            (mode === "third_party" && !thirdPartyReady)
          }
        >
          {saveAgent.isPending ? <Loader2 className="size-3.5 animate-spin" /> : null}
          {t("settings.modelConfig.agent.save")}
        </Button>
      </div>
    </div>
  );
}

function OfficialGatewayPanel({
  config,
  loading,
  activateHybrid = false,
}: {
  config: ModelGatewayConfig | undefined;
  loading: boolean;
  activateHybrid?: boolean;
}) {
  const { t } = useTranslation();
  const official = config?.official;
  const enableOfficial = useEnableOfficial();
  const enableHybrid = useEnableHybrid();
  const saveOfficial = useSaveOfficialConfig();
  const mediaCatalogQuery = useOfficialMediaCatalogStatus();
  const saveMediaCatalogPreferences = useSaveOfficialMediaCatalogPreferences();
  const checkMediaCatalog = useCheckOfficialMediaCatalog();
  const automaticCatalogCheckStarted = useRef(false);

  const [apiKey, setApiKey] = useState("");
  const [revealKey, setRevealKey] = useState(false);
  const apiKeyInputRef = useRef<HTMLInputElement>(null);
  const savedApiKeyPreview = official?.configured ? official.apiKeyPreview : "";
  const mediaCatalog = mediaCatalogQuery.data?.data;

  const runMediaCatalogCheck = async (manual: boolean) => {
    try {
      const response = await checkMediaCatalog.mutateAsync();
      if (!response.ok) {
        if (manual) {
          toast.error(
            getResponseErrorMessage(
              response,
              t("settings.modelConfig.official.mediaCatalogCheckFailed"),
            ),
          );
        }
        return;
      }
      if (manual) {
        toast.success(
          t(
            response.data.updated
              ? "settings.modelConfig.official.mediaCatalogUpdated"
              : "settings.modelConfig.official.mediaCatalogUpToDate",
          ),
        );
      }
    } catch (error) {
      if (manual) {
        toast.error(
          await getRequestErrorMessage(
            error,
            t("settings.modelConfig.official.mediaCatalogCheckFailed"),
          ),
        );
      }
    }
  };

  useEffect(() => {
    if (
      automaticCatalogCheckStarted.current ||
      !official?.configured ||
      !mediaCatalog?.autoUpdate ||
      checkMediaCatalog.isPending
    )
      return;
    automaticCatalogCheckStarted.current = true;
    void runMediaCatalogCheck(false);
  }, [official?.configured, mediaCatalog?.autoUpdate, checkMediaCatalog.isPending]);

  const handleMediaCatalogAutoUpdate = async () => {
    const next = !mediaCatalog?.autoUpdate;
    try {
      const response = await saveMediaCatalogPreferences.mutateAsync(next);
      if (!response.ok) {
        toast.error(
          getResponseErrorMessage(
            response,
            t("settings.modelConfig.requestFailed"),
          ),
        );
      }
    } catch (error) {
      toast.error(
        await getRequestErrorMessage(
          error,
          t("settings.modelConfig.requestFailed"),
        ),
      );
    }
  };

  const handleSave = async () => {
    // Password managers may update the DOM without firing React's onChange.
    const trimmedApiKey = (
      apiKey ||
      apiKeyInputRef.current?.value ||
      ""
    ).trim();
    try {
      if (!trimmedApiKey) {
        if (!official?.configured) {
          toast.error(t("settings.modelConfig.official.missingFields"));
          return;
        }
        const response = await (
          activateHybrid && config?.custom?.configured
            ? enableHybrid
            : enableOfficial
        ).mutateAsync();
        if (!response.ok) {
          toast.error(
            getResponseErrorMessage(
              response,
              t("settings.modelConfig.requestFailed"),
            ),
          );
          return;
        }
        toast.success(t("settings.modelConfig.official.saved"));
        return;
      }
      const response = await saveOfficial.mutateAsync({
        newApiApiKey: trimmedApiKey,
      });
      if (!response.ok) {
        toast.error(
          getResponseErrorMessage(
            response,
            t("settings.modelConfig.requestFailed"),
          ),
        );
        return;
      }
      if (activateHybrid && config?.custom?.configured) {
        const hybridResponse = await enableHybrid.mutateAsync();
        if (!hybridResponse.ok) {
          toast.error(
            getResponseErrorMessage(
              hybridResponse,
              t("settings.modelConfig.requestFailed"),
            ),
          );
          return;
        }
      }
      setApiKey("");
      setRevealKey(false);
      toast.success(t("settings.modelConfig.official.saved"));
    } catch (error) {
      toast.error(
        await getRequestErrorMessage(
          error,
          t("settings.modelConfig.requestFailed"),
        ),
      );
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-xs leading-relaxed text-muted-foreground">
        {t("settings.modelConfig.official.description")}{" "}
        <a
          href="https://relayclaw.cdnfg.com"
          target="_blank"
          rel="noreferrer"
          className="text-primary underline-offset-4 hover:underline"
        >
          {t("settings.modelConfig.official.registerLink")}
        </a>
      </p>

      {official?.configured ? <div className="rounded-md border border-border/70 px-3 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-medium text-foreground">
              {t("settings.modelConfig.official.mediaCatalogTitle")}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              {mediaCatalog
                ? t("settings.modelConfig.official.mediaCatalogStatus", {
                    version: mediaCatalog.catalogVersion,
                    count: mediaCatalog.modelCount,
                    source: t(
                      `settings.modelConfig.official.mediaCatalogSources.${mediaCatalog.source}`,
                    ),
                  })
                : t("settings.modelConfig.loading")}
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void runMediaCatalogCheck(true)}
            disabled={
              mediaCatalogQuery.isLoading || checkMediaCatalog.isPending
            }
          >
            <RotateCw
              className={cn(
                "size-3.5",
                checkMediaCatalog.isPending && "animate-spin",
              )}
            />
            {t("settings.modelConfig.official.mediaCatalogCheckNow")}
          </Button>
        </div>
        <div className="mt-3 flex items-center justify-between gap-3 border-t border-border/60 pt-3">
          <div>
            <Label className="text-xs font-normal text-foreground">
              {t("settings.modelConfig.official.mediaCatalogAutoUpdate")}
            </Label>
            <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
              {t("settings.modelConfig.official.mediaCatalogAutoUpdateHint")}
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={mediaCatalog?.autoUpdate ?? false}
            aria-label={t(
              "settings.modelConfig.official.mediaCatalogAutoUpdate",
            )}
            disabled={!mediaCatalog || saveMediaCatalogPreferences.isPending}
            onClick={() => void handleMediaCatalogAutoUpdate()}
            className={cn(
              "relative h-5 w-9 shrink-0 rounded-full border transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50",
              mediaCatalog?.autoUpdate
                ? "border-primary bg-primary"
                : "border-input bg-muted",
            )}
          >
            <span
              className={cn(
                "absolute top-0.5 left-0.5 size-4 rounded-full bg-white shadow-sm transition-transform",
                mediaCatalog?.autoUpdate ? "translate-x-4" : "translate-x-0",
              )}
            />
          </button>
        </div>
      </div> : null}

      <div className="space-y-2.5">
        <div className="grid grid-cols-[120px_1fr] items-center gap-3">
          <Label className="justify-start text-[11px] font-normal tracking-wide text-muted-foreground uppercase">
            {t("settings.modelConfig.fields.apiKey")}
          </Label>
          <div className="relative">
            <Input
              ref={apiKeyInputRef}
              name="relayclaw-official-api-key"
              autoComplete="new-password"
              data-1p-ignore="true"
              data-lpignore="true"
              type={revealKey ? "text" : "password"}
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value);
                if (!e.target.value) setRevealKey(false);
              }}
              placeholder={
                savedApiKeyPreview
                  ? t("settings.secretSavedPlaceholder", {
                      preview: savedApiKeyPreview,
                    })
                  : "sk-..."
              }
              autoCapitalize="none"
              spellCheck={false}
              className={cn(
                "h-9 rounded-md border-input/80 focus-visible:border-ring/70 focus-visible:ring-1 focus-visible:ring-ring/30",
                apiKey ? "pr-9" : savedApiKeyPreview ? "pr-16" : "",
              )}
            />
            {apiKey ? (
              <button
                type="button"
                onClick={() => setRevealKey((r) => !r)}
                aria-label={
                  revealKey
                    ? t("settings.mediaStorage.hideSecret")
                    : t("settings.mediaStorage.showSecret")
                }
                className="absolute top-1/2 right-2 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
              >
                {revealKey ? (
                  <EyeOff className="size-4" />
                ) : (
                  <Eye className="size-4" />
                )}
              </button>
            ) : savedApiKeyPreview ? (
              <span className="absolute top-1/2 right-2 -translate-y-1/2 rounded bg-emerald-400/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400">
                {t("settings.secretSavedBadge")}
              </span>
            ) : null}
          </div>
        </div>
      </div>

      <div className="flex justify-end">
        <Button
          type="button"
          size="sm"
          onClick={handleSave}
          disabled={
            loading ||
            saveOfficial.isPending ||
            enableOfficial.isPending ||
            enableHybrid.isPending
          }
        >
          {saveOfficial.isPending ||
          enableOfficial.isPending ||
          enableHybrid.isPending ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : null}
          {t("settings.modelConfig.official.save")}
        </Button>
      </div>
    </div>
  );
}

export function BrainClawGatewayPanel({
  config,
  loading,
}: {
  config: ModelGatewayConfig | undefined;
  loading: boolean;
}) {
  const { t } = useTranslation();
  const saveBrainClaw = useSaveBrainClawConfig();
  const enableBrainClaw = useEnableBrainClaw();
  const savedBrainClaw = config?.brainclaw;
  const savedBaseUrl =
    savedBrainClaw?.baseUrl ||
    (config?.llmEffective.brainclaw ? config.llmEffective.baseUrl : "") ||
    config?.official.baseUrl ||
    "";
  const [baseUrl, setBaseUrl] = useState(savedBaseUrl);
  const [apiKey, setApiKey] = useState("");
  const [revealKey, setRevealKey] = useState(false);
  const savedApiKeyPreview =
    savedBrainClaw?.apiKeyPreview ||
    (config?.llmEffective.brainclaw ? config.llmEffective.apiKeyPreview : "") ||
    config?.official.apiKeyPreview ||
    "";

  useEffect(() => {
    if (savedBaseUrl) {
      setBaseUrl((current) => (current === savedBaseUrl ? current : savedBaseUrl));
    }
  }, [savedBaseUrl]);

  const handleSave = async () => {
    const trimmedApiKey = apiKey.trim();
    const trimmedBaseUrl = baseUrl.trim();
    if (!trimmedBaseUrl) {
      toast.error(t("settings.modelConfig.brainclaw.missingEndpoint"));
      return;
    }
    try {
      const response = trimmedApiKey || trimmedBaseUrl !== savedBaseUrl
        ? await saveBrainClaw.mutateAsync({
            newApiBaseUrl: trimmedBaseUrl,
            ...(trimmedApiKey ? { newApiApiKey: trimmedApiKey } : {}),
          })
        : await enableBrainClaw.mutateAsync();
      if (!response.ok) {
        toast.error(getResponseErrorMessage(response, t("settings.modelConfig.requestFailed")));
        return;
      }
      setApiKey("");
      setRevealKey(false);
      toast.success(t("settings.modelConfig.brainclaw.enabled"));
    } catch (error) {
      toast.error(await getRequestErrorMessage(error, t("settings.modelConfig.requestFailed")));
    }
  };

  return (
    <div className="mt-4 rounded-md border border-primary/30 bg-primary/[0.04] px-3 py-3">
      <h4 className="text-xs font-medium text-foreground">
        {t("settings.modelConfig.brainclaw.title")}
      </h4>
      <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
        {t("settings.modelConfig.brainclaw.description")}
      </p>

      <div className="mt-3 space-y-2.5">
        <div className="grid grid-cols-[120px_1fr] items-center gap-3">
          <Label className="justify-start text-[11px] font-normal tracking-wide text-muted-foreground uppercase">
            {t("settings.modelConfig.fields.gatewayBaseUrl")}
          </Label>
          <Input
            name="brainclaw-newapi-base-url"
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
            placeholder="http://127.0.0.1:3000/v1"
            autoCapitalize="none"
            spellCheck={false}
            className="h-9"
          />
        </div>
        <div className="grid grid-cols-[120px_1fr] items-center gap-3">
          <Label className="justify-start text-[11px] font-normal tracking-wide text-muted-foreground uppercase">
            {t("settings.modelConfig.fields.apiKey")}
          </Label>
          <div className="relative">
            <Input
              name="relayclaw-brainclaw-api-key"
              autoComplete="new-password"
              data-1p-ignore="true"
              data-lpignore="true"
              type={revealKey ? "text" : "password"}
              value={apiKey}
              onChange={(event) => {
                setApiKey(event.target.value);
                if (!event.target.value) setRevealKey(false);
              }}
              placeholder={
                savedApiKeyPreview
                  ? t("settings.secretSavedPlaceholder", { preview: savedApiKeyPreview })
                  : "sk-..."
              }
              autoCapitalize="none"
              spellCheck={false}
              className={cn("h-9", apiKey ? "pr-9" : savedApiKeyPreview ? "pr-16" : "")}
            />
            {apiKey ? (
              <button
                type="button"
                onClick={() => setRevealKey((value) => !value)}
                aria-label={
                  revealKey
                    ? t("settings.mediaStorage.hideSecret")
                    : t("settings.mediaStorage.showSecret")
                }
                className="absolute top-1/2 right-2 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
              >
                {revealKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            ) : savedApiKeyPreview ? (
              <span className="absolute top-1/2 right-2 -translate-y-1/2 rounded bg-emerald-400/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400">
                {t("settings.secretSavedBadge")}
              </span>
            ) : null}
          </div>
        </div>
        <div className="grid grid-cols-[120px_1fr] items-center gap-3 text-[11px]">
          <span className="text-muted-foreground">{t("settings.modelConfig.brainclaw.model")}</span>
          <code className="text-foreground">brainclaw</code>
        </div>
      </div>

      <div className="mt-3 flex justify-end">
        <Button
          type="button"
          size="sm"
          onClick={handleSave}
          disabled={
            loading ||
            saveBrainClaw.isPending ||
            enableBrainClaw.isPending ||
            !baseUrl.trim() ||
            (!apiKey.trim() && !savedApiKeyPreview)
          }
        >
          {saveBrainClaw.isPending || enableBrainClaw.isPending ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : null}
          {t("settings.modelConfig.brainclaw.save")}
        </Button>
      </div>
    </div>
  );
}

export function CustomGatewayPanel({
  config,
  loading,
  baseUrl,
  activateHybrid = false,
}: {
  config: ModelGatewayConfig | undefined;
  loading: boolean;
  baseUrl: string;
  activateHybrid?: boolean;
}) {
  const { t } = useTranslation();
  const initCustom = useInitCustomNewApi();
  const enableHybrid = useEnableHybrid();
  const [setupPassword, setSetupPassword] = useState("");
  const [setupConfirmPassword, setSetupConfirmPassword] = useState("");
  const [initError, setInitError] = useState("");
  const [initNotice, setInitNotice] = useState("");

  const showInitError = (message: string) => {
    setInitError(message);
    setInitNotice("");
    toast.error(message);
  };

  const showInitResponseError = (message: string) => {
    const displayMessage =
      message.includes("setupUsername") ||
      message.includes("NewAPI is not initialized")
        ? t("settings.modelConfig.custom.setupRequired")
        : message;
    showInitError(displayMessage);
  };

  const handleInit = async () => {
    setInitError("");
    setInitNotice("");
    const trimmedSetupPassword = setupPassword.trim();
    const trimmedSetupConfirmPassword = setupConfirmPassword.trim();
    const hasSetupPassword = Boolean(
      trimmedSetupPassword || trimmedSetupConfirmPassword,
    );
    if (
      hasSetupPassword &&
      (!trimmedSetupPassword || !trimmedSetupConfirmPassword)
    ) {
      showInitError(t("settings.modelConfig.custom.setupPasswordIncomplete"));
      return;
    }
    if (hasSetupPassword && trimmedSetupPassword.length < 8) {
      showInitError(t("settings.modelConfig.custom.setupPasswordTooShort"));
      return;
    }
    if (
      hasSetupPassword &&
      trimmedSetupPassword !== trimmedSetupConfirmPassword
    ) {
      showInitError(t("settings.modelConfig.custom.setupPasswordMismatch"));
      return;
    }

    try {
      const response = await initCustom.mutateAsync({
        ...(baseUrl.trim() ? { newApiBaseUrl: baseUrl.trim() } : {}),
        ...(hasSetupPassword
          ? {
              setupUsername: "root",
              setupPassword: trimmedSetupPassword,
              setupConfirmPassword: trimmedSetupConfirmPassword,
            }
          : {}),
      });
      if (response.ok !== true) {
        showInitResponseError(
          getResponseErrorMessage(
            response,
            t("settings.modelConfig.requestFailed"),
          ),
        );
        return;
      }
      const passwordIgnored =
        hasSetupPassword &&
        response.data.newApiSetup?.alreadyInitialized === true;
      setSetupPassword("");
      setSetupConfirmPassword("");
      if (passwordIgnored) {
        setInitNotice(
          t(
            "settings.modelConfig.custom.setupAlreadyInitializedPasswordIgnored",
          ),
        );
      }
      if (activateHybrid && config?.official?.configured) {
        const hybridResponse = await enableHybrid.mutateAsync();
        if (!hybridResponse.ok) {
          showInitResponseError(
            getResponseErrorMessage(
              hybridResponse,
              t("settings.modelConfig.requestFailed"),
            ),
          );
          return;
        }
      }
      toast.success(t("settings.modelConfig.custom.initialized"));
    } catch (error) {
      const message = await getRequestErrorMessage(
        error,
        t("settings.modelConfig.requestFailed"),
      );
      showInitResponseError(message);
    }
  };

  const databaseStatus = config?.provisioner?.database;
  const databaseReady = Boolean(databaseStatus?.available);
  const customConfigured = Boolean(config?.custom?.configured);

  return (
    <div className="space-y-3">
      <p className="text-xs leading-relaxed text-muted-foreground">
        {t("settings.modelConfig.custom.description")}
      </p>

      <div className="rounded-md border border-border/70 p-3">
        <div className="flex items-center justify-between gap-3">
          <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            {t("settings.modelConfig.custom.localStatusTitle")}
          </p>
          <span
            className={cn(
              "text-[11px]",
              customConfigured ? "text-emerald-400" : "text-amber-300",
            )}
          >
            {customConfigured
              ? t("settings.modelConfig.custom.localReady")
              : t("settings.modelConfig.custom.localNeedsInit")}
          </span>
        </div>
        <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
          {databaseReady
            ? t("settings.modelConfig.custom.sqliteReady")
            : t("settings.modelConfig.custom.sqliteWaiting")}
        </p>
      </div>

      {!customConfigured ? (
        <div className="rounded-md border border-border/70 p-3">
          <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            {t("settings.modelConfig.custom.setupAdminTitle")}
          </p>
          <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
            {t("settings.modelConfig.custom.setupAdminDescription")}
          </p>
          <div className="mt-3 space-y-2.5">
            <FieldRow
              secret
              name="newapi-setup-password"
              autoComplete="new-password"
              label={t("settings.modelConfig.custom.setupPassword")}
              value={setupPassword}
              onChange={setSetupPassword}
              placeholder={t(
                "settings.modelConfig.custom.setupPasswordPlaceholder",
              )}
            />
            <FieldRow
              secret
              name="newapi-setup-password-confirmation"
              autoComplete="new-password"
              label={t("settings.modelConfig.custom.setupConfirmPassword")}
              value={setupConfirmPassword}
              onChange={setSetupConfirmPassword}
              placeholder={t(
                "settings.modelConfig.custom.setupConfirmPasswordPlaceholder",
              )}
            />
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
            {t("settings.modelConfig.custom.setupPasswordOnlyOnce")}
          </p>
        </div>
      ) : null}

      {initError ? (
        <p
          role="alert"
          aria-live="polite"
          className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-[11px] leading-relaxed text-destructive"
        >
          {initError}
        </p>
      ) : null}
      {!initError && initNotice ? (
        <p
          role="status"
          aria-live="polite"
          className="rounded-md border border-amber-400/35 bg-amber-400/10 px-3 py-2 text-[11px] leading-relaxed text-amber-200"
        >
          {initNotice}
        </p>
      ) : null}

      <div className="flex justify-end">
        <Button
          type="button"
          size="sm"
          onClick={handleInit}
          disabled={loading || initCustom.isPending}
        >
          {initCustom.isPending ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : null}
          {t(
            customConfigured
              ? "settings.modelConfig.custom.repair"
              : "settings.modelConfig.custom.init",
          )}
        </Button>
      </div>
    </div>
  );
}


interface QuickProfileChannel {
  id: string;
  provider: FeatureModelProvider;
  type?: number;
  baseUrl: string;
  priority?: number;
  settings?: Record<string, unknown>;
}

interface QuickProfileModel {
  channel: string;
  model: string;
  mediaType?: "image" | "video" | "audio";
  label?: string;
  enabled?: boolean;
  sortOrder?: number;
  config?: Record<string, unknown>;
}

interface QuickModelProfile {
  version: 2;
  name: string;
  channels: QuickProfileChannel[];
  featureModels: {
    text: QuickProfileModel;
    vision: QuickProfileModel;
    overrides: Record<string, QuickProfileModel>;
  };
  embedding: QuickProfileModel & { dimension: number; batchSize: number };
  mediaModels: Record<string, QuickProfileModel>;
}

function comfyNode(classType: string, inputs: Record<string, unknown>) {
  return { inputs, class_type: classType };
}

function minimaxH3Fl2vaWorkflow(firstFrame: boolean) {
  const generationInputs: Record<string, unknown> = {
    prompt: "",
    width: ["115", 0],
    height: ["115", 1],
    length: ["105:107", 1],
    clip: ["105:13", 0],
    vae: ["105:11", 0],
  };
  if (firstFrame) generationInputs.first_frame = ["114", 0];
  return {
    "92": comfyNode("SaveVideo", {
      filename_prefix: "video/MiniMax_H3",
      format: "auto",
      codec: "auto",
      video: ["105:91", 0],
    }),
    ...(firstFrame
      ? {
          "114": comfyNode("LoadImage", {
            image: "transparent_rgb_gaming_mouse.png",
          }),
          "119": comfyNode("ImageScaleToTotalPixels", {
            upscale_method: "nearest-exact",
            megapixels: 1,
            resolution_steps: 32,
          }),
          "120": comfyNode("GetImageSize", { image: ["119", 0] }),
        }
      : {}),
    "115": comfyNode("ResolutionSelector", {
      aspect_ratio: firstFrame ? "1:1 (Square)" : "16:9 (Widescreen)",
      megapixels: 0.4,
      multiple: 32,
    }),
    "105:11": comfyNode("VAELoader", {
      vae_name: "minimax_h3_video_vae_fp16.safetensors",
    }),
    "105:24": comfyNode("VAELoader", {
      vae_name: "minimax_h3_audio_vae_fp32.safetensors",
    }),
    "105:23": comfyNode("VAEDecodeAudio", {
      samples: ["105:14", 0],
      vae: ["105:24", 0],
    }),
    "105:10": comfyNode("VAEDecode", {
      samples: ["105:14", 0],
      vae: ["105:11", 0],
    }),
    "105:17": comfyNode("KSamplerSelect", { sampler_name: "res_multistep" }),
    "105:9": comfyNode("BasicScheduler", {
      scheduler: "simple",
      steps: 20,
      denoise: 1,
      model: ["105:6", 0],
    }),
    "105:14": comfyNode("SamplerCustomAdvanced", {
      noise: ["105:15", 0],
      guider: ["105:16", 0],
      sampler: ["105:17", 0],
      sigmas: ["105:9", 0],
      latent_image: ["105:104", 1],
    }),
    "105:16": comfyNode("BasicGuider", {
      model: ["105:6", 0],
      conditioning: ["105:104", 0],
    }),
    "105:6": comfyNode("UNETLoader", {
      unet_name: "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
      weight_dtype: "default",
    }),
    "105:13": comfyNode("CLIPLoader", {
      clip_name: "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
      type: "minimax",
      device: "default",
    }),
    "105:15": comfyNode("RandomNoise", {
      noise_seed: firstFrame ? 168866841893410 : 556589502035082,
    }),
    "105:91": comfyNode("CreateVideo", {
      fps: 24,
      bit_depth: 8,
      images: ["105:10", 0],
      audio: ["105:23", 0],
    }),
    "105:104": comfyNode("MiniMaxH3ImageToVideo", generationInputs),
    "105:107": comfyNode("ComfyMathExpression", {
      expression:
        "max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17",
      "values.a": ["105:111", 0],
    }),
    "105:111": comfyNode("PrimitiveFloat", { value: 5 }),
  };
}

function minimaxH3ReferenceWorkflow() {
  return {
    "92": comfyNode("SaveVideo", {
      filename_prefix: "video/MiniMax_H3",
      format: "auto",
      codec: "auto",
      video: ["130", 0],
    }),
    "115": comfyNode("ResolutionSelector", {
      aspect_ratio: "16:9 (Widescreen)",
      megapixels: 0.4,
      multiple: 32,
    }),
    "119": comfyNode("VAELoader", {
      vae_name: "minimax_h3_video_vae_fp16.safetensors",
    }),
    "120": comfyNode("VAELoader", {
      vae_name: "minimax_h3_audio_vae_fp32.safetensors",
    }),
    "121": comfyNode("VAEDecodeAudio", {
      samples: ["125", 0],
      vae: ["120", 0],
    }),
    "122": comfyNode("VAEDecode", { samples: ["125", 0], vae: ["119", 0] }),
    "123": comfyNode("KSamplerSelect", { sampler_name: "res_multistep" }),
    "124": comfyNode("BasicScheduler", {
      scheduler: "simple",
      steps: 20,
      denoise: 1,
      model: ["127", 0],
    }),
    "125": comfyNode("SamplerCustomAdvanced", {
      noise: ["129", 0],
      guider: ["126", 0],
      sampler: ["123", 0],
      sigmas: ["124", 0],
      latent_image: ["136", 1],
    }),
    "126": comfyNode("BasicGuider", {
      model: ["127", 0],
      conditioning: ["136", 0],
    }),
    "127": comfyNode("UNETLoader", {
      unet_name: "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
      weight_dtype: "default",
    }),
    "128": comfyNode("CLIPLoader", {
      clip_name: "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
      type: "minimax",
      device: "default",
    }),
    "129": comfyNode("RandomNoise", { noise_seed: 157368968253448 }),
    "130": comfyNode("CreateVideo", {
      fps: 24,
      bit_depth: 8,
      images: ["122", 0],
      audio: ["121", 0],
    }),
    "131": comfyNode("ComfyMathExpression", {
      expression:
        "max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17",
      "values.a": ["132", 0],
    }),
    "132": comfyNode("PrimitiveFloat", { value: 5 }),
    "136": comfyNode("MiniMaxH3ReferenceToVideo", {
      prompt: ["138", 0],
      width: ["115", 0],
      height: ["115", 1],
      length: ["131", 1],
      ref_image_size: "match",
      clip: ["128", 0],
      vae: ["119", 0],
      audio_vae: ["120", 0],
      "ref_images.ref_image_0": ["137", 0],
      "ref_images.ref_image_1": ["139", 0],
    }),
    "137": comfyNode("LoadImage", { image: "red_superboy_on_city_roof.png" }),
    "138": comfyNode("PrimitiveStringMultiline", { value: "" }),
    "139": comfyNode("LoadImage", { image: "mecha_dragon_lightning.png" }),
  };
}

export const HYBRID_COMFYUI_WORKFLOWS = {
  model: "MiniMax-H3-local",
  workflows: {
    minimax_h3_t2v: minimaxH3Fl2vaWorkflow(false),
    minimax_h3_i2v: minimaxH3Fl2vaWorkflow(true),
    minimax_h3_r2v: minimaxH3ReferenceWorkflow(),
  },
};

type ChannelCapability =
  | "text"
  | "vision"
  | "embedding"
  | "rerank"
  | "image"
  | "video"
  | "audio";

const CUSTOM_PROVIDER_CHANNEL_TYPES: Readonly<Record<string, number>> = {
  fal_ai: 61,
  comfyui: 63,
};

function customProviderChannelType(provider: string): number | undefined {
  return CUSTOM_PROVIDER_CHANNEL_TYPES[provider];
}

export function providersSupportingCapability(
  configuredProviders: readonly FeatureModelProvider[],
  channelTypeByProvider: ReadonlyMap<string, NewApiChannelType>,
  capability: ChannelCapability,
  currentProvider?: FeatureModelProvider,
): FeatureModelProvider[] {
  const supported = configuredProviders.filter((provider) => {
    const channelType = channelTypeByProvider.get(provider);
    return !channelType || channelType.capabilities.includes(capability);
  });
  if (
    currentProvider &&
    configuredProviders.includes(currentProvider) &&
    !supported.includes(currentProvider)
  ) {
    return [currentProvider, ...supported];
  }
  return supported;
}

function parseQuickModelProfile(value: string): QuickModelProfile {
  const profile = JSON.parse(value) as QuickModelProfile;
  if (profile.version !== 2) throw new Error("unsupported profile version");
  if (!Array.isArray(profile.channels) || profile.channels.length === 0) {
    throw new Error("channels must be a non-empty array");
  }
  const channelIds = new Set<string>();
  const providers = new Set<string>();
  for (const channel of profile.channels) {
    const id = channel.id?.trim();
    if (!id) throw new Error("channel.id is required");
    if (channelIds.has(id)) throw new Error(`duplicate channel id: ${id}`);
    if (!/^[a-z0-9][a-z0-9_-]*$/.test(channel.provider)) {
      throw new Error(`unsupported provider: ${channel.provider}`);
    }
    if (
      channel.type !== undefined &&
      (!Number.isInteger(channel.type) || channel.type <= 0)
    ) {
      throw new Error(`invalid channel type: ${channel.provider}`);
    }
    if (channel.provider === "comfyui") {
      const workflows = readComfyUIWorkflows(channel.settings ?? {});
      const model = readComfyUIModelName(channel.settings ?? {});
      if (!channel.baseUrl?.trim())
        throw new Error("ComfyUI channel.baseUrl is required");
      if (!model) throw new Error("ComfyUI model name is required");
      if (Object.keys(workflows).length === 0)
        throw new Error("ComfyUI requires at least one workflow");
    }
    if (providers.has(channel.provider)) {
      throw new Error(
        `duplicate provider is not supported yet: ${channel.provider}`,
      );
    }
    channelIds.add(id);
    providers.add(channel.provider);
  }
  const validateModel = (item: QuickProfileModel | undefined, path: string) => {
    if (!item?.channel?.trim() || !channelIds.has(item.channel.trim())) {
      throw new Error(
        `${path}.channel does not reference a configured channel`,
      );
    }
    if (!item.model?.trim()) throw new Error(`${path}.model is required`);
  };
  validateModel(profile.featureModels?.text, "featureModels.text");
  validateModel(profile.featureModels?.vision, "featureModels.vision");
  for (const [featureId, item] of Object.entries(
    profile.featureModels?.overrides ?? {},
  )) {
    validateModel(item, `featureModels.overrides.${featureId}`);
  }
  validateModel(profile.embedding, "embedding");
  if (
    !Number.isInteger(profile.embedding.dimension) ||
    profile.embedding.dimension <= 0
  ) {
    throw new Error("embedding.dimension must be a positive integer");
  }
  if (
    !Number.isInteger(profile.embedding.batchSize) ||
    profile.embedding.batchSize <= 0
  ) {
    throw new Error("embedding.batchSize must be a positive integer");
  }
  if (!profile.mediaModels || typeof profile.mediaModels !== "object") {
    throw new Error("mediaModels must be an object");
  }
  for (const [model, item] of Object.entries(profile.mediaModels)) {
    validateModel(item, `mediaModels.${model}`);
  }
  return profile;
}

export function syncQuickProfileFromAdvancedSettings(
  profile: QuickModelProfile,
  settings: FeatureModelSettings,
): QuickModelProfile | null {
  const usableProviderChannels = Object.values(settings.providerChannels).filter((channel) => {
    if (channel.provider !== "comfyui") return true;
    if (!channel.baseUrl.trim()) return false;
    const comfySettings = normalizeProviderChannelSettings("comfyui", channel.settings);
    return (
      Boolean(readComfyUIModelName(comfySettings)) &&
      Object.keys(readComfyUIWorkflows(comfySettings)).length > 0
    );
  });
  if (usableProviderChannels.length === 0) return null;

  const previousChannelByProvider = new Map(
    profile.channels.map((channel) => [channel.provider, channel]),
  );
  const usedChannelIds = new Set<string>();
  const channels = usableProviderChannels.map((channel) => {
    const previous = previousChannelByProvider.get(channel.provider);
    let id = previous?.id || channel.provider;
    for (let suffix = 2; usedChannelIds.has(id); suffix += 1) id = `${channel.provider}-${suffix}`;
    usedChannelIds.add(id);
    return {
      id,
      provider: channel.provider,
      ...(previous?.type
        ? { type: previous.type }
        : customProviderChannelType(channel.provider)
          ? { type: customProviderChannelType(channel.provider) }
          : {}),
      baseUrl: channel.baseUrl,
      priority: channel.priority,
      settings: normalizeProviderChannelSettings(channel.provider, channel.settings),
    };
  });
  const channelIdByProvider = new Map(channels.map((channel) => [channel.provider, channel.id]));
  const activeChannelIds = new Set(channels.map((channel) => channel.id));
  const modelFromEntry = (entry: FeatureModelEntry | undefined): QuickProfileModel | null => {
    const channel = entry && channelIdByProvider.get(entry.provider);
    const model = entry?.model.trim() ?? "";
    return channel && model ? { channel, model } : null;
  };
  const firstFeatureModel = (requiresVision: boolean) => {
    for (const group of FEATURE_MODEL_GROUPS) {
      for (const feature of group.features) {
        if (Boolean(feature.requiresVision) !== requiresVision) continue;
        const selected = modelFromEntry(settings.featureModels[feature.id]);
        if (selected) return selected;
      }
    }
    return null;
  };
  const keepActiveModel = (item: QuickProfileModel) =>
    activeChannelIds.has(item.channel) && item.model.trim() ? item : null;
  const text = keepActiveModel(profile.featureModels.text) ?? firstFeatureModel(false);
  const vision = keepActiveModel(profile.featureModels.vision) ?? firstFeatureModel(true);
  if (!text || !vision) return null;

  const overrides: Record<string, QuickProfileModel> = {};
  for (const group of FEATURE_MODEL_GROUPS) {
    for (const feature of group.features) {
      const selected = modelFromEntry(settings.featureModels[feature.id]);
      if (!selected) continue;
      const fallback = feature.requiresVision ? vision : text;
      if (
        selected.channel !== fallback.channel ||
        selected.model !== fallback.model
      ) {
        overrides[feature.id] = selected;
      }
    }
  }

  const configuredEmbedding = settings.embeddingModel;
  const embeddingChannel = configuredEmbedding
    ? channelIdByProvider.get(configuredEmbedding.provider)
    : undefined;
  const embedding = embeddingChannel && configuredEmbedding?.upstreamModel.trim()
    ? {
        channel: embeddingChannel,
        model: configuredEmbedding.upstreamModel.trim(),
        dimension: configuredEmbedding.dimension,
        batchSize: configuredEmbedding.batchSize ?? profile.embedding.batchSize,
      }
    : null;
  if (!embedding) return null;

  const mediaModels = Object.fromEntries(
    Object.entries(settings.mediaModels).flatMap(([model, entry]) => {
      const channel = channelIdByProvider.get(entry.provider);
      if (!channel) return [];
      return [[
            model,
            {
              channel,
              model: entry.upstreamModel || model,
              ...(entry.mediaType ? { mediaType: entry.mediaType } : {}),
              ...(entry.label ? { label: entry.label } : {}),
              enabled: entry.enabled !== false,
              sortOrder: entry.sortOrder ?? 100,
              config: entry.config ?? {},
            },
          ] as const];
    }),
  );

  const next: QuickModelProfile = {
    ...profile,
    channels,
    featureModels: { text, vision, overrides },
    embedding,
    mediaModels,
  };
  try {
    return parseQuickModelProfile(JSON.stringify(next));
  } catch {
    return null;
  }
}

function readComfyUIWorkflows(
  settings: Record<string, unknown>,
): Record<string, Record<string, unknown>> {
  const comfyui = settings.comfyui;
  if (!comfyui || typeof comfyui !== "object" || Array.isArray(comfyui))
    return {};
  const config = comfyui as Record<string, unknown>;
  const routes = config.workflow_routes;
  if (Array.isArray(routes)) {
    return Object.fromEntries(
      routes.flatMap((route) => {
        if (!route || typeof route !== "object" || Array.isArray(route))
          return [];
        const item = route as Record<string, unknown>;
        const id = typeof item.id === "string" ? item.id.trim() : "";
        const workflow = item.workflow;
        if (
          !id ||
          !workflow ||
          typeof workflow !== "object" ||
          Array.isArray(workflow)
        )
          return [];
        return [[id, workflow as Record<string, unknown>]];
      }),
    );
  }
  const workflows = config.workflow_by_model;
  if (!workflows || typeof workflows !== "object" || Array.isArray(workflows))
    return {};
  return Object.fromEntries(
    Object.entries(workflows).filter(
      (entry): entry is [string, Record<string, unknown>] =>
        Boolean(entry[0]) &&
        Boolean(entry[1]) &&
        typeof entry[1] === "object" &&
        !Array.isArray(entry[1]),
    ),
  );
}

function readComfyUIModelName(settings: Record<string, unknown>): string {
  const comfyui = settings.comfyui;
  if (!comfyui || typeof comfyui !== "object" || Array.isArray(comfyui))
    return "";
  const config = comfyui as Record<string, unknown>;
  if (typeof config.model_name === "string" && config.model_name.trim()) {
    return config.model_name.trim();
  }
  if (Array.isArray(config.workflow_routes)) {
    for (const route of config.workflow_routes) {
      if (!route || typeof route !== "object" || Array.isArray(route)) continue;
      const match = (route as Record<string, unknown>).match;
      if (!match || typeof match !== "object" || Array.isArray(match)) continue;
      const models = (match as Record<string, unknown>).models;
      if (Array.isArray(models) && typeof models[0] === "string") {
        const model = models[0].trim();
        if (model) return model;
      }
    }
  }
  const legacyModels = Object.keys(readComfyUIWorkflows(settings));
  if (legacyModels.length === 1) return legacyModels[0];
  if (
    legacyModels.length > 1 &&
    legacyModels.every((model) => /^minimax[_-]h3(?:[_-]|$)/i.test(model))
  ) {
    return "MiniMax-H3-local";
  }
  return legacyModels[0] ?? "";
}

function buildComfyUIWorkflowRoutes(
  workflows: Record<string, Record<string, unknown>>,
): Record<string, unknown>[] {
  return Object.entries(workflows).map(([id, workflow]) => ({
    id,
    match: {},
    workflow,
  }));
}

function normalizeProviderChannelSettings(
  provider: string,
  settings: Record<string, unknown>,
): Record<string, unknown> {
  if (provider !== "comfyui") return settings;
  const comfyui =
    settings.comfyui &&
    typeof settings.comfyui === "object" &&
    !Array.isArray(settings.comfyui)
      ? (settings.comfyui as Record<string, unknown>)
      : {};
  if (Array.isArray(comfyui.workflow_routes)) return settings;
  const workflows = readComfyUIWorkflows(settings);
  const workflowIds = Object.keys(workflows);
  const isLegacyH3Group =
    workflowIds.length > 1 &&
    workflowIds.every((id) => /^minimax[_-]h3(?:[_-]|$)/i.test(id));
  if (workflowIds.length !== 1 && !isLegacyH3Group) return settings;
  const model = readComfyUIModelName(settings);
  if (!model) return settings;
  const normalized = { ...comfyui };
  delete normalized.workflow_by_model;
  delete normalized.workflow;
  normalized.model_name = model;
  normalized.workflow_routes = buildComfyUIWorkflowRoutes(workflows);
  return { ...settings, comfyui: normalized };
}

function MediaStorageSection() {
  const { t } = useTranslation();
  const configQuery = useModelGatewayConfig(true);
  const mediaRelay = configQuery.data?.data.mediaRelay;
  const mediaStorage = useSettingsStore((s) => s.mediaStorage);
  const setProvider = useSettingsStore((s) => s.setMediaStorageProvider);
  const updateCloudinary = useSettingsStore(
    (s) => s.updateCloudinaryStorageConfig,
  );
  const updateAliyunOss = useSettingsStore(
    (s) => s.updateAliyunOssStorageConfig,
  );
  const minio = useSettingsStore((s) => s.mediaStorage.minio);
  const updateMinio = useSettingsStore((s) => s.updateMinioStorageConfig);
  const saveMediaRelay = useSaveMediaRelayConfig();

  const { provider, cloudinary, aliyunOss } = mediaStorage;
  const [ttlSeconds, setTtlSeconds] = useState("1800");
  const [minioAccessKey, setMinioAccessKey] = useState("");
  const [minioSecretKey, setMinioSecretKey] = useState("");
  const mediaRelayKey = JSON.stringify(mediaRelay ?? {});
  useEffect(() => {
    if (!mediaRelay) return;
    if (
      mediaRelay.provider === "aliyun_oss" ||
      mediaRelay.provider === "cloudinary" ||
      mediaRelay.provider === "minio"
    ) {
      setProvider(mediaRelay.provider as MediaStorageProvider);
    }
    if (mediaRelay.endpoint || mediaRelay.bucket) {
      updateAliyunOss({
        endpoint: mediaRelay.endpoint || aliyunOss.endpoint,
        bucket: mediaRelay.bucket || aliyunOss.bucket,
        ...(mediaRelay.configured
          ? { accessKeyId: "", accessKeySecret: "" }
          : {}),
      });
    }
    if (mediaRelay.minioEndpoint || mediaRelay.minioPublicEndpoint) {
      updateMinio({
        endpoint: mediaRelay.minioEndpoint || minio.endpoint,
        publicEndpoint: mediaRelay.minioPublicEndpoint || minio.publicEndpoint,
        bucket: mediaRelay.minioBucket || minio.bucket,
        port: mediaRelay.minioPort ? String(mediaRelay.minioPort) : minio.port,
        useSSL: mediaRelay.minioUseSSL ?? minio.useSSL,
      });
    }
    if (mediaRelay.cloudName || mediaRelay.apiFolder) {
      updateCloudinary({
        cloudName: mediaRelay.cloudName || cloudinary.cloudName,
        apiFolder: mediaRelay.apiFolder || cloudinary.apiFolder,
        ...(mediaRelay.provider === "cloudinary" && mediaRelay.configured
          ? { apiKey: "", apiSecret: "" }
          : {}),
      });
    }
    if (mediaRelay.ttlSeconds) {
      setTtlSeconds((current) =>
        current === String(mediaRelay.ttlSeconds)
          ? current
          : String(mediaRelay.ttlSeconds),
      );
    }
    // Full AccessKey values must never be kept after the backend has a saved config.
    // Users re-enter them only when creating/updating the OSS relay credentials.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mediaRelayKey]);

  const hasConfiguredMediaRelay = Boolean(mediaRelay?.configured);
  const configuredProvider = hasConfiguredMediaRelay
    ? mediaRelay?.provider
    : provider;
  const handleSave = async () => {
    const ttl = Number(ttlSeconds.trim() || "0");
    if (!Number.isFinite(ttl) || ttl <= 0) {
      toast.error(t("settings.mediaStorage.validation.ttlSeconds"));
      return;
    }
    try {
      const res = await saveMediaRelay.mutateAsync(
        provider === "cloudinary"
          ? {
              provider: "cloudinary",
              ttlSeconds: Math.trunc(ttl),
              cloudName: cloudinary.cloudName.trim(),
              apiFolder: cloudinary.apiFolder.trim(),
              ...(cloudinary.apiKey.trim()
                ? { apiKey: cloudinary.apiKey.trim() }
                : {}),
              ...(cloudinary.apiSecret.trim()
                ? { apiSecret: cloudinary.apiSecret.trim() }
                : {}),
            }
          : provider === "minio"
            ? {
                provider: "minio",
                ttlSeconds: Math.trunc(ttl),
                endpoint: minio.endpoint.trim(),
                publicEndpoint: minio.publicEndpoint.trim(),
                port: Number(minio.port.trim() || "9000"),
                useSSL: minio.useSSL,
                bucket: minio.bucket.trim(),
                ...(minioAccessKey.trim()
                  ? { accessKeyId: minioAccessKey.trim() }
                  : {}),
                ...(minioSecretKey.trim()
                  ? { accessKeySecret: minioSecretKey.trim() }
                  : {}),
              }
            : {
              provider: "aliyun_oss",
              ttlSeconds: Math.trunc(ttl),
              endpoint: aliyunOss.endpoint.trim(),
              bucket: aliyunOss.bucket.trim(),
              ...(aliyunOss.accessKeyId.trim()
                ? { accessKeyId: aliyunOss.accessKeyId.trim() }
                : {}),
              ...(aliyunOss.accessKeySecret.trim()
                ? { accessKeySecret: aliyunOss.accessKeySecret.trim() }
                : {}),
            },
      );
      if (!res.ok) {
        toast.error(res.error);
        return;
      }
      if (provider === "cloudinary") {
        updateCloudinary({ apiKey: "", apiSecret: "" });
      } else if (provider === "minio") {
        setMinioAccessKey("");
        setMinioSecretKey("");
      } else {
        updateAliyunOss({ accessKeyId: "", accessKeySecret: "" });
      }
      toast.success(
        provider === "cloudinary"
          ? t("settings.mediaStorage.cloudinarySaveSuccess")
          : provider === "minio"
            ? t("settings.mediaStorage.minioSaveSuccess")
          : t("settings.mediaStorage.saveSuccess"),
      );
    } catch (error) {
      toast.error(
        await getRequestErrorMessage(
          error,
          t(
            provider === "minio"
              ? "settings.mediaStorage.minioSaveFailed"
              : "settings.mediaStorage.saveFailed",
          ),
        ),
      );
    }
  };

  return (
    <section className="px-5 py-5">
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "size-1.5 rounded-full",
            hasConfiguredMediaRelay ? "bg-emerald-400" : "bg-amber-400",
          )}
        />
        <h3 className="font-heading text-sm font-medium text-foreground">
          {t("settings.mediaStorage.title")}
        </h3>
        {!hasConfiguredMediaRelay ? (
          <AlertTriangle
            className="size-3.5 text-amber-400"
            aria-label={t("settings.mediaStorage.warningIconLabel")}
          />
        ) : null}
        <span className="ml-1 rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
          {t("settings.mediaStorage.currentPlan")}:{" "}
          {configuredProvider === "cloudinary"
            ? t("settings.mediaStorage.providerCloudinary")
            : configuredProvider === "minio"
              ? t("settings.mediaStorage.providerMinio")
              : t("settings.mediaStorage.providerAliyunOss")}
        </span>
      </div>

      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
        {t("settings.mediaStorage.description")}
      </p>

      <p className="mt-3 text-xs text-muted-foreground">
        {t("settings.mediaStorage.status")}:{" "}
        <span
          className={
            hasConfiguredMediaRelay ? "text-emerald-400" : "text-amber-300"
          }
        >
          {hasConfiguredMediaRelay
            ? t("settings.mediaStorage.configured")
            : t("settings.mediaStorage.notConfigured")}
        </span>
        {hasConfiguredMediaRelay && mediaRelay?.source ? (
          <span className="ml-2 text-[11px] text-muted-foreground/80">
            {t("settings.mediaStorage.source", { source: mediaRelay.source })}
          </span>
        ) : null}
      </p>
      {!hasConfiguredMediaRelay ? (
        <div className="mt-3 flex gap-2 rounded-md border border-amber-500/35 bg-amber-500/10 px-3 py-2 text-[11px] leading-relaxed text-amber-100">
          <AlertTriangle
            className="mt-0.5 size-3.5 shrink-0 text-amber-300"
            aria-hidden
          />
          <p>{t("settings.mediaStorage.notConfiguredImpact")}</p>
        </div>
      ) : null}

      <div className="mt-4 flex items-center gap-3">
        <span className="w-[64px] shrink-0 text-xs text-muted-foreground">
          {t("settings.mediaStorage.provider")}
        </span>
        <Tabs
          value={provider}
          onValueChange={(value) => setProvider(value as MediaStorageProvider)}
        >
          <TabsList>
            {MEDIA_STORAGE_PROVIDERS.map((p) => (
              <TabsTrigger key={p} value={p}>
                {p === "aliyun_oss"
                  ? t("settings.mediaStorage.providerAliyunOss")
                  : p === "minio"
                    ? t("settings.mediaStorage.providerMinio")
                    : t("settings.mediaStorage.providerCloudinary")}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      <div className="mt-4 space-y-2.5">
        {provider === "cloudinary" ? (
          <CloudinaryFields
            config={cloudinary}
            onChange={updateCloudinary}
            apiKeyPreview={mediaRelay?.cloudinaryApiKeyPreview ?? ""}
            apiSecretPreview={mediaRelay?.cloudinaryApiSecretPreview ?? ""}
          />
        ) : provider === "minio" ? (
          <MinioFields
            config={minio}
            onChange={updateMinio}
            ttlSeconds={ttlSeconds}
            onTtlSecondsChange={setTtlSeconds}
            accessKey={minioAccessKey}
            onAccessKeyChange={setMinioAccessKey}
            secretKey={minioSecretKey}
            onSecretKeyChange={setMinioSecretKey}
            accessKeyPreview={mediaRelay?.minioAccessKeyPreview ?? ""}
            secretKeyPreview={mediaRelay?.minioSecretKeyPreview ?? ""}
          />
        ) : (
          <AliyunOssFields
            config={aliyunOss}
            onChange={updateAliyunOss}
            ttlSeconds={ttlSeconds}
            onTtlSecondsChange={setTtlSeconds}
            accessKeyIdPreview={mediaRelay?.accessKeyIdPreview ?? ""}
            accessKeySecretPreview={mediaRelay?.accessKeySecretPreview ?? ""}
          />
        )}
      </div>

      <div className="mt-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            {provider === "cloudinary" ? (
              <>
                {t("settings.mediaStorage.cloudinaryFieldsHint")}{" "}
                <a
                  href="https://cloudinary.com/users/register/free"
                  target="_blank"
                  rel="noreferrer"
                  className="text-cyan-400 hover:text-cyan-300"
                >
                  {t("settings.mediaStorage.cloudinaryRegisterLink")}
                </a>
              </>
            ) : (
              t("settings.mediaStorage.fieldsHint")
            )}
          </p>
        </div>
        <Button
          type="button"
          size="sm"
          className="shrink-0"
          onClick={handleSave}
          disabled={saveMediaRelay.isPending || configQuery.isLoading}
        >
          {saveMediaRelay.isPending ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : null}
          {provider === "cloudinary"
            ? t("settings.mediaStorage.saveCloudinary")
            : provider === "minio"
              ? t("settings.mediaStorage.saveMinio")
              : t("settings.mediaStorage.save")}
        </Button>
      </div>
    </section>
  );
}

function CloudinaryFields({
  config,
  onChange,
  apiKeyPreview,
  apiSecretPreview,
}: {
  config: CloudinaryStorageConfig;
  onChange: (patch: Partial<CloudinaryStorageConfig>) => void;
  apiKeyPreview: string;
  apiSecretPreview: string;
}) {
  const { t } = useTranslation();
  return (
    <>
      <FieldRow
        label={t("settings.mediaStorage.fields.cloudName")}
        value={config.cloudName}
        onChange={(v) => onChange({ cloudName: v })}
      />
      <FieldRow
        secret
        name="cloudinary-api-key"
        label={t("settings.mediaStorage.fields.apiKey")}
        value={config.apiKey}
        onChange={(v) => onChange({ apiKey: v })}
        placeholder={apiKeyPreview || undefined}
        savedPreview={apiKeyPreview}
      />
      <FieldRow
        secret
        name="cloudinary-api-secret"
        label={t("settings.mediaStorage.fields.apiSecret")}
        value={config.apiSecret}
        onChange={(v) => onChange({ apiSecret: v })}
        placeholder={apiSecretPreview || undefined}
        savedPreview={apiSecretPreview}
      />
      <FieldRow
        label={t("settings.mediaStorage.fields.apiFolder")}
        value={config.apiFolder}
        onChange={(v) => onChange({ apiFolder: v })}
      />
    </>
  );
}

function MinioFields({
  config,
  onChange,
  ttlSeconds,
  onTtlSecondsChange,
  accessKey,
  onAccessKeyChange,
  secretKey,
  onSecretKeyChange,
  accessKeyPreview,
  secretKeyPreview,
}: {
  config: MinioStorageConfig;
  onChange: (patch: Partial<MinioStorageConfig>) => void;
  ttlSeconds: string;
  onTtlSecondsChange: (value: string) => void;
  accessKey: string;
  onAccessKeyChange: (value: string) => void;
  secretKey: string;
  onSecretKeyChange: (value: string) => void;
  accessKeyPreview: string;
  secretKeyPreview: string;
}) {
  const { t } = useTranslation();
  return (
    <>
      <FieldRow
        label={t("settings.mediaStorage.fields.minioEndpoint")}
        value={config.endpoint}
        onChange={(v) => onChange({ endpoint: v })}
      />
      <FieldRow
        label={t("settings.mediaStorage.fields.minioPublicEndpoint")}
        value={config.publicEndpoint}
        onChange={(v) => onChange({ publicEndpoint: v })}
      />
      <FieldRow
        label={t("settings.mediaStorage.fields.minioPort")}
        value={config.port}
        onChange={(v) => onChange({ port: v })}
      />
      <FieldRow
        label={t("settings.mediaStorage.fields.bucket")}
        value={config.bucket}
        onChange={(v) => onChange({ bucket: v })}
      />
      <FieldRow
        secret
        name="minio-access-key"
        label={t("settings.mediaStorage.fields.accessKeyId")}
        value={accessKey}
        onChange={onAccessKeyChange}
        placeholder={accessKeyPreview || undefined}
        savedPreview={accessKeyPreview}
      />
      <FieldRow
        secret
        name="minio-secret-key"
        label={t("settings.mediaStorage.fields.accessKeySecret")}
        value={secretKey}
        onChange={onSecretKeyChange}
        placeholder={secretKeyPreview || undefined}
        savedPreview={secretKeyPreview}
      />
      <label className="ml-[132px] flex items-center gap-2 text-xs text-muted-foreground">
        <input
          type="checkbox"
          checked={config.useSSL}
          onChange={(event) => onChange({ useSSL: event.target.checked })}
          className="size-3.5 accent-primary"
        />
        {t("settings.mediaStorage.fields.minioUseSSL")}
      </label>
      <FieldRow
        label={t("settings.mediaStorage.fields.ttlSeconds")}
        value={ttlSeconds}
        onChange={onTtlSecondsChange}
      />
      <p className="ml-[132px] text-[11px] text-muted-foreground">
        {t("settings.mediaStorage.minioHint")}
      </p>
    </>
  );
}

function AliyunOssFields({
  config,
  onChange,
  ttlSeconds,
  onTtlSecondsChange,
  accessKeyIdPreview,
  accessKeySecretPreview,
}: {
  config: AliyunOssStorageConfig;
  onChange: (patch: Partial<AliyunOssStorageConfig>) => void;
  ttlSeconds: string;
  onTtlSecondsChange: (value: string) => void;
  accessKeyIdPreview: string;
  accessKeySecretPreview: string;
}) {
  const { t } = useTranslation();
  return (
    <>
      <FieldRow
        name="aliyun-oss-access-key-id"
        label={t("settings.mediaStorage.fields.accessKeyId")}
        value={config.accessKeyId}
        onChange={(v) => onChange({ accessKeyId: v })}
        placeholder={accessKeyIdPreview || undefined}
        savedPreview={accessKeyIdPreview}
      />
      <FieldRow
        secret
        name="aliyun-oss-access-key-secret"
        label={t("settings.mediaStorage.fields.accessKeySecret")}
        value={config.accessKeySecret}
        onChange={(v) => onChange({ accessKeySecret: v })}
        placeholder={accessKeySecretPreview || undefined}
        savedPreview={accessKeySecretPreview}
      />
      <FieldRow
        label={t("settings.mediaStorage.fields.bucket")}
        value={config.bucket}
        onChange={(v) => onChange({ bucket: v })}
      />
      <FieldRow
        label={t("settings.mediaStorage.fields.endpoint")}
        value={config.endpoint}
        onChange={(v) => onChange({ endpoint: v })}
      />
      <FieldRow
        label={t("settings.mediaStorage.fields.ttlSeconds")}
        value={ttlSeconds}
        onChange={onTtlSecondsChange}
      />
    </>
  );
}

function FieldRow({
  label,
  value,
  onChange,
  secret = false,
  placeholder,
  name,
  autoComplete,
  savedPreview,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  secret?: boolean;
  placeholder?: string;
  name?: string;
  autoComplete?: string;
  savedPreview?: string;
}) {
  const { t } = useTranslation();
  const inputId = useId();
  const [revealed, setRevealed] = useState(false);
  useEffect(() => {
    if (!value) setRevealed(false);
  }, [value]);
  const hasSavedSecret = Boolean(savedPreview && !value);
  return (
    <div className="grid grid-cols-[120px_1fr] items-center gap-3">
      <Label htmlFor={inputId} className="justify-start text-[11px] font-normal tracking-wide text-muted-foreground uppercase">
        {label}
      </Label>
      <div className="relative">
        <Input
          id={inputId}
          name={name}
          autoComplete={autoComplete ?? (secret ? "new-password" : undefined)}
          type={secret && !revealed ? "password" : "text"}
          value={value}
          placeholder={
            hasSavedSecret
              ? t("settings.secretSavedPlaceholder", { preview: savedPreview })
              : placeholder
          }
          onChange={(e) => onChange(e.target.value)}
          className={cn(
            "h-9 rounded-md border-input/80 focus-visible:border-ring/70 focus-visible:ring-1 focus-visible:ring-ring/30",
            secret && value && "pr-9",
            hasSavedSecret && "pr-16",
          )}
        />
        {secret && value ? (
          <button
            type="button"
            onClick={() => setRevealed((r) => !r)}
            aria-label={
              revealed
                ? t("settings.mediaStorage.hideSecret")
                : t("settings.mediaStorage.showSecret")
            }
            className="absolute top-1/2 right-2 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
          >
            {revealed ? (
              <EyeOff className="size-4" />
            ) : (
              <Eye className="size-4" />
            )}
          </button>
        ) : hasSavedSecret ? (
          <span className="absolute top-1/2 right-2 -translate-y-1/2 rounded bg-emerald-400/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400">
            {t("settings.secretSavedBadge")}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function CodexBridgeSection() {
  const { t } = useTranslation();
  return (
    <section className="px-5 py-5">
      <div className="flex items-center gap-2">
        <span className="size-1.5 rounded-full bg-emerald-400" />
        <h3 className="font-heading text-sm font-medium text-foreground">
          {t("settings.codexBridge.title")}
        </h3>
        <span className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
          {t("settings.codexBridge.badge")}
        </span>
      </div>

      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
        {t("settings.codexBridge.description")}
      </p>

      <div className="mt-3 space-y-2 text-xs">
        <div className="flex items-center gap-3">
          <span className="w-[48px] shrink-0 text-muted-foreground">
            {t("settings.codexBridge.statusLabel")}
          </span>
          <span className="inline-flex items-center gap-1.5 text-emerald-400">
            <span className="size-1.5 rounded-full bg-emerald-400" />
            {t("settings.codexBridge.statusConnected")}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="w-[48px] shrink-0 text-muted-foreground">
            {t("settings.codexBridge.authLabel")}
          </span>
          <span className="text-foreground">
            {t("settings.codexBridge.authReady")}
          </span>
        </div>
      </div>
    </section>
  );
}
