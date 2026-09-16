// File: frontend/app/portal-next/page.tsx
// Summary: Exposes /portal-next as the canonical accountant shell while client, invite, and password-reset flows remain separate.

import { FisoraPortalApp } from "../portal-app";

export default function PortalNextPage() {
  return <FisoraPortalApp presentation="next" routeKey="musavir" />;
}
