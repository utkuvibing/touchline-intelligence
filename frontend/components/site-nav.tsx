"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", label: "Overview" },
  { href: "/model", label: "Model" },
  { href: "/explore", label: "Explore" },
  { href: "/methodology", label: "Methodology" },
] as const;

export function SiteNav() {
  const pathname = usePathname();

  return (
    <header className="site-nav">
      <nav className="site-shell site-nav-inner" aria-label="Primary">
        <Link href="/" className="wordmark">
          Touchline<span className="wordmark-accent">.</span>
          <span className="wordmark-tail"> Intelligence</span>
        </Link>
        <div className="nav-links">
          {NAV_ITEMS.map((item) => {
            const active =
              item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
              >
                {item.label}
              </Link>
            );
          })}
        </div>
      </nav>
    </header>
  );
}
