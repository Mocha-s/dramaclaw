import { createLazyFileRoute } from "@tanstack/react-router";
import { AigcdoPaymentResult } from "@/components/aigcdo/account-page";

export const Route = createLazyFileRoute("/payment/result")({ component: PaymentResultRoute });

function PaymentResultRoute() {
  const { accountUser, orderId } = Route.useRouteContext();
  return <AigcdoPaymentResult userId={accountUser.id} orderId={orderId} />;
}
