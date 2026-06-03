import { Button } from "@/components/ui/button"
import { AccountNav } from "@/components/layout/AccountNav"
import { SignupLoginDialog } from "@/components/user/SignupLoginCard"
import { useAuth } from "@/hooks/useAuth"
import { SiteLogo } from "./SiteLogo"

const Header = () => {
  const { user, loading } = useAuth()

  return (
    <header className="flex min-h-24 items-center justify-between px-5 py-3 sm:px-8">
      <SiteLogo />
      {loading ? (
        <span className="size-10 animate-pulse rounded-full bg-muted" />
      ) : user ? (
        <AccountNav />
      ) : (
        <SignupLoginDialog
          trigger={
            <Button variant="outline" size="xl">
              Sign up or Login
            </Button>
          }
        />
      )}
    </header>
  )
}

export default Header
