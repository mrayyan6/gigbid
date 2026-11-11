"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { clearSession, getToken, getUser, type StoredUser } from "@/lib/auth";
import { MarketplaceBanner } from "./MarketplaceBanner";

const NAV = [
  { href: "/inbox", label: "Inbox" },
  { href: "/pipeline", label: "Pipeline" },
  { href: "/messages", label: "Messages" },
  { href: "/analytics", label: "Analytics" },
  { href: "/settings", label: "Settings" },
];

const PUBLIC_PATHS = ["/login"];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<StoredUser | null>(null);
  const [open, setOpen] = useState(false);
  const isPublic = PUBLIC_PATHS.includes(pathname);

  useEffect(() => {
    const token = getToken();
    setUser(getUser());
    if (!token && !isPublic) {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [pathname, isPublic, router]);

  useEffect(() => setOpen(false), [pathname]);

  function logout() {
    clearSession();
    setUser(null);
    router.replace("/login");
  }

  if (isPublic) {
    return (
      <>
        <MarketplaceBanner />
        <main id="main" className="mx-auto w-full max-w-md px-4 py-10">
          {children}
        </main>
      </>
    );
  }

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <MarketplaceBanner />
      <header className="flex items-center justify-between gap-2 border-b border-slate-200 bg-white px-4 py-2 md:hidden">
        <Link href="/inbox" className="font-semibold text-indigo-700">
          GigBid
        </Link>
        <button
          type="button"
          className="btn"
          aria-expanded={open}
          aria-controls="primary-nav"
          onClick={() => setOpen((o) => !o)}
        >
          {open ? "Close menu" : "Menu"}
        </button>
      </header>
      <div className="flex flex-1 flex-col md:flex-row">
        <nav
          id="primary-nav"
          aria-label="Primary"
          className={`${open ? "block" : "hidden"} border-b border-slate-200 bg-white p-3 md:block md:w-56 md:shrink-0 md:border-b-0 md:border-r`}
        >
          <Link href="/inbox" className="mb-4 hidden px-2 text-lg font-semibold text-indigo-700 md:block">
            GigBid
          </Link>
          <ul className="flex flex-col gap-1">
            {NAV.map((n) => {
              const active = pathname === n.href || pathname.startsWith(n.href + "/");
              return (
                <li key={n.href}>
                  <Link
                    href={n.href}
                    aria-current={active ? "page" : undefined}
                    className={`block rounded-md px-3 py-2 text-sm font-medium ${
                      active ? "bg-indigo-50 text-indigo-700" : "text-slate-700 hover:bg-slate-100"
                    }`}
                  >
                    {n.label}
                  </Link>
                </li>
              );
            })}
          </ul>
          <div className="mt-4 border-t border-slate-200 pt-3 text-xs text-slate-500">
            {user && (
              <>
                <p className="truncate" title={user.email}>
                  {user.email}
                </p>
                <p>Persona: {user.persona}</p>
              </>
            )}
            <button type="button" className="btn mt-2 w-full" onClick={logout}>
              Sign out
            </button>
          </div>
        </nav>
        <main id="main" className="min-w-0 flex-1 p-4 md:p-6">
          {ready ? children : null}
        </main>
      </div>
    </div>
  );
}
