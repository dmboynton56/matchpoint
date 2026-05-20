import { Landing } from "@/components/landing/Landing"
import { SiteLogo } from "@/components/layout/SiteLogo"

export function LandingPage() {
  return (
    <main className="flex min-h-svh flex-col bg-background text-foreground">
      <header className="flex min-h-24 items-center px-5 py-3 sm:px-8">
        <SiteLogo />
      </header>
      <Landing />
    </main>
  )
}
