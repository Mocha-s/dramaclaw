import { z } from "zod";
import { request } from "./aigcdo-account";

const session = z.object({ username: z.string() });
const credits = z.object({ credits_per_usd: z.string(), decimals: z.number().int().min(0).max(8) });
const announcement = z.object({
  id: z.string(), title: z.string(), body: z.string(), pinned: z.boolean(), published_at: z.string(),
});
export type AdminAnnouncement = z.infer<typeof announcement>;
const saved = z.unknown();

export const adminApi = {
  session: (signal?: AbortSignal) => request("api/v1/admin/session", session, { signal }),
  login: (username: string, password: string) =>
    request("api/v1/auth/admin/login", session, { json: { username, password } }),
  logout: () => request("api/v1/auth/admin/logout", saved, { json: {} }),
  credits: (signal?: AbortSignal) => request("api/v1/admin/credits", credits, { signal }),
  saveCredits: (value: z.infer<typeof credits>) => request("api/v1/admin/credits", saved, { json: value }),
  announcements: (signal?: AbortSignal) =>
    request("api/v1/admin/announcements", z.object({ items: z.array(announcement) }), { signal }),
  saveAnnouncements: (items: AdminAnnouncement[]) =>
    request("api/v1/admin/announcements", saved, { json: { items } }),
};
