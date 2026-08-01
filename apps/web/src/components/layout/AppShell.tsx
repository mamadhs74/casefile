import type { ReactNode } from 'react';
import { NavLink } from 'react-router';

const NAV_ITEMS = [
  { to: '/cases', label: 'Cases' },
  { to: '/studio', label: 'Studio' },
  { to: '/publishing', label: 'Publishing' },
  { to: '/analytics', label: 'Analytics' },
];

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-svh flex-col md:flex-row">
      <header className="flex shrink-0 flex-col border-b border-ink/10 bg-paper-raised md:h-svh md:w-56 md:border-b-0 md:border-r">
        <div className="px-5 py-5">
          <span className="font-sans text-lg font-semibold tracking-tight text-ink">
            casefile
          </span>
        </div>
        <nav className="flex flex-1 flex-row gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:overflow-visible">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `shrink-0 rounded-md px-3 py-2 font-sans text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-ledger-blue/12 text-ledger-blue'
                    : 'text-ink-muted hover:bg-paper hover:text-ink'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="min-w-0 flex-1 px-4 py-6 md:px-8 md:py-8">{children}</main>
    </div>
  );
}
