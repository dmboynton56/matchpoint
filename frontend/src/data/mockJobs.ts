import type { JobListing } from "@/types/job"

/** Max listings shown in the landing preview card (1 sharp + rest blurred). */
export const LANDING_PREVIEW_JOB_COUNT = 4

/** Sample listings for dev/preview until upload + match APIs are wired. */
export const MOCK_JOBS: JobListing[] = [
  {
    id: "00000000-0000-4000-8000-000000000001",
    title: "Senior Frontend Engineer",
    company: "Northwind Labs",
    location: "Remote · US",
    apply_url: "https://example.com/jobs/northwind-senior-fe",
    match_score: 0.92,
    match_highlights: [
      "React and TypeScript called out heavily in your resume",
      "Senior IC scope aligns with your last two roles",
      "Fully remote matches your stated work preference",
    ],
  },
  {
    id: "00000000-0000-4000-8000-000000000002",
    title: "Product Engineer",
    company: "Riverstone Health",
    location: "Hybrid · Denver",
    apply_url: "https://example.com/jobs/riverstone-product",
    match_score: 0.87,
    match_highlights: [
      "Full-stack experience matches the product engineering bar",
      "Healthcare domain overlap from a prior internship",
      "Hybrid schedule fits your Denver metro preference",
    ],
  },
  {
    id: "00000000-0000-4000-8000-000000000003",
    title: "Applied ML Engineer",
    company: "Crescent Analytics",
    location: "Remote · Americas",
    apply_url: "https://example.com/jobs/crescent-ml",
    match_score: 0.84,
    match_highlights: [
      "Python and ML projects appear in your skills section",
      "Data pipeline work mirrors the role’s core responsibilities",
      "Americas remote window matches your timezone",
    ],
  },
  {
    id: "00000000-0000-4000-8000-000000000004",
    title: "Staff Platform Engineer",
    company: "Atlas Mobility",
    location: "On-site · Austin",
    apply_url: "https://example.com/jobs/atlas-platform",
    match_score: 0.81,
    match_highlights: [
      "Kubernetes and infra keywords overlap with your resume",
      "Staff-level scope is adjacent to your platform lead title",
      "On-site in Austin — note relocation if you’re not local",
    ],
  },
  {
    id: "00000000-0000-4000-8000-000000000005",
    title: "Growth Engineer",
    company: "Lumen Retail",
    location: "Remote · EU",
    apply_url: null,
    match_score: 0.78,
    match_highlights: [
      "Experimentation and analytics tools listed on your resume",
      "Growth engineering is a stretch vs your backend-heavy profile",
      "EU remote may require hours overlap with your timezone",
    ],
  },
  {
    id: "00000000-0000-4000-8000-000000000006",
    title: "Developer Experience Lead",
    company: "Harbor Payments",
    location: "Hybrid · NYC",
    apply_url: "https://example.com/jobs/harbor-dx",
    match_score: 0.75,
    match_highlights: [
      "Developer tooling and docs work show up in your experience",
      "Lead title is a step up from your current senior role",
      "Hybrid NYC — partial match on location preference",
    ],
  },
  {
    id: "00000000-0000-4000-8000-000000000007",
    title: "Security Software Engineer",
    company: "Ironwatch",
    location: null,
    apply_url: "https://example.com/jobs/ironwatch-security",
    match_score: 0.72,
    match_highlights: [
      "Security coursework noted, but limited production AppSec depth",
      "Systems programming overlap is moderate for this bar",
      "Location not specified — confirm fit before applying",
    ],
  },
]
