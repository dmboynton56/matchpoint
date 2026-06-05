import type { Match } from "@/apis/matches"
import type { JobMatch } from "@/types/job"

export function sortByMatchScore(jobs: JobMatch[]): JobMatch[] {
  return [...jobs].sort((a, b) => (b.match_score ?? 0) - (a.match_score ?? 0))
}

export function matchToJobMatch(match: Match): JobMatch {
  return {
    id: match.job.id,
    match_id: match.match_id,
    is_favorited: match.is_favorited,
    title: match.job.title,
    company: match.job.company,
    location: match.job.location,
    apply_url: match.job.apply_url,
    match_score: match.match_score,
    match_notes: match.match_notes,
    match_highlights: match.match_highlights,
    match_concerns: match.match_concerns,
    interview_likelihood: match.interview_likelihood,
    skills_fit: match.skills_fit,
    experience_fit: match.experience_fit,
    seniority_fit: match.seniority_fit,
    location_fit: match.location_fit,
    pay_fit: match.pay_fit,
    role_fit: match.role_fit,
    preference_fit: match.preference_fit,
    location_reason: match.location_reason,
    location_evidence: match.location_evidence,
    pay_reason: match.pay_reason,
    pay_evidence: match.pay_evidence,
    role_reason: match.role_reason,
    role_evidence: match.role_evidence,
    job_facts: match.job_facts,
  }
}
