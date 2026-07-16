import type { JobBrowseListing } from "@/types/job"
import {
  DEFAULT_JOB_SEARCH_FILTERS,
  type JobSearchFilters,
} from "@/types/jobSearch"

/** Max listings shown in the landing preview card (1 sharp + rest blurred). */
export const LANDING_PREVIEW_JOB_COUNT = 4

/**
 * Sample Turso-shaped listings for dev/preview until `GET /jobs/search`
 * exists. Fields mirror `fetch_full_jobs()` in backend/app/db/turso.py:
 * id, title, company, location, apply_url, description, posted_at.
 */
export const MOCK_JOBS: JobBrowseListing[] = [
  {
    id: "00000000-0000-4000-8000-000000000001",
    title: "Senior Frontend Engineer",
    company: "Northwind Labs",
    location: "Remote · US",
    apply_url: "https://example.com/jobs/northwind-senior-fe",
    description:
      "Build customer-facing React and TypeScript experiences for a fast-growing SaaS platform.",
    posted_at: daysAgo(2),
  },
  {
    id: "00000000-0000-4000-8000-000000000002",
    title: "Product Engineer",
    company: "Riverstone Health",
    location: "Hybrid · Denver",
    apply_url: "https://example.com/jobs/riverstone-product",
    description:
      "Full-stack product engineer working across React, Node, and healthcare integrations.",
    posted_at: daysAgo(5),
  },
  {
    id: "00000000-0000-4000-8000-000000000003",
    title: "Applied ML Engineer",
    company: "Crescent Analytics",
    location: "Remote · Americas",
    apply_url: "https://example.com/jobs/crescent-ml",
    description:
      "Ship production machine learning pipelines and model serving for analytics products.",
    posted_at: daysAgo(1),
  },
  {
    id: "00000000-0000-4000-8000-000000000004",
    title: "Staff Platform Engineer",
    company: "Atlas Mobility",
    location: "On-site · Austin",
    apply_url: "https://example.com/jobs/atlas-platform",
    description:
      "Own Kubernetes infrastructure, observability, and developer tooling for platform teams.",
    posted_at: daysAgo(9),
  },
  {
    id: "00000000-0000-4000-8000-000000000005",
    title: "Growth Engineer",
    company: "Lumen Retail",
    location: "Remote · EU",
    apply_url: null,
    description:
      "Run experiments, build funnel analytics, and optimize acquisition flows for e-commerce.",
    posted_at: daysAgo(14),
  },
  {
    id: "00000000-0000-4000-8000-000000000006",
    title: "Developer Experience Lead",
    company: "Harbor Payments",
    location: "Hybrid · NYC",
    apply_url: "https://example.com/jobs/harbor-dx",
    description:
      "Lead internal developer experience initiatives across docs, SDKs, and CI tooling.",
    posted_at: daysAgo(20),
  },
  {
    id: "00000000-0000-4000-8000-000000000007",
    title: "Security Software Engineer",
    company: "Ironwatch",
    location: "Remote · US",
    apply_url: "https://example.com/jobs/ironwatch-security",
    description:
      "Harden application security, threat modeling, and secure coding practices across services.",
    posted_at: daysAgo(30),
  },
  {
    id: "00000000-0000-4000-8000-000000000008",
    title: "Machine Learning Engineer I",
    company: "Crescent Analytics",
    location: "Denver, CO",
    apply_url: "https://example.com/jobs/crescent-mle-1",
    description:
      "Entry-level machine learning role focused on feature engineering and model evaluation.",
    posted_at: daysAgo(1),
  },
  {
    id: "00000000-0000-4000-8000-000000000009",
    title: "Entry Level Machine Learning Engineer",
    company: "Northwind Labs",
    location: "San Francisco, CA",
    apply_url: "https://example.com/jobs/northwind-mle-entry",
    description:
      "Junior ML engineer supporting experimentation, data labeling, and notebook-to-production workflows.",
    posted_at: daysAgo(3),
  },
  {
    id: "00000000-0000-4000-8000-000000000010",
    title: "Junior ML / Data Scientist",
    company: "Lumen Retail",
    location: "Remote · US",
    apply_url: "https://example.com/jobs/lumen-junior-ml",
    description:
      "Apply machine learning to demand forecasting and recommendation systems for retail.",
    posted_at: daysAgo(4),
  },
  {
    id: "00000000-0000-4000-8000-000000000011",
    title: "Machine Learning Intern",
    company: "Atlas Mobility",
    location: "San Francisco, CA",
    apply_url: "https://example.com/jobs/atlas-ml-intern",
    description:
      "Summer internship building computer vision prototypes for autonomous systems research.",
    posted_at: daysAgo(6),
  },
  {
    id: "00000000-0000-4000-8000-000000000012",
    title: "Backend Engineer, Payments",
    company: "Harbor Payments",
    location: "Denver, CO",
    apply_url: "https://example.com/jobs/harbor-backend",
    description:
      "Design and operate high-throughput payment APIs with strong reliability requirements.",
    posted_at: daysAgo(8),
  },
  {
    id: "00000000-0000-4000-8000-000000000013",
    title: "Data Engineer",
    company: "Ironwatch",
    location: "Remote · US",
    apply_url: "https://example.com/jobs/ironwatch-data-eng",
    description:
      "Build batch and streaming data pipelines supporting security analytics and reporting.",
    posted_at: daysAgo(11),
  },
  {
    id: "00000000-0000-4000-8000-000000000014",
    title: "Frontend Engineer, New Grad",
    company: "Riverstone Health",
    location: "Austin, TX",
    apply_url: "https://example.com/jobs/riverstone-newgrad-fe",
    description:
      "New grad frontend role working on accessible patient-facing web applications.",
    posted_at: daysAgo(2),
  },
  {
    id: "00000000-0000-4000-8000-000000000015",
    title: "Computer Vision Engineer",
    company: "Atlas Mobility",
    location: "Remote · US",
    apply_url: "https://example.com/jobs/atlas-cv",
    description:
      "Develop perception models and evaluation tooling for robotics and mobility products.",
    posted_at: daysAgo(15),
  },
  {
    id: "00000000-0000-4000-8000-000000000016",
    title: "Site Reliability Engineer",
    company: "Northwind Labs",
    location: "Seattle, WA",
    apply_url: "https://example.com/jobs/northwind-sre",
    description:
      "Improve reliability, incident response, and capacity planning for cloud-native services.",
    posted_at: daysAgo(18),
  },
  {
    id: "00000000-0000-4000-8000-000000000017",
    title: "NLP Research Engineer",
    company: "Crescent Analytics",
    location: "Remote · US",
    apply_url: "https://example.com/jobs/crescent-nlp",
    description:
      "Research and productionize NLP models for document understanding and search.",
    posted_at: daysAgo(1),
  },
  {
    id: "00000000-0000-4000-8000-000000000018",
    title: "Machine Learning Engineer II",
    company: "Lumen Retail",
    location: "Denver, CO",
    apply_url: "https://example.com/jobs/lumen-mle-2",
    description:
      "Mid-level machine learning engineer owning ranking models and offline evaluation.",
    posted_at: daysAgo(7),
  },
  {
    id: "00000000-0000-4000-8000-000000000019",
    title: "Support Engineer, Contract",
    company: "Ironwatch",
    location: "Chicago, IL",
    apply_url: "https://example.com/jobs/ironwatch-support-contract",
    description:
      "Contract role triaging customer issues and coordinating with engineering on escalations.",
    posted_at: daysAgo(25),
  },
  {
    id: "00000000-0000-4000-8000-000000000020",
    title: "VP of Engineering",
    company: "Harbor Payments",
    location: "New York, NY",
    apply_url: "https://example.com/jobs/harbor-vpe",
    description:
      "Executive leadership role scaling engineering org, roadmap, and delivery for payments.",
    posted_at: daysAgo(40),
  },
]

