import "./globals.css";

export const metadata = {
  title: "GlitchHunter Dashboard",
  description: "Find, reproduce, and validate concurrency bugs.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
