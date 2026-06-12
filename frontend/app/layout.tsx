import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Fisora Operasyon Portalı",
  description: "Mali müşavir kontrollü muhasebe otomasyon çalışma alanı",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="tr">
      <body>{children}</body>
    </html>
  );
}

