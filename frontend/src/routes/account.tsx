import { createFileRoute } from "@tanstack/react-router";
import { accountApi } from "@/lib/queries/aigcdo-account";

export const Route = createFileRoute("/account")({
  beforeLoad: async ({ abortController }) => ({
    accountUser: await accountApi.identity(abortController.signal),
  }),
});
