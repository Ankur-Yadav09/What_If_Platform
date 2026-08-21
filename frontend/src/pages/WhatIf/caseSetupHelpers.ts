// Section-scoping helpers for the Case Setup wizard, ported from
// Scripts/Whatif_streamlit_dashboard_updated.py's allowed_sections_upto /
// _in_section_scope / _cs_scoped_tag_options / _cs_model_input_options /
// infer_section (mirrors src/whatif/wizard.py's Python port of the same
// logic) — kept here as plain TS so both the wizard shell and individual
// step editors can filter/prioritize consistently.
import type { MvDvCvTagRow, PiMappingRow } from '../../api/types'

const SECTION_KEYWORDS: [string, string[]][] = [
  ['CGC', ['cgc', 'cracked gas']],
  ['PRC', ['prc', 'propylene']],
  ['ERC', ['erc', 'ethylene refrig']],
  ['Furnace', ['furnace', 'coil', 'cot', 'cip']],
  ['Quench', ['quench']],
  ['Cold', ['cold', 'demethaniser', 'demethanizer', 'deethaniser', 'deethanizer']],
]

export function inferSection(description: string | undefined | null): string {
  const text = (description ?? '').toString().toLowerCase()
  for (const [section, keywords] of SECTION_KEYWORDS) {
    if (keywords.some((kw) => text.includes(kw))) return section
  }
  return ''
}

/** Every section at or before `targetSection` in `sectionOrder` (upstream + target itself). */
export function allowedSectionsUpto(sectionOrder: string[], targetSection: string | null | undefined): string[] {
  if (!sectionOrder.length || !targetSection) return sectionOrder
  const norm = sectionOrder.map((s) => s.trim().toLowerCase())
  const t = targetSection.trim().toLowerCase()
  const idx = norm.indexOf(t)
  if (idx === -1) return sectionOrder
  return sectionOrder.slice(0, idx + 1)
}

export function excludedSections(sectionOrder: string[], targetSection: string | null | undefined): string[] {
  const allowed = new Set(allowedSectionsUpto(sectionOrder, targetSection).map((s) => s.toLowerCase()))
  return sectionOrder.filter((s) => !allowed.has(s.toLowerCase()))
}

/** True if `section` (falling back to name-based inference from `fallbackText`
 * when blank) is one of `allowed` — blank/unclassified rows always pass. */
export function inSectionScope(section: string | undefined, allowed: Set<string>, fallbackText?: string): boolean {
  let sec = (section ?? '').trim().toLowerCase()
  if (!sec || sec === 'nan') {
    const guess = inferSection(fallbackText)
    if (guess) sec = guess.toLowerCase()
  }
  return !sec || sec === 'nan' || allowed.has(sec)
}

export function allowedSet(sectionOrder: string[], targetSection: string | null | undefined): Set<string> {
  return new Set(allowedSectionsUpto(sectionOrder, targetSection).map((s) => s.trim().toLowerCase()))
}

/** PI tag options (Generalized Description values — the historian's actual
 * column-name space, see backend/app/services/what_if_service.py's
 * get_tag_options fix) restricted to the active scope. */
export function scopedTagOptions(piRows: PiMappingRow[], allowed: Set<string>): string[] {
  if (allowed.size === 0) {
    return dedupe(piRows.map((r) => r['Generalized Description']).filter(Boolean))
  }
  return dedupe(
    piRows
      .filter((r) => inSectionScope(r.Section, allowed, r['Generalized Description']))
      .map((r) => r['Generalized Description'])
      .filter(Boolean),
  )
}

/** MV/DV/CV Tag List names, scoped to the active process scope, list order preserved. */
export function mvdvcvTagNames(mvdvcvRows: MvDvCvTagRow[], allowed: Set<string>): string[] {
  return dedupe(
    mvdvcvRows
      .filter((r) => inSectionScope(r.Section, allowed, r.GeneralizedDescription))
      .map((r) => r.GeneralizedDescription)
      .filter(Boolean),
  )
}

/** Every MV/DV/CV + PI tag name, completely unfiltered — MV/DV/CV tags
 * first (list order preserved), then every remaining PI tag. The baseline
 * "nothing hidden" list that modelInputOptionsForSection() below reorders
 * but never subtracts from. */
function allTagNames(piRows: PiMappingRow[], mvdvcvRows: MvDvCvTagRow[]): string[] {
  const mvTags = dedupe(mvdvcvRows.map((r) => r.GeneralizedDescription).filter(Boolean))
  const mvLower = new Set(mvTags.map((t) => t.toLowerCase()))
  const other = dedupe(piRows.map((r) => r['Generalized Description']).filter(Boolean)).filter(
    (t) => !mvLower.has(t.toLowerCase()),
  )
  return [...mvTags, ...other]
}

/** Model Mapping's per-row input-tag dropdown options: MV/DV/CV tags whose
 * own Section matches the row's chosen Section (or is upstream of it, per
 * the process-flow order — a PRC parameter legitimately depends on a CGC
 * tag, since CGC feeds into PRC) are bumped to the top of the list as the
 * prioritized/recommended choices. Every other tag — MV/DV/CV or PI, any
 * section — still follows afterward; nothing is ever hidden, only reordered
 * (an earlier version filtered non-matching tags out entirely, which made
 * already-saved cross-section values render as an inexplicable blank
 * selection). With no Section chosen, there's nothing to prioritize, so
 * it's just the complete list in its natural order. */
export function modelInputOptionsForSection(
  piRows: PiMappingRow[],
  mvdvcvRows: MvDvCvTagRow[],
  section: string | undefined,
  sectionOrder: string[] = [],
): string[] {
  const all = allTagNames(piRows, mvdvcvRows)
  const sec = (section ?? '').trim()
  if (!sec) return all

  const allowed = sectionOrder.length ? allowedSet(sectionOrder, sec) : new Set([sec.toLowerCase()])
  const priority = mvdvcvTagNames(mvdvcvRows, allowed)
  const priorityLower = new Set(priority.map((t) => t.toLowerCase()))
  const rest = all.filter((t) => !priorityLower.has(t.toLowerCase()))
  return [...priority, ...rest]
}

/** Ensures a row's already-saved value for a dropdown is always selectable,
 * even if it falls outside the computed options (a stray/typo'd tag that
 * doesn't match any known PI/MV-DV-CV description) — so an existing value
 * never silently renders as a blank selection. */
export function optionsWithCurrentValue(options: string[], current: string | undefined): string[] {
  const value = (current ?? '').trim()
  if (!value) return options
  const lower = value.toLowerCase()
  if (options.some((o) => o.toLowerCase() === lower)) return options
  return [value, ...options]
}

function dedupe(values: string[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const v of values) {
    const trimmed = v.trim()
    if (!trimmed || trimmed.toLowerCase() === 'nan') continue
    const key = trimmed.toLowerCase()
    if (!seen.has(key)) {
      seen.add(key)
      out.push(trimmed)
    }
  }
  return out
}
