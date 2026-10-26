import type { Metadata } from "next";
import "./globals.css";
import { USE_MOCK } from "@/lib/api";
import Nav from "@/components/Nav";

export const metadata: Metadata = {
  title: "GlitchHunter",
  description: "Reproduces concurrency bugs and validates AI-proposed fixes by rerunning the failing run.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a href="#content" className="skip">Skip to content</a>
        {USE_MOCK && (
          <div className="mockbanner">MOCK DATA: nothing on this screen came from a real run. Set NEXT_PUBLIC_USE_MOCK=false to use the live API.</div>
        )}
        <Nav />
        <main id="content">{children}</main>
      </body>
    </html>
  );
}
