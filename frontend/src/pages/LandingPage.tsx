import UploadDropzone from "@/components/user/UploadDropzone"
import Header from "@/components/layout/Header"
export function LandingPage() {
  return (
    <main className="flex min-h-svh flex-col bg-background text-foreground">
      <Header />
      <section
        className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-14 px-5 py-10 pb-20 lg:flex-row lg:items-center lg:gap-16 lg:py-14 xl:gap-24"
        aria-labelledby="landing-hero-heading"
      >
        <div className="max-w-xl flex-1 lg:max-w-none lg:flex-[1.05]">
          <p className="text-xs font-semibold tracking-[0.22em] text-primary uppercase">
            AI job search
          </p>
          <h1
            id="landing-hero-heading"
            className="mt-4 font-heading text-4xl leading-[1.05] font-bold tracking-tight text-foreground uppercase sm:text-5xl lg:text-6xl xl:text-[3.35rem]"
          >
            Find your perfect jobs
          </h1>
          <p className="mt-6 max-w-lg text-lg leading-relaxed text-muted-foreground sm:text-xl">
            Upload once. MatchPoint reads your resume, pulls intent and skills,
            and surfaces roles worth your time.
          </p>
        </div>

        <div className="flex w-full flex-1 justify-center lg:max-w-none lg:justify-end xl:flex-[0.85]">
          <UploadDropzone />
        </div>
      </section>
    </main>
  )
}
