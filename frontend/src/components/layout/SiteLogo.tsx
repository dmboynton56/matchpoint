import { Link } from "react-router-dom"

type SiteLogoProps = {
  className?: string
}

export function SiteLogo({ className }: SiteLogoProps) {
  return (
    <Link to="/" className={className ?? "inline-flex items-center text-foreground"}>
      <img
        src="/matchpoint-logo.png"
        alt="MatchPoint"
        className="h-[4.5rem] w-auto"
        width={360}
        height={72}
        decoding="async"
      />
    </Link>
  )
}
