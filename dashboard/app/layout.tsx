import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { USE_MOCK } from "@/lib/api";

export const metadata: Metadata = {
  title: "GlitchHunter",
  description: "Reproduces concurrency bugs and validates AI-proposed fixes by rerunning the failing run.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        {USE_MOCK && (
          <div className="mockbanner">MOCK DATA: nothing on this screen came from a real run. Set NEXT_PUBLIC_USE_MOCK=false to use the live API.</div>
        )}
        <header className="topbar">
          <div className="topbar-in">
            <Link href="/" className="brand">Glitch<span>Hunter</span></Link>
          </div>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
