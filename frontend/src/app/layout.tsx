import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { PrefsSync } from "@/components/shell/PrefsSync";
import { Providers } from "@/components/shell/Providers";
import { PREFS_SCRIPT } from "@/lib/prefsScript";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Translate",
  description: "Upload a document, get a reviewed translation, refine it by chatting.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // suppressHydrationWarning: the inline script sets data-theme / data-sidebar before React hydrates.
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: PREFS_SCRIPT }} />
      </head>
      {/* suppressHydrationWarning: browser extensions (Grammarly, password managers, ColorZilla…) add attributes to
          <body> before React hydrates; this only quiets that element's attributes, not mismatches anywhere else. */}
      <body className="h-full font-sans" suppressHydrationWarning>
        <PrefsSync />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
