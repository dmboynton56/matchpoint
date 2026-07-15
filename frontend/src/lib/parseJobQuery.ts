import {
  formatExperienceLevel,
  formatJobType,
  formatWorkplaceType,
  type ExperienceLevel,
  type JobType,
  type WorkplaceType,
} from "@/types/job"
import type { JobSearchFilters } from "@/types/jobSearch"

/**
 * PLACEHOLDER heuristic query parser — regex/keyword matching only, no LLM.
 * Good enough to demo the chat-style search assistant end-to-end today.
 *
 * Swap this out (and `extractFiltersFromMessage` in
 * `@/apis/jobSearchAssistant`, the only caller) for a real NLU/LLM call once
 * the backend endpoint exists. Nothing else in the UI needs to change.
 */

const EXPERIENCE_LEVEL_KEYWORDS: [RegExp, ExperienceLevel][] = [
  [/\b(intern(ship)?)\b/i, "internship"],
  [/\b(entry[\s-]?level|new\s?grad|junior|jr\.?)\b/i, "entry"],
  [/\b(mid[\s-]?level|mid[\s-]?senior)\b/i, "mid"],
  [/\b(senior|sr\.?)\b/i, "senior"],
  [/\b(lead|staff|principal)\b/i, "lead"],
  [/\b(executive|director|vp|vice\s?president|head\s?of)\b/i, "executive"],
]

const JOB_TYPE_KEYWORDS: [RegExp, JobType][] = [
  [/\b(internship|intern)\b/i, "internship"],
  [/\b(part[\s-]?time)\b/i, "part_time"],
  [/\b(contract(or)?)\b/i, "contract"],
  [/\b(temp(orary)?)\b/i, "temporary"],
  [/\b(full[\s-]?time)\b/i, "full_time"],
]

// "Remote" is deliberately excluded here — see `CITY_ALIASES` below. Phrases
// like "Denver, SF, or remote" list remote as an OR'd alternative to a city,
// not an independent AND'd facet, so it's folded into `locations` (which
// already has a "Remote" option) instead of `workplaceTypes`. Otherwise
// "remote" + a specific city would AND together and (almost) always return
// zero results, since a listing is rarely both.
const WORKPLACE_TYPE_KEYWORDS: [RegExp, WorkplaceType][] = [
  [/\b(hybrid)\b/i, "hybrid"],
  [/\b(on[\s-]?site|in[\s-]?person|in[\s-]?office)\b/i, "on_site"],
]

/** Small curated set of common tech-hub cities + aliases. Extend as needed. */
const CITY_ALIASES: [RegExp, string][] = [
  [/\b(remote|wfh|work\s?from\s?home)\b/i, "Remote"],
  [/\b(san\s?francisco|sf|bay\s?area)\b/i, "San Francisco"],
  [/\b(new\s?york(\s?city)?|nyc|ny)\b/i, "New York"],
  [/\bdenver\b/i, "Denver"],
  [/\baustin\b/i, "Austin"],
  [/\bseattle\b/i, "Seattle"],
  [/\bboston\b/i, "Boston"],
  [/\bchicago\b/i, "Chicago"],
  [/\b(los\s?angeles|la)\b/i, "Los Angeles"],
]

/** Matches in the order they first appear in `message`, not pattern order. */
function extractMany<T extends string>(
  message: string,
  patterns: [RegExp, T][]
): T[] {
  const found: { value: T; index: number }[] = []
  for (const [pattern, value] of patterns) {
    const match = message.match(pattern)
    if (match?.index != null) found.push({ value, index: match.index })
  }
  return found.sort((a, b) => a.index - b.index).map((entry) => entry.value)
}

/** Rough $ amount matcher: "$120k", "120000", "150k" — used for pay range phrases. */
function extractPayRange(message: string): {
  payMin: number | null
  payMax: number | null
} {
  const rangeMatch = message.match(
    /\$?(\d{2,3})\s?k?\s*(?:-|to|–)\s*\$?(\d{2,3})\s?k/i
  )
  if (rangeMatch) {
    return {
      payMin: Number(rangeMatch[1]) * 1000,
      payMax: Number(rangeMatch[2]) * 1000,
    }
  }

  const minMatch = message.match(/(?:over|above|at least|\$)\s?(\d{2,3})\s?k\+?/i)
  if (minMatch) {
    return { payMin: Number(minMatch[1]) * 1000, payMax: null }
  }

  return { payMin: null, payMax: null }
}

function extractLocations(message: string): string[] {
  return extractMany(message, CITY_ALIASES)
}

function stripMatchedPhrases(message: string): string {
  const allPatterns = [
    ...EXPERIENCE_LEVEL_KEYWORDS,
    ...JOB_TYPE_KEYWORDS,
    ...WORKPLACE_TYPE_KEYWORDS,
    ...CITY_ALIASES,
  ].map(([pattern]) => pattern)

  let remainder = message
  for (const pattern of allPatterns) {
    remainder = remainder.replace(new RegExp(pattern, "gi"), " ")
  }

  // Punctuation left behind by removed phrases (e.g. "Denver, SF, or remote"
  // -> ", , or") isn't caught by the `\b`-anchored word regex below, so
  // strip it separately before the noise-word pass.
  remainder = remainder.replace(/[,.]/g, " ")

  const noise =
    /\b(show\s?me|find\s?me|find|search\s?for|search|jobs?|roles?|positions?|in|or|and)\b/gi
  remainder = remainder.replace(noise, " ")

  return remainder.replace(/\s+/g, " ").trim()
}

/** Parses free text into a partial `JobSearchFilters`. See module doc above. */
export function parseJobQueryLocally(
  message: string
): Partial<JobSearchFilters> {
  const trimmed = message.trim()
  if (!trimmed) return {}

  const { payMin, payMax } = extractPayRange(trimmed)
  const result: Partial<JobSearchFilters> = {
    locations: extractLocations(trimmed),
    experienceLevels: extractMany(trimmed, EXPERIENCE_LEVEL_KEYWORDS),
    jobTypes: extractMany(trimmed, JOB_TYPE_KEYWORDS),
    workplaceTypes: extractMany(trimmed, WORKPLACE_TYPE_KEYWORDS),
    payMin,
    payMax,
    keywords: stripMatchedPhrases(trimmed),
  }

  return result
}

/** Human-readable summary of a parsed filter patch, for the assistant's reply bubble. */
export function describeExtractedFilters(
  filters: Partial<JobSearchFilters>
): string[] {
  const parts: string[] = []

  if (filters.keywords) parts.push(`"${filters.keywords}"`)
  filters.experienceLevels?.forEach((level) =>
    parts.push(formatExperienceLevel(level))
  )
  filters.jobTypes?.forEach((type) => parts.push(formatJobType(type)))
  filters.workplaceTypes?.forEach((type) => parts.push(formatWorkplaceType(type)))
  filters.locations?.forEach((location) => parts.push(location))
  if (filters.payMin != null || filters.payMax != null) {
    if (filters.payMin != null && filters.payMax != null) {
      parts.push(`$${filters.payMin / 1000}k–$${filters.payMax / 1000}k`)
    } else if (filters.payMin != null) {
      parts.push(`$${filters.payMin / 1000}k+`)
    }
  }

  return parts
}
