import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import ky from "ky";
import i18n from "i18next";
import { server } from "@/__mocks__/msw/server";
import { AigcdoLoginForm } from "@/components/aigcdo/login-form";
import { useAuthStore } from "@/stores/auth-store";
import zh from "../../../../public/locales/zh/account.json";

vi.mock("@/lib/api", () => ({
  api: ky.create({ baseUrl: "http://localhost:3000/", credentials: "include" }),
}));

const config = {
  auth_provider: "aigcdo", phone_otp_entry_visible: false,
  registration_enabled: true, registration_supported: true, login_supported: true,
  login_agreement_enabled: true, login_agreement_revision: "v1",
  login_agreement_documents: [{ id: "terms", title: "服务条款", content_md: "<script>secretScript()</script>条款内容" }],
};
const user = { id: "alice", username: "aigcdo_alice", role: "user", application: { status: "ready", group_id: 41 } };
const ok = (data: unknown, status = 200) => HttpResponse.json({ ok: true, data }, { status });
const enter = vi.fn();

function mount() {
  const client = new QueryClient({ defaultOptions: {
    queries: { retry: 1, staleTime: 30000, refetchOnWindowFocus: false },
  } });
  return { client, ...render(<QueryClientProvider client={client}><AigcdoLoginForm onReady={enter} /></QueryClientProvider>) };
}
async function fill() {
  fireEvent.change(await screen.findByLabelText("邮箱"), { target: { value: "alice@example.test" } });
  fireEvent.change(screen.getByLabelText("密码"), { target: { value: "test-password" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "我已阅读并同意以上协议" }));
}

beforeEach(() => {
  enter.mockReset();
  useAuthStore.getState().reset();
  i18n.addResourceBundle("zh", "account", zh, true, true);
  server.use(
    http.get("*/api/v1/auth/ui-config", () => ok(config)),
    http.get("*/api/v1/auth/me", () => ok(user)),
    http.post("*/api/v1/auth/login", () => ok(user)),
  );
});
afterEach(cleanup);

