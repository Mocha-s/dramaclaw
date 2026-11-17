import { z } from "zod";
import { AccountApiError, accountApi, accountIdentitySchema, request } from "./aigcdo-account";

export const authUiSchema = z.object({
  auth_provider: z.literal("aigcdo"),
  registration_enabled: z.boolean(),
  registration_supported: z.boolean(),
  login_supported: z.boolean(),
  // Cloudflare Turnstile site key; empty when the gateway asks for no human check.
  turnstile_site_key: z.string().max(128).regex(/^[A-Za-z0-9_-]*$/).default(""),
  login_agreement_enabled: z.boolean(),
  login_agreement_revision: z.string().max(256),
  login_agreement_documents: z.array(z.object({
    id: z.string().min(1).max(128), title: z.string().min(1).max(256),
    content_md: z.string().min(1).max(131072),
  })).max(10),
}).refine((data) => !data.login_agreement_enabled ||
  (data.login_agreement_revision.length > 0 && data.login_agreement_documents.length > 0));
const applicationSchema = z.object({
  status: z.enum(["ready", "pending", "blocked"]),
});
const authenticatedSchema = accountIdentitySchema.extend({
  application: applicationSchema.optional(),
});
const loginSchema = z.union([
  z.object({ requires_2fa: z.literal(true) }),
  authenticatedSchema,
]);
export type AuthenticatedAccount = z.infer<typeof authenticatedSchema>;

export const aigcdoAuthApi = {
  config: (signal?: AbortSignal) => request("api/v1/auth/ui-config", authUiSchema, { signal }),
  login: (username: string, password: string, signal?: AbortSignal, turnstile = "") =>
    request("api/v1/auth/login", loginSchema, {
      json: { username, password, ...(turnstile ? { turnstile_token: turnstile } : {}) }, signal,
    }),
  register: (email: string, password: string, signal?: AbortSignal, turnstile = "") =>
    request("api/v1/auth/register", authenticatedSchema, {
      json: { email, password, ...(turnstile ? { turnstile_token: turnstile } : {}) }, signal,
    }),
  secondFactor: (code: string, signal?: AbortSignal) =>
    request("api/v1/auth/login/2fa", authenticatedSchema, { json: { code }, signal }),
  application: async (userId: string, signal?: AbortSignal) => {
    const user = await accountApi.identity(signal);
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    if (user.id !== userId) throw new AccountApiError("session_changed", 409);
    return request("api/v1/auth/application", applicationSchema, {
      json: {}, signal, expectedUserId: userId,
    });
  },
};
