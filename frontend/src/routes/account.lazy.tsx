import { createLazyFileRoute } from "@tanstack/react-router";
import { AigcdoAccountPage } from "@/components/aigcdo/account-page";

export const Route = createLazyFileRoute("/account")({ component: AccountRoute });

function AccountRoute() {
  const { accountUser } = Route.useRouteContext();
  return <AigcdoAccountPage userId={accountUser.id} />;
}
