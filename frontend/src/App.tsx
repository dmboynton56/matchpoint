import { Landing } from "@/components/landing/Landing"

export function App() {
  return (
    <main className="flex min-h-svh flex-col bg-background text-foreground">
      <header className="flex min-h-24 items-center px-5 py-3 sm:px-8">
        <a href="/" className="inline-flex items-center gap-2.5 text-foreground">
          <img
            src="/matchpoint-logo.png"
            alt="MatchPoint"
            className="h-[4.5rem] w-auto"
            width={360}
            height={72}
            decoding="async"
          />
        </a>
      </header>

      <Landing />
    </main>
  )
}

export default App
