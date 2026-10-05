import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";

export const metadata: Metadata = {
  title: "NeuroForge AI — Evidence-grounded document intelligence",
  description: "Multimodal document intelligence and decision automation. Every important AI conclusion is traceable to evidence.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-ink font-sans text-paper antialiased">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
