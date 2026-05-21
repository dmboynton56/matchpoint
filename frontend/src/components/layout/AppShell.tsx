import type { ReactNode } from "react"

import { AccountNav } from "@/components/layout/AccountNav"
import { SiteLogo } from "@/components/layout/SiteLogo"

type AppShellProps = {
  children: ReactNode
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="flex min-h-svh flex-col bg-background text-foreground">
      <header className="flex min-h-20 items-center justify-between gap-4 border-b border-border px-5 py-3 sm:px-8 lg:hidden">
        <SiteLogo />
        <AccountNav />
      </header>

      <div className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-1 gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,3fr)_minmax(0,1fr)] lg:gap-8 lg:px-8 lg:py-8">
        <aside aria-label="Site navigation" className="hidden min-w-0 lg:block">
          <SiteLogo className="sticky top-8" />
        </aside>

        <main className="min-w-0">{children}</main>

        <aside className="hidden min-w-0 justify-end lg:flex">
          <div className="sticky top-8">
            <AccountNav />
          </div>
        </aside>
      </div>
    </div>
  )
}
