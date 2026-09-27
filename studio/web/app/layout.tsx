import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Suspense } from "react";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { AuthGate } from "@/components/AuthGate";
import { ToastProvider } from "@/components/Toasts";

export const metadata: Metadata = {
  title: "CLOUD VIDEO",
  description: "Private AI video editing workspace powered by video-use",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#0a0a0b", colorScheme: "dark" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body>
        <ToastProvider>
          <AuthGate>
            <div className="shell">
              <Suspense fallback={<aside className="sidebar" />}>
                <Sidebar />
              </Suspense>
              <main className="content">
                <Suspense fallback={<div className="center-screen"><div className="spinner" /></div>}>
                  {children}
                </Suspense>
              </main>
            </div>
          </AuthGate>
        </ToastProvider>
      </body>
    </html>
  );
}
