import {
  Briefcase,
  ClipboardCheck,
  FileText,
  Heart,
  LogOut,
  Sparkles,
  User,
} from "lucide-react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { signOut } from "@/auth/supabaseAuth"
import { getUserAvatarUrl, getUserDisplayName, useAuth } from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

const AccountAvatar = ({
  avatarUrl,
  name,
}: {
  avatarUrl?: string
  name: string
}) => {
  const initials = name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()

  return (
    <Avatar className="size-10 border border-border ring-2 ring-primary/20">
      <AvatarImage
        src={avatarUrl}
        alt={name}
        referrerPolicy="no-referrer"
        className="object-cover"
      />
      <AvatarFallback className="bg-muted text-sm font-semibold text-muted-foreground">
        {initials || "?"}
      </AvatarFallback>
    </Avatar>
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

  if (!loading && !user) {
    return null
  }

  return (
    <nav aria-label="Account" className={cn("group relative", className)}>
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
            onClick={() => navigate("/jobs")}
          >
            <Briefcase className="size-4" aria-hidden="true" />
            Jobs
          </Button>
          <Button
            type="button"
            variant="ghost"
            role="menuitem"
            className="h-9 w-full justify-start gap-2 rounded-none px-3 font-normal"
            onClick={() => navigate("/matches")}
          >
            <Sparkles className="size-4" aria-hidden="true" />
            Matches
          </Button>
          <Button
            type="button"
            variant="ghost"
            role="menuitem"
            className="h-9 w-full justify-start gap-2 rounded-none px-3 font-normal"
            onClick={() => navigate("/applied")}
          >
            <ClipboardCheck className="size-4" aria-hidden="true" />
            Applied
          </Button>
          <Button
            type="button"
            variant="ghost"
            role="menuitem"
            className="h-9 w-full justify-start gap-2 rounded-none px-3 font-normal"
            onClick={() => navigate("/favorites")}
          >
            <Heart className="size-4" aria-hidden="true" />
            Favorites
          </Button>
          <Button
            type="button"
            variant="ghost"
            role="menuitem"
            className="h-9 w-full justify-start gap-2 rounded-none px-3 font-normal"
            onClick={() => navigate("/profile")}
          >
            <User className="size-4" aria-hidden="true" />
            Profile
          </Button>
          <Button
            type="button"
            variant="ghost"
            role="menuitem"
            className="h-9 w-full justify-start gap-2 rounded-none px-3 font-normal"
            onClick={() => navigate("/resume")}
          >
            <FileText className="size-4" aria-hidden="true" />
            Resume
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
