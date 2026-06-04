import { useEffect, useState } from "react"
import { toast } from "sonner"

import {
  consumeOAuthUrlError,
  prepareEmailForAuth,
  signUpWithEmail,
  signInWithEmail,
  signInWithGoogle,
} from "@/auth/supabaseAuth"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useNavigate } from "react-router-dom"

const GoogleGIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 48 48"
    width="18"
    height="18"
    aria-hidden="true"
    focusable="false"
    {...props}
  >
    <path
      fill="#EA4335"
      d="M24 9.5c3.15 0 5.78 1.09 7.93 2.9l5.81-5.81C34.18 3.1 29.53 1 24 1 14.62 1 6.51 6.38 2.56 14.22l6.76 5.25C11.12 13.54 17.04 9.5 24 9.5z"
    />
    <path
      fill="#4285F4"
      d="M46.5 24.5c0-1.62-.15-3.17-.42-4.67H24v8.84h12.6c-.54 2.9-2.19 5.36-4.67 7.02l7.16 5.55C43.25 37.4 46.5 31.54 46.5 24.5z"
    />
    <path
      fill="#FBBC05"
      d="M9.32 28.53A14.45 14.45 0 0 1 8.5 24c0-1.58.27-3.1.82-4.53l-6.76-5.25A23 23 0 0 0 1 24c0 3.7.88 7.2 2.56 10.28l6.76-5.25z"
    />
    <path
      fill="#34A853"
      d="M24 47c5.53 0 10.18-1.83 13.59-4.96l-7.16-5.55c-1.98 1.33-4.5 2.11-6.43 2.11-6.96 0-12.88-4.04-14.68-9.97l-6.76 5.25C6.51 41.62 14.62 47 24 47z"
    />
    <path fill="none" d="M0 0h48v48H0z" />
  </svg>
)

const SignupLoginCard = () => {
  const navigate = useNavigate()

  useEffect(() => {
    const urlError = consumeOAuthUrlError()
    if (urlError) {
      toast.error(urlError, { position: "top-center" })
    }
  }, [])

  const [isLogin, setIsLogin] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")

  const handleSubmit = async (email: string, password: string) => {
    const prepared = prepareEmailForAuth(email)
    if (!prepared.ok) {
      toast.error(prepared.message, { position: "top-center" })
      return
    }

    setIsSubmitting(true)
    try {
      const result = isLogin
        ? await signInWithEmail(email, password)
        : await signUpWithEmail(email, password)
      if (!result.ok) {
        toast.error(result.message, { position: "top-center" })
        return
      }
      const { error } = result
      if (error?.code === "weak_password") {
        toast.error(
          "Password must be at least 8 characters and include uppercase, lowercase, a number, and a special character.",
          { position: "top-center" }
        )
        return
      }
      if (error) {
        toast.error(
          error.message ||
            `Could not use email and password to ${isLogin ? "login" : "sign up"}. Please try again.`,
          { position: "top-center" }
        )
      } else {
        toast.success(
          `Successfully ${isLogin ? "logged in" : "signed up"}. Redirecting to dashboard...`,
          { position: "top-center" }
        )
        navigate("/jobs", { replace: true })
      }
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : `Something went wrong while using email and password to ${isLogin ? "login" : "sign up"}. Please try again.`
      toast.error(message, { position: "top-center" })
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleGoogleSignIn = async () => {
    setIsSubmitting(true)
    try {
      const { error } = await signInWithGoogle()
      if (error) {
        toast.error(
          error.message || "Could not use Google sign-in. Please try again.",
          { position: "top-center" }
        )
      }
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : "Something went wrong while connecting to Google."
      toast.error(message, { position: "top-center" })
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle>
          {isLogin ? "Login to your account" : "Sign up for an account"}
        </CardTitle>
        <CardDescription>
          {isLogin
            ? "Enter your email and password or use Google to login to your account"
            : "Enter your email and password or use Google to sign up for an account"}
        </CardDescription>
        <CardAction>
          <Button variant="link" onClick={() => setIsLogin(!isLogin)}>
            {isLogin ? "Sign up" : "Login"}
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        <form
          id="signup-login-email-form"
          onSubmit={(e) => {
            e.preventDefault()
            void handleSubmit(email, password)
          }}
        >
          <div className="flex flex-col gap-6">
            <div className="grid gap-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="your-email@example.com"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <div className="flex items-center">
                <Label htmlFor="password">Password</Label>
                {isLogin && (
                  <a
                    href="#"
                    className="ml-auto inline-block text-sm underline-offset-4 hover:underline"
                  >
                    Forgot your password?
                  </a>
                )}
              </div>
              <Input
                id="password"
                type="password"
                autoComplete={isLogin ? "current-password" : "new-password"}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              {!isLogin && (
                <p className="text-xs text-muted-foreground">
                  Password must be at least 8 characters long
                </p>
              )}
              {!isLogin && (
                <p className="text-xs text-muted-foreground">
                  Password must contain at least one uppercase letter, one
                  lowercase letter, one number, and one special character
                </p>
              )}
            </div>
          </div>
        </form>
      </CardContent>
      <CardFooter className="flex-col gap-2">
        <Button
          type="submit"
          form="signup-login-email-form"
          className="w-full"
          disabled={isSubmitting}
        >
          {isSubmitting ? "Connecting…" : "Submit"}
        </Button>
        <Button
          type="button"
          variant="outline"
          className="w-full bg-white! text-black ring-0! hover:bg-white/80! hover:text-black"
          disabled={isSubmitting}
          onClick={handleGoogleSignIn}
        >
          <GoogleGIcon />
          {isSubmitting ? "Connecting…" : "Login with Google"}
        </Button>
      </CardFooter>
    </Card>
  )
}

type SignupLoginDialogProps = {
  open?: boolean
  onOpenChange?: (open: boolean) => void
  trigger?: React.ReactNode
}

export function SignupLoginDialog({
  open,
  onOpenChange,
  trigger,
}: SignupLoginDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {trigger ? <DialogTrigger asChild>{trigger}</DialogTrigger> : null}
      <DialogContent>
        <DialogTitle className="sr-only">Sign in or create an account</DialogTitle>
        <DialogDescription className="sr-only">
          Use email, password, or Google to sign in or sign up.
        </DialogDescription>
        <SignupLoginCard />
      </DialogContent>
    </Dialog>
  )
}

export default SignupLoginCard