describe("AIGCDO registration and login", () => {
  it("requires agreement and renders gateway documents as inert text", async () => {
    mount();
    await screen.findByLabelText("邮箱");
    expect(screen.getByRole("button", { name: "登录" })).toBeDisabled();
    expect(screen.getByText(/secretScript/).tagName).not.toBe("SCRIPT");
    expect(document.querySelector("script")).toBeNull();
    await fill();
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    await waitFor(() => expect(enter).toHaveBeenCalledOnce());
  });

  it("does not authenticate a 202 challenge and submits only the second factor", async () => {
    server.use(
      http.post("*/api/v1/auth/login", () => ok({ requires_2fa: true }, 202)),
      http.post("*/api/v1/auth/login/2fa", async ({ request }) => {
        expect(await request.json()).toEqual({ code: "123456" });
        return ok(user);
      }),
    );
    mount(); await fill();
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    fireEvent.change(await screen.findByLabelText("两步验证码"), { target: { value: "123456" } });
    expect(enter).not.toHaveBeenCalled();
    expect(useAuthStore.getState().username).toBeNull();
    expect(screen.queryByLabelText("密码")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "验证并登录" }));
    await waitFor(() => expect(enter).toHaveBeenCalledOnce());
  });

  it("preserves successful registration when application provisioning is pending", async () => {
    let registrations = 0;
    server.use(
      http.post("*/api/v1/auth/register", async ({ request }) => {
        registrations++;
        expect(await request.json()).toEqual({ email: "alice@example.test", password: "test-password" });
        return ok({ ...user, application: { status: "pending", code: "gateway_unavailable" } });
      }),
      http.post("*/api/v1/auth/application", ({ request }) => {
        expect(request.headers.get("X-AIGCDO-User-ID")).toBe("alice");
        return ok({ status: "ready", group_id: 41 });
      }),
    );
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "注册账号" }));
    await fill();
    fireEvent.click(screen.getByRole("button", { name: "创建账号" }));
    await screen.findByText("账号已登录，模型服务尚在开通。请重试开通，无需重新注册。");
    expect(enter).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "返回账户" })).toHaveAttribute("href", "/account");
    fireEvent.click(screen.getByRole("button", { name: "重试开通" }));
    await waitFor(() => expect(enter).toHaveBeenCalledOnce());
    expect(registrations).toBe(1);
  });

  it.each([
    { registration_enabled: false },
    { registration_supported: false },
  ])("does not offer unavailable registration: %j", async (change) => {
    server.use(http.get("*/api/v1/auth/ui-config", () => ok({ ...config, ...change })));
    mount();
    await screen.findByLabelText("邮箱");
    expect(screen.queryByRole("button", { name: "注册账号" })).not.toBeInTheDocument();
  });

  it("fails closed on missing configuration", async () => {
    server.use(http.get("*/api/v1/auth/ui-config", () => HttpResponse.json({ ok: false }, { status: 503 })));
    mount();
    await screen.findByText("登录配置暂不可用，请刷新重试。");
    expect(screen.queryByLabelText("密码")).not.toBeInTheDocument();
  });

  it("does not echo upstream errors or automatically retry registration", async () => {
    let posts = 0;
    server.use(http.post("*/api/v1/auth/register", () => {
      posts++;
      return HttpResponse.json({ ok: false, code: "gateway_unavailable", error: "private-upstream-body" }, { status: 503 });
    }));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "注册账号" }));
    await fill();
    fireEvent.click(screen.getByRole("button", { name: "创建账号" }));
    await screen.findByText("注册结果未确认，请先尝试登录；不要重复创建账号。");
    expect(posts).toBe(1);
    expect(screen.queryByText(/private-upstream/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "创建账号" })).not.toBeInTheDocument();
  });

  it("does not recover another account's application after cookie changes", async () => {
    let posts = 0;
    server.use(
      http.post("*/api/v1/auth/login", () => ok({ ...user, application: { status: "pending" } })),
      http.get("*/api/v1/auth/me", () => ok({ ...user, id: "bob" })),
      http.post("*/api/v1/auth/application", () => { posts++; return ok({ status: "ready" }); }),
    );
    mount(); await fill();
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    fireEvent.click(await screen.findByRole("button", { name: "重试开通" }));
    await screen.findByText("登录账号已变化，请重新登录。");
    expect(posts).toBe(0);
    expect(enter).not.toHaveBeenCalled();
  });

  it("does not complete login after unmount", async () => {
    let release!: () => void;
    let started!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const begin = new Promise<void>((resolve) => { started = resolve; });
    server.use(http.post("*/api/v1/auth/login", async () => { started(); await gate; return ok(user); }));
    const view = mount(); await fill();
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    await begin;
    view.unmount();
    await act(async () => { release(); await gate; });
    expect(enter).not.toHaveBeenCalled();
  });

  it("requires renewed agreement after a configuration revision changes", async () => {
    const view = mount(); await fill();
    expect(screen.getByRole("button", { name: "登录" })).not.toBeDisabled();
    server.use(http.get("*/api/v1/auth/ui-config", () => ok({ ...config, login_agreement_revision: "v2" })));
    await act(async () => { await view.client.invalidateQueries({ queryKey: ["aigcdo-auth-ui"] }); });
    await waitFor(() => expect(screen.getByRole("button", { name: "登录" })).toBeDisabled());
    expect(screen.getByRole("checkbox", { name: "我已阅读并同意以上协议" })).not.toBeChecked();
  });

  it("refreshes agreements on focus despite production's disabled global focus refresh", async () => {
    mount(); await fill();
    act(() => focusManager.setFocused(false));
    server.use(http.get("*/api/v1/auth/ui-config", () => ok({ ...config, login_agreement_revision: "v2" })));
    try {
      act(() => focusManager.setFocused(true));
      await waitFor(() => expect(screen.getByRole("button", { name: "登录" })).toBeDisabled());
      expect(screen.getByRole("checkbox", { name: "我已阅读并同意以上协议" })).not.toBeChecked();
    } finally {
      act(() => focusManager.setFocused(undefined));
    }
  });

  it.each(["revision", "prerequisite", "unavailable"])("rechecks %s before sending registration", async (change) => {
    let posts = 0;
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "注册账号" }));
    await fill();
    server.use(
      http.get("*/api/v1/auth/ui-config", () => change === "unavailable"
        ? HttpResponse.json({ ok: false }, { status: 503 })
        : ok({ ...config, ...(change === "revision"
          ? { login_agreement_revision: "v2" } : { registration_supported: false }) })),
      http.post("*/api/v1/auth/register", () => { posts++; return ok(user); }),
    );
    fireEvent.click(screen.getByRole("button", { name: "创建账号" }));
    await screen.findByRole("alert");
    expect(posts).toBe(0);
    expect(enter).not.toHaveBeenCalled();
  });

  it("submits only once while the first login is in flight", async () => {
    let count = 0;
    let release!: () => void;
    let started!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const begin = new Promise<void>((resolve) => { started = resolve; });
    server.use(http.post("*/api/v1/auth/login", async () => {
      count++; started(); await gate; return ok(user);
    }));
    mount(); await fill();
    const form = screen.getByRole("button", { name: "登录" }).closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    await begin;
    await act(async () => { release(); await gate; });
    await waitFor(() => expect(enter).toHaveBeenCalledOnce());
    expect(count).toBe(1);
  });
});

describe("AIGCDO human check", () => {
  it("waits for the Turnstile proof, sends it once, and asks for a new one per attempt", async () => {
    const rendered: Array<{ callback: (token: string) => void }> = [];
    (window as unknown as { turnstile: unknown }).turnstile = {
      render: (_: HTMLElement, options: { callback: (token: string) => void }) => { rendered.push(options); return "w"; },
      remove: vi.fn(),
    };
    const append = vi.spyOn(document.head, "append").mockImplementation((node) => {
      queueMicrotask(() => (node as HTMLScriptElement).onload?.(new Event("load")));
    });
    const bodies: unknown[] = [];
    server.use(
      http.get("*/api/v1/auth/ui-config", () => ok({ ...config, turnstile_site_key: "0x4AAAtest" })),
      http.post("*/api/v1/auth/login", async ({ request }) => {
        bodies.push(await request.json());
        return bodies.length === 1 ? HttpResponse.json({ ok: false }, { status: 400 }) : ok(user);
      }),
    );
    try {
      mount();
      await fill();
      const submit = screen.getByRole("button", { name: "登录" });
      await waitFor(() => expect(rendered).toHaveLength(1));
      expect(submit).toBeDisabled();
      act(() => rendered[0].callback("proof-1"));
      fireEvent.click(submit);
      await waitFor(() => expect(rendered).toHaveLength(2));
      expect(submit).toBeDisabled();
      fireEvent.change(screen.getByLabelText("密码"), { target: { value: "test-password" } });
      act(() => rendered[1].callback("proof-2"));
      fireEvent.click(submit);
      await waitFor(() => expect(enter).toHaveBeenCalledOnce());
      expect(bodies.map((body) => (body as { turnstile_token: string }).turnstile_token)).toEqual(["proof-1", "proof-2"]);
    } finally {
      append.mockRestore();
      delete (window as unknown as { turnstile?: unknown }).turnstile;
    }
  });
});
