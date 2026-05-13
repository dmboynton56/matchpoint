import { useEffect, useState } from "react"
import { toast } from "sonner"

import { consumeOAuthUrlError, signInWithGoogle } from "@/auth/supabaseAuth"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

export function GoogleOAuth() {
  const [isSigningIn, setIsSigningIn] = useState(false)

  useEffect(() => {
    const urlError = consumeOAuthUrlError()
    if (urlError) {
      toast.error(urlError)
    }
  }, [])

  const handleGoogleSignIn = async () => {
    setIsSigningIn(true)
    try {
      const { error } = await signInWithGoogle()
      if (error) {
        toast.error(
          error.message || "Could not start Google sign-in. Please try again.",
        )
      }
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : "Something went wrong while connecting to Google."
      toast.error(message)
    } finally {
      setIsSigningIn(false)
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle>Login to your account</CardTitle>
        <CardDescription>
          Use Google to signup or login to your account
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button
          variant="outline"
          className="w-full"
          disabled={isSigningIn}
          onClick={handleGoogleSignIn}
        >
          {isSigningIn ? "Connecting…" : "Login with Google"}
        </Button>
      </CardContent>
    </Card>
  )
}
