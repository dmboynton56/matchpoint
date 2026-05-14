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

export function SignupLoginCard() {
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
      const { error } = isLogin
        ? await signInWithEmail(prepared.email, password)
        : await signUpWithEmail(prepared.email, password)
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
                {!isLogin && (
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
              {isLogin && (
                <p className="text-xs text-muted-foreground">
                  Password must be at least 8 characters long
                </p>
              )}
              {isLogin && (
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
          variant="outline"
          className="w-full"
          disabled={isSubmitting}
          onClick={handleGoogleSignIn}
        >
          {isSubmitting
            ? "Connecting…"
            : isLogin
              ? "Sign up with Google"
              : "Login with Google"}
        </Button>
      </CardFooter>
    </Card>
  )
}
