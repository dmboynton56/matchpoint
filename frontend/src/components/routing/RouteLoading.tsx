import { LoadingIcon } from "@/components/ui/sonner"

export function RouteLoading() {
  return (
    <div className="flex min-h-svh items-center justify-center gap-2 bg-background text-xl text-muted-foreground">
      <LoadingIcon className="size-5" />
      Loading…
    </div>
  )
}
