import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { adminApi, type AdminAnnouncement } from "@/lib/queries/aigcdo-admin";

const panel = "rounded-lg border border-border bg-card p-5 text-card-foreground";
const options = { retry: false as const, staleTime: 0, gcTime: 0 };

/** Credit ratio: how many credits one USD of gateway balance is shown as. */
export function AdminCreditsSection() {
  const { t } = useTranslation("account");
  const query = useQuery({ queryKey: ["aigcdo-admin", "credits"], queryFn: ({ signal }) => adminApi.credits(signal), ...options });
  const [draft, setDraft] = useState<{ ratio: string; decimals: string } | null>(null);
  const save = useMutation({ mutationFn: adminApi.saveCredits, onSuccess: () => { setDraft(null); void query.refetch(); } });
  if (!query.data) return <p className="p-5 text-sm">{t(query.isError ? "loadError" : "loading")}</p>;
  const ratio = draft?.ratio ?? query.data.credits_per_usd;
  const decimals = draft?.decimals ?? String(query.data.decimals);
  return <form className="flex max-w-md flex-col gap-3 p-5 text-sm" onSubmit={(event) => {
    event.preventDefault(); save.mutate({ credits_per_usd: ratio, decimals: Number(decimals) });
  }}>
    <h3 className="text-base font-semibold">{t("admin.credits")}</h3>
    <p className="text-muted-foreground">{t("admin.creditsHint")}</p>
    <label htmlFor="admin-ratio">{t("admin.ratio")}</label>
    <Input id="admin-ratio" inputMode="decimal" value={ratio} onChange={(e) => setDraft({ ratio: e.target.value, decimals })} />
    <label htmlFor="admin-decimals">{t("admin.decimals")}</label>
    <Input id="admin-decimals" inputMode="numeric" value={decimals} onChange={(e) => setDraft({ ratio, decimals: e.target.value })} />
    <Button type="submit" disabled={save.isPending || !draft}>{t("admin.save")}</Button>
    {save.isError ? <p role="alert">{t("admin.saveError")}</p> : save.isSuccess ? <p role="status">{t("admin.saved")}</p> : null}
  </form>;
}

export function AdminAnnouncementsSection() {
  const { t } = useTranslation("account");
  const query = useQuery({ queryKey: ["aigcdo-admin", "announcements"], queryFn: ({ signal }) => adminApi.announcements(signal), ...options });
  const [draft, setDraft] = useState<AdminAnnouncement[] | null>(null);
  const save = useMutation({ mutationFn: adminApi.saveAnnouncements, onSuccess: () => { setDraft(null); void query.refetch(); } });
  if (!query.data) return <p className="p-5 text-sm">{t(query.isError ? "loadError" : "loading")}</p>;
  const items = draft ?? query.data.items;
  const change = (index: number, patch: Partial<AdminAnnouncement>) =>
    setDraft(items.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  return <div className="flex flex-col gap-3 p-5 text-sm">
    <h3 className="text-base font-semibold">{t("admin.announcements")}</h3>
    {items.length === 0 ? <p className="text-muted-foreground">{t("admin.noAnnouncements")}</p> : null}
    {items.map((item, index) => <div key={item.id} className={`${panel} flex flex-col gap-2`}>
      <Input aria-label={t("admin.title")} placeholder={t("admin.title")} maxLength={200} value={item.title}
        onChange={(e) => change(index, { title: e.target.value })} />
      <Textarea aria-label={t("admin.body")} placeholder={t("admin.body")} maxLength={5000} rows={3} value={item.body}
        onChange={(e) => change(index, { body: e.target.value })} />
      <div className="flex items-center justify-between gap-2">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={item.pinned} onChange={(e) => change(index, { pinned: e.target.checked })} />
          {t("admin.pinned")}
        </label>
        <Button type="button" variant="outline" onClick={() => setDraft(items.filter((_, i) => i !== index))}>{t("admin.remove")}</Button>
      </div>
    </div>)}
    <div className="flex gap-2">
      <Button type="button" variant="outline" onClick={() => setDraft([{
        id: `a${Date.now().toString(36)}`, title: "", body: "", pinned: false, published_at: new Date().toISOString(),
      }, ...items])}>{t("admin.add")}</Button>
      <Button type="button" disabled={save.isPending || !draft || items.some((item) => !item.title.trim() || !item.body.trim())}
        onClick={() => save.mutate(items)}>{t("admin.save")}</Button>
    </div>
    {save.isError ? <p role="alert">{t("admin.saveError")}</p> : save.isSuccess ? <p role="status">{t("admin.saved")}</p> : null}
  </div>;
}

