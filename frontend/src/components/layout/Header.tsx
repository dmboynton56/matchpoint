import { Button } from "@/components/ui/button"
import { AccountNav } from "@/components/layout/AccountNav"
import SignupLoginCard from "@/components/user/SignupLoginCard"
import { useAuth } from "@/hooks/useAuth"
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
  DialogTrigger,
} from "../ui/dialog"
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
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="outline" size="xl">
              Sign up or Login
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogTitle className="sr-only">
              Sign in or create an account
            </DialogTitle>
            <DialogDescription className="sr-only">
              Use email, password, or Google to sign in or sign up.
            </DialogDescription>
            <SignupLoginCard />
          </DialogContent>
        </Dialog>
      )}
    </header>
  )
}

export default Header
