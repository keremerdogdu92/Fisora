// File: frontend/app/portal-next/layout.tsx
// Summary: Loads route-scoped next-generation Fisora presentation styles without changing the existing portal route tree.

import "./portal-next.css";
import "./portal-next-upload.css";

export default function PortalNextLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children;
}
