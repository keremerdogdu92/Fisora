// File: frontend/app/portal-next/page.tsx
// Summary: Exposes the isolated next-generation accountant UI at /portal-next while preserving the existing /portal routes.

import { FisoraPortalApp } from "../portal-app";

export default function PortalNextPage() {
  return <FisoraPortalApp presentation="next" routeKey="musavir" />;
}
