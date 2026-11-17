import { createFileRoute } from "@tanstack/react-router";
import { accountApi } from "@/lib/queries/aigcdo-account";
import { paymentReturnOrderId } from "@/lib/aigcdo-account";

export const Route = createFileRoute("/payment/result")({
  beforeLoad: async ({ abortController, location }) => ({
    accountUser: await accountApi.identity(abortController.signal),
    orderId: paymentReturnOrderId(location.searchStr),
  }),
});
