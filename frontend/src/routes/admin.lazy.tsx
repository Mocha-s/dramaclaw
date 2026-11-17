import { createLazyFileRoute } from "@tanstack/react-router";
import { AigcdoAdminPage } from "@/components/aigcdo/admin-page";

export const Route = createLazyFileRoute("/admin")({ component: AigcdoAdminPage });
