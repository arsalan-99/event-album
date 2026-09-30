import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Event Album",
  description: "Private face matching photo delivery.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <header className="navbar">
          <Link href="/events" className="brand">
            <span className="brand-dot"></span>
            <span>Event Album</span>
          </Link>
          <nav className="nav-links">
            <Link href="/events" className="nav-link">
              All Events
            </Link>
            <Link href="/events/new" className="btn btn-secondary btn-sm">
              + New Event
            </Link>
          </nav>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
