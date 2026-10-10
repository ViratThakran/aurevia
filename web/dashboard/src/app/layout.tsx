import type { Metadata } from "next";
import "./globals.css";
import { ACCENT_BOOT_SCRIPT } from "@/lib/accent";
import { SessionProvider } from "@/lib/session";

export const metadata: Metadata = {
  title: "Aurevia",
  description: "AI voice sales agents",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: ACCENT_BOOT_SCRIPT }} />
      </head>
      <body className="antialiased">
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
