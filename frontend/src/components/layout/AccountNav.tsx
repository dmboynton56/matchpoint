import { LogOut, Settings, User } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"

import { signOut } from "@/auth/supabaseAuth"
import { Button } from "@/components/ui/button"
import {
  getUserAvatarUrl,
  getUserDisplayName,
  useAuth,
} from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

function AccountAvatar({ avatarUrl, name }: { avatarUrl?: string; name: string }) {
  const initials = name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()

  if (avatarUrl) {
    return (
      <img
        src={avatarUrl}
        alt=""
        className="size-10 rounded-full border border-border object-cover ring-2 ring-primary/20"
        referrerPolicy="no-referrer"
      />
    )
  }

  return (
    <span
      aria-hidden="true"
      className="flex size-10 items-center justify-center rounded-full border border-border bg-muted text-sm font-semibold text-muted-foreground ring-2 ring-primary/20"
    >
      {initials || "?"}
    </span>
  )
}

export function AccountNav({ className }: { className?: string }) {
  const { user, loading } = useAuth()
  const navigate = useNavigate()
  const avatarUrl = getUserAvatarUrl(user)
  const displayName = getUserDisplayName(user)

  const handleLogout = async () => {
    try {
      await signOut()
      navigate("/")
    } catch {
      toast.error("Could not sign out. Please try again.")
    }
  }

  return (
    <nav
      aria-label="Account"
      className={cn("group relative", className)}
    >
      <button
        type="button"
        className="flex items-center gap-2 rounded-full outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        aria-haspopup="menu"
        aria-label={`Account menu for ${displayName}`}
      >
        {loading ? (
          <span className="size-10 animate-pulse rounded-full bg-muted" />
        ) : (
          <AccountAvatar avatarUrl={avatarUrl} name={displayName} />
        )}
      </button>

      <div
        role="menu"
        className="invisible absolute top-full right-0 z-50 w-44 pt-2 opacity-0 transition-opacity group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100"
      >
        <div className="overflow-hidden rounded-xl border border-border bg-card py-1 shadow-lg ring-1 ring-foreground/5">
          <Button
            type="button"
            variant="ghost"
            role="menuitem"
            className="h-9 w-full justify-start gap-2 rounded-none px-3 font-normal"
            onClick={() => toast.message("Profile — coming soon")}
          >
            <User className="size-4" aria-hidden="true" />
            Profile
          </Button>
          <Button
            type="button"
            variant="ghost"
            role="menuitem"
            className="h-9 w-full justify-start gap-2 rounded-none px-3 font-normal"
            onClick={() => toast.message("Settings — coming soon")}
          >
            <Settings className="size-4" aria-hidden="true" />
            Settings
          </Button>
          <Button
            type="button"
            variant="ghost"
            role="menuitem"
            className="h-9 w-full justify-start gap-2 rounded-none px-3 font-normal text-destructive hover:text-destructive"
            onClick={handleLogout}
          >
            <LogOut className="size-4" aria-hidden="true" />
            Log out
          </Button>
        </div>
      </div>
    </nav>
  )
}
