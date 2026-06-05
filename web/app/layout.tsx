import type { Metadata } from "next";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { RunHydrator } from "@/components/run-hydrator";

export const metadata: Metadata = {
  title: "Founding Team Analyzer",
  description:
    "Multi-agent founding team analysis. Score a founding team in 90 seconds.",
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <ThemeProvider>
          <RunHydrator />
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