function daysAgo(days: number): string {
  const date = new Date()
  date.setUTCDate(date.getUTCDate() - days)
  return date.toISOString()
}

const DATE_POSTED_WINDOW_DAYS: Record<string, number> = {
  "24h": 1,
  "3d": 3,
  "7d": 7,
  "14d": 14,
  "30d": 30,
}

function jobHaystack(job: JobBrowseListing): string {
  return `${job.title} ${job.company} ${job.description ?? ""}`.toLowerCase()
}

function keywordScore(job: JobBrowseListing, keywords: string): number {
  const trimmed = keywords.trim().toLowerCase()
  if (!trimmed) return 0

  const terms = trimmed.split(/\s+/).filter(Boolean)
  const haystack = jobHaystack(job)
  let score = 0

  for (const term of terms) {
    if (job.title.toLowerCase().includes(term)) score += 3
    if (job.company.toLowerCase().includes(term)) score += 2
    if (haystack.includes(term)) score += 1
  }

  return score
}

function matchesKeywords(job: JobBrowseListing, keywords: string): boolean {
  const trimmed = keywords.trim().toLowerCase()
  if (!trimmed) return true
  return trimmed.split(/\s+/).every((term) => jobHaystack(job).includes(term))
}

function matchesLocation(job: JobBrowseListing, locations: string[]): boolean {
  if (locations.length === 0) return true
  const haystack = (job.location ?? "").toLowerCase()
  return locations.some((location) => haystack.includes(location.toLowerCase()))
}

