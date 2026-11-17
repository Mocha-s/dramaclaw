import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SettingsDialog } from "@/components/settings/settings-dialog";
import { setAdminSession } from "@/lib/runtime-config";
import { adminApi } from "@/lib/queries/aigcdo-admin";

const panel = "rounded-lg border border-border bg-card p-5 text-card-foreground";
const options = { retry: false as const, staleTime: 0, gcTime: 0 };

export function AigcdoAdminPage() {
  const { t } = useTranslation("account");
  const session = useQuery({ queryKey: ["aigcdo-admin", "session"], queryFn: ({ signal }) => adminApi.session(signal), ...options });
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [open, setOpen] = useState(true);
  const login = useMutation({
    mutationFn: () => adminApi.login(username, password),
    onSuccess: () => { setPassword(""); void session.refetch(); },
  });
  const signedIn = Boolean(session.data);
  setAdminSession(signedIn);
  return <main id="main-content" tabIndex={-1} className="flex h-dvh items-center justify-center bg-background p-4 text-foreground">
    {session.isPending ? <p role="status">{t("loading")}</p> : signedIn ? <section className={`${panel} flex w-full max-w-sm flex-col gap-3`}>
      <h1 className="text-xl font-semibold">{t("admin.heading")}</h1>
      <p className="text-sm text-muted-foreground">{t("admin.signedInAs", { username: session.data?.username })}</p>
      <Button onClick={() => setOpen(true)}>{t("admin.openSettings")}</Button>
      <Button variant="outline" onClick={() => void adminApi.logout().finally(() => { setAdminSession(false); void session.refetch(); })}>
        {t("admin.signOut")}
      </Button>
      <SettingsDialog open={open} onOpenChange={setOpen} />
    </section> : <form className={`${panel} flex w-full max-w-sm flex-col gap-3 text-sm`}
      onSubmit={(event) => { event.preventDefault(); login.mutate(); }}>
      <h1 className="text-xl font-semibold">{t("admin.heading")}</h1>
      <label htmlFor="admin-username">{t("admin.username")}</label>
      <Input id="admin-username" autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} />
      <label htmlFor="admin-password">{t("auth.password")}</label>
      <Input id="admin-password" type="password" autoComplete="current-password" required value={password}
        onChange={(e) => setPassword(e.target.value)} />
      <Button type="submit" disabled={login.isPending}>{t("auth.signIn")}</Button>
      {login.isError ? <p role="alert">{t("admin.loginFailed")}</p> : null}
    </form>}
  </main>;
}
