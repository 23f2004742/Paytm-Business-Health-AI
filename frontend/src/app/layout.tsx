import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

import { AppDataProvider } from "@/components/providers";
import { Shell } from "@/components/shell";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Munim AI · Paytm for Business",
  description:
    "The soundbox that runs the whole dukaan. Money in, money stuck, money out, "
    + "plus your shop's health score, insights and actions, from one voice command.",
};

export const viewport: Viewport = {
  themeColor: "#ffffff",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      data-scroll-behavior="smooth"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      {/*
        suppressHydrationWarning is scoped to this element's own attributes, so
        it silences the attributes browser extensions inject into <body> before
        React hydrates (Grammarly adds data-gr-ext-installed, for example)
        without hiding genuine mismatches anywhere inside the tree.
      */}
      <body className="min-h-full" suppressHydrationWarning>
        <AppDataProvider>
          <Shell>{children}</Shell>
        </AppDataProvider>
      </body>
    </html>
  );
}
