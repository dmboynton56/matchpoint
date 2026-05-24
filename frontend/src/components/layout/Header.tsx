import { Button } from "@/components/ui/button"
import { SiteLogo } from "./SiteLogo"
import SignupLoginCard from "@/components/user/SignupLoginCard"
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
  DialogTrigger,
} from "../ui/dialog"
const Header = () => {
  return (
    <header className="flex min-h-24 items-center justify-between px-5 py-3 sm:px-8">
      <SiteLogo />
      <Dialog>
        <DialogTrigger asChild>
          <Button variant="outline">Login</Button>
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
    </header>
  )
}

export default Header
