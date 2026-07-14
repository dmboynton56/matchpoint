import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { ExternalLink, FileText, Trash2, Upload } from "lucide-react"
import { toast } from "sonner"

import {
  deleteResume,
  getResumeDetails,
  type ResumeDetailsResponse,
  uploadResume,
} from "@/apis/resumes"
import { AppShell } from "@/components/layout/AppShell"
import { ResumeSuggestionsCard } from "@/components/user/ResumeSuggestionsCard"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useAuth } from "@/hooks/useAuth"

export function ResumePage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const resumeInputRef = useRef<HTMLInputElement>(null)

  const [resume, setResume] = useState<ResumeDetailsResponse | null>(null)
  const [resumeLoading, setResumeLoading] = useState(true)
  const [resumeUploading, setResumeUploading] = useState(false)
  const [resumeDeleting, setResumeDeleting] = useState(false)
  const [resumeMutationPending, setResumeMutationPending] = useState(false)

  const refreshResume = useCallback(async (showLoading = true) => {
    if (showLoading) {
      setResumeLoading(true)
    }
    try {
      setResume(await getResumeDetails())
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Could not load resume."
      toast.error(message, { position: "top-center" })
    } finally {
      setResumeLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!user) return
    void refreshResume(false)
  }, [refreshResume, user])

  const handleViewResume = () => {
    if (!resume?.signed_url) return
    window.open(resume.signed_url, "_blank", "noopener,noreferrer")
  }

  const handleResumeUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ""

    if (!file) return
    if (file.type !== "application/pdf") {
      toast.error("Only PDF files are supported.", { position: "top-center" })
      return
    }

    setResumeMutationPending(true)
    setResumeUploading(true)
    try {
      const response = await uploadResume(file)
      await refreshResume()
      toast.success("Resume updated.", { position: "top-center" })
      navigate("/jobs", { state: { jobs: response.jobs } })
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Resume upload failed."
      toast.error(message, { position: "top-center" })
    } finally {
      setResumeUploading(false)
      setResumeMutationPending(false)
    }
  }

  const handleDeleteResume = async () => {
    setResumeMutationPending(true)
    setResumeDeleting(true)
    try {
      await deleteResume()
      await refreshResume()
      toast.success("Resume deleted.", { position: "top-center" })
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Resume delete failed."
      toast.error(message, { position: "top-center" })
    } finally {
      setResumeDeleting(false)
      setResumeMutationPending(false)
    }
  }

  if (!user) {
    return null
  }

  const resumeUploadedAt =
    resume?.uploaded_at === null || resume?.uploaded_at === undefined
      ? null
      : new Intl.DateTimeFormat(undefined, {
          month: "short",
          day: "numeric",
          year: "numeric",
        }).format(new Date(resume.uploaded_at))

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-5xl space-y-8">
        <section className="space-y-2">
          <p className="text-xs font-semibold tracking-[0.22em] text-primary uppercase">
            Account
          </p>
          <h1 className="font-heading text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
            Resume
          </h1>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            View your resume, re-upload it, and get tailored suggestions and
            bullet rewrites grounded in your top job matches.
          </p>
        </section>

        <div className="flex flex-col items-center gap-6">
          <Card className="h-fit min-w-100 md:min-w-150 lg:min-w-200">
            <CardHeader>
              <CardTitle>Your resume</CardTitle>
              <CardDescription>
                View, re-upload, or delete your resume.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {resumeLoading ? (
                <div className="flex h-72 items-center justify-center rounded-lg border border-dashed border-border bg-muted/30 text-sm text-muted-foreground">
                  Loading resume…
                </div>
              ) : resume?.has_resume && resume.signed_url ? (
                <div className="space-y-3">
                  <div
                    role="button"
                    tabIndex={0}
                    className="group relative h-72 w-full overflow-hidden rounded-lg border border-border bg-muted/30 text-left"
                    onClick={handleViewResume}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault()
                        handleViewResume()
                      }
                    }}
                    aria-label="Open uploaded resume"
                  >
                    <iframe
                      title="Uploaded resume preview"
                      src={`${resume.signed_url}#page=1&toolbar=0&navpanes=0&scrollbar=0`}
                      className="pointer-events-none h-full w-full bg-white"
                    />
                    <span className="absolute inset-0 bg-transparent transition-colors group-hover:bg-background/10" />
                  </div>
                  <div className="flex items-center gap-3 text-sm">
                    <FileText
                      className="size-4 shrink-0 text-muted-foreground"
                      aria-hidden="true"
                    />
                    <div className="min-w-0">
                      <p className="truncate font-medium text-foreground">
                        {resume.file_name ?? "resume.pdf"}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {resumeUploadedAt
                          ? `Uploaded ${resumeUploadedAt}`
                          : "Uploaded resume on file"}
                      </p>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="flex h-72 flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-muted/30 px-4 text-center text-sm text-muted-foreground">
                  <FileText className="size-8" aria-hidden="true" />
                  No resume on file
                </div>
              )}
              <input
                ref={resumeInputRef}
                type="file"
                accept="application/pdf"
                className="hidden"
                disabled={resumeMutationPending}
                onChange={(e) => void handleResumeUpload(e)}
              />
            </CardContent>
            <CardFooter className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={!resume?.has_resume || !resume.signed_url}
                onClick={handleViewResume}
              >
                <ExternalLink className="size-4" aria-hidden="true" />
                View
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={resumeUploading || resumeMutationPending}
                onClick={() => resumeInputRef.current?.click()}
              >
                <Upload className="size-4" aria-hidden="true" />
                {resume?.has_resume ? "Re-upload" : "Upload"}
              </Button>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    type="button"
                    variant="destructive"
                    disabled={
                      !resume?.has_resume ||
                      resumeDeleting ||
                      resumeMutationPending
                    }
                  >
                    <Trash2 className="size-4" aria-hidden="true" />
                    Delete
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Delete resume?</AlertDialogTitle>
                    <AlertDialogDescription>
                      This removes your uploaded resume from your profile. You
                      can upload a new one anytime.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction
                      variant="destructive"
                      disabled={resumeDeleting || resumeMutationPending}
                      onClick={() => void handleDeleteResume()}
                    >
                      Confirm
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </CardFooter>
          </Card>

          <div className="w-full max-w-3xl space-y-2">
            <h2 className="font-heading text-lg font-semibold tracking-tight text-foreground">
              Tailored resume tips
            </h2>
            <p className="text-sm leading-relaxed text-muted-foreground">
              Suggestions to add to your resume, based on the skills your top
              job matches are asking for. Each tip is grounded in a real job
              description. The bullet workshop below is experimental — it
              asks you to defend the weakest bullets (missing specifics,
              scope, ownership, or results) and rewrites them from what
              you say, but the output isn&apos;t guaranteed to keep every
              measurable detail intact. Read before you paste it in.
            </p>
            <ResumeSuggestionsCard enabled={!!resume?.has_resume} />
          </div>
        </div>
      </div>
    </AppShell>
  )
}