function matchesDatePosted(job: JobBrowseListing, datePosted: string): boolean {
  if (datePosted === "any") return true
  const windowDays = DATE_POSTED_WINDOW_DAYS[datePosted]
  if (!windowDays || !job.posted_at) return true
  const postedDate = new Date(job.posted_at)
  if (Number.isNaN(postedDate.getTime())) return true
  const diffDays = (Date.now() - postedDate.getTime()) / (1000 * 60 * 60 * 24)
  return diffDays <= windowDays
}

function sortJobs(
  jobs: JobBrowseListing[],
  sort: JobSearchFilters["sort"],
  keywords: string
): JobBrowseListing[] {
  const sorted = [...jobs]
  switch (sort) {
    case "newest":
      sorted.sort(
        (a, b) =>
          new Date(b.posted_at ?? 0).getTime() -
          new Date(a.posted_at ?? 0).getTime()
      )
      break
    case "relevance":
    default:
      sorted.sort(
        (a, b) => keywordScore(b, keywords) - keywordScore(a, keywords)
      )
      break
  }
  return sorted
}

export type MockSearchJobsResult = {
  jobs: JobBrowseListing[]
  total: number
  page: number
  pageSize: number
}

/**
 * Client-side stand-in for `GET /jobs/search`. Only filters/sorts on fields
 * Turso stores today (title, company, location, description, posted_at).
 * Pay/level/type/workplace filters in the UI are ignored here until the
 * backend adds those columns.
 */
export async function mockSearchJobs(
  filters: JobSearchFilters = DEFAULT_JOB_SEARCH_FILTERS
): Promise<MockSearchJobsResult> {
  await new Promise((resolve) => setTimeout(resolve, 350))

  const filtered = MOCK_JOBS.filter((job) => {
    if (!matchesKeywords(job, filters.keywords)) return false
    if (!matchesLocation(job, filters.locations)) return false
    if (!matchesDatePosted(job, filters.datePosted)) return false
    return true
  })

  const sorted = sortJobs(filtered, filters.sort, filters.keywords)
  const total = sorted.length
  const start = (filters.page - 1) * filters.pageSize
  const page = sorted.slice(start, start + filters.pageSize)

  return { jobs: page, total, page: filters.page, pageSize: filters.pageSize }
}
