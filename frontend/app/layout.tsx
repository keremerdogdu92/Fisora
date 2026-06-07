import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Fisora Private Pilot",
  description: "Mali müşavir kontrollü private pilot arayüzü",
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

