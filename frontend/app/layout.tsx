import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Muhasebe Operasyon Otomasyonu",
  description: "Faz 0 dogrulama arayuzu",
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

