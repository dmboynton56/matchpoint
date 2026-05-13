export type MockJob = {
  id: string
  title: string
  company: string
  location: string
  tags: string[]
}

export const MOCK_JOBS: MockJob[] = [
  {
    id: "1",
    title: "Senior Frontend Engineer",
    company: "Northwind Labs",
    location: "Remote · US",
    tags: ["React", "Staff"],
  },
  {
    id: "2",
    title: "Product Engineer",
    company: "Riverstone Health",
    location: "Hybrid · Denver",
    tags: ["AI", "Full-stack"],
  },
  {
    id: "3",
    title: "Applied ML Engineer",
    company: "Crescent Analytics",
    location: "Remote · Americas",
    tags: ["Python", "Remote"],
  },
  {
    id: "4",
    title: "Staff Platform Engineer",
    company: "Atlas Mobility",
    location: "On-site · Austin",
    tags: ["Kubernetes"],
  },
  {
    id: "5",
    title: "Growth Engineer",
    company: "Lumen Retail",
    location: "Remote · EU",
    tags: ["Data"],
  },
  {
    id: "6",
    title: "Developer Experience Lead",
    company: "Harbor Payments",
    location: "Hybrid · NYC",
    tags: ["DX"],
  },
  {
    id: "7",
    title: "Security Software Engineer",
    company: "Ironwatch",
    location: "Remote",
    tags: ["Security"],
  },
]
