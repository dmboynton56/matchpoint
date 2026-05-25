import {
  Dropzone,
  DropZoneArea,
  DropzoneDescription,
  DropzoneFileList,
  DropzoneFileListItem,
  DropzoneMessage,
  DropzoneRemoveFile,
  DropzoneTrigger,
  useDropzone,
} from "@/components/ui/dropzone"
import { uploadResume } from "@/apis/resumes"
import { CloudUploadIcon, FileUp, Trash2Icon } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"

import { Button } from "../ui/button"
import { Spinner } from "../ui/spinner"

const UploadDropzone = () => {
  const navigate = useNavigate()

  const dropzone = useDropzone({
    onDropFile: async (file: File) => {
      try {
        const response = await uploadResume(file)
        toast.success("Resume uploaded successfully")
        navigate("/jobs", { state: { jobs: response.jobs } })
        return {
          status: "success",
          result: URL.createObjectURL(file),
        }
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Resume upload failed"
        toast.error(message)
        return {
          status: "error",
          error: message,
        }
      }
    },
    validation: {
      accept: {
        "application/pdf": [".pdf"],
      },
      maxFiles: 1,
    },
  })

  return (
    <div className="not-prose flex flex-col gap-4">
      <Dropzone {...dropzone}>
        <div>
          <div className="mb-4 text-center">
            <DropzoneDescription className="text-lg font-bold">
              Please upload your resume (PDF Format Only)
            </DropzoneDescription>
            <DropzoneMessage className="text-md font-bold" />
          </div>
          <DropZoneArea className="rounded-md border-2 border-dashed border-primary">
            <DropzoneTrigger className="flex flex-col items-center gap-4 bg-transparent p-10 text-center text-sm">
              <CloudUploadIcon className="size-10" />
              <div>
                <Button
                  asChild
                  size="lg"
                  variant="secondary"
                  className="pointer-events-auto mb-2 h-11 gap-2 rounded-xl border border-accent/35 bg-accent px-6 text-base font-semibold text-accent-foreground shadow-md shadow-accent/15 hover:bg-accent/80"
                >
                  <span>
                    <FileUp className="size-4 shrink-0" aria-hidden="true" />
                    Upload your resume
                  </span>
                </Button>
                <p className="text-sm text-muted-foreground">
                  Click here or drag and drop your resume (PDF Format Only)
                </p>
              </div>
            </DropzoneTrigger>
          </DropZoneArea>
        </div>

        <DropzoneFileList>
          {dropzone.fileStatuses.map((file) => (
            <DropzoneFileListItem
              className="overflow-hidden rounded-md bg-secondary p-0 shadow-sm"
              key={file.id}
              file={file}
            >
              {file.status === "pending" && (
                <div className="flex w-full justify-center bg-black/10 py-4">
                  <span className="inline-flex">
                    <Spinner className="size-6 text-primary" />
                  </span>
                </div>
              )}

              <div className="flex items-center justify-between p-2 pl-4">
                <div className="min-w-0">
                  <p className="truncate text-sm">{file.fileName}</p>
                  <p className="text-xs text-muted-foreground">
                    {(file.file.size / (1024 * 1024)).toFixed(2)} MB
                  </p>
                </div>
                {file.status === "success" && (
                  <DropzoneRemoveFile
                    variant="ghost"
                    className="shrink-0 cursor-pointer hover:text-destructive"
                  >
                    <Trash2Icon className="size-4" />
                  </DropzoneRemoveFile>
                )}
              </div>
            </DropzoneFileListItem>
          ))}
        </DropzoneFileList>
      </Dropzone>
    </div>
  )
}

export default UploadDropzone
