import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { commitFormulas, getFormulas, getModelMapping, validateFormula } from '../../api/whatIf'
import { Callout } from '../../components/Callout'
import type { FormulaRow, FormulaValidateResult } from '../../api/types'

const OPERATORS = ['+', '-', '*', '/', '^', '(', ')']
const FUNCTIONS = ['sqrt(', 'log(', 'log10(', 'exp(', 'abs(', 'min(', 'max(', 'pow(', 'round(']

interface FormulaEditorProps {
  predictedParameter: string
  onBack: () => void
}

// Model Definition's "Define Formula" action for First-Principle rows (see
// ModelMappingEditor.tsx) -- lets the user type a math expression for a
// parameter instead of relying on a hardcoded plant plug-in function.
// Evaluated server-side by src/whatif/formula_eval.py's safe, whitelisted
// AST evaluator (never Python's eval()/exec()). Saving auto-populates this
// parameter's own Input parameter_1..8 in Model Definition with whatever
// tags/parameters the formula references (backend commit_formulas ->
// _sync_formula_inputs), so the engine's dependency graph schedules it
// correctly -- no separate manual step needed here.
export function FormulaEditor({ predictedParameter, onBack }: FormulaEditorProps) {
  const queryClient = useQueryClient()
  const formulasQuery = useQuery({ queryKey: ['whatif-formulas'], queryFn: getFormulas })
  const mappingQuery = useQuery({ queryKey: ['whatif-model-mapping'], queryFn: getModelMapping })
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const [formula, setFormula] = useState('')
  const [hydrated, setHydrated] = useState(false)

  // One-time hydration from the saved formula once it's loaded -- guarded so
  // it never re-runs and clobbers in-progress typing once loaded (including
  // right after this component's own Save success invalidates the query).
  useEffect(() => {
    if (hydrated || !formulasQuery.data) return
    const existing = formulasQuery.data.find((r) => (r['Predicted parameter'] ?? '').trim() === predictedParameter)
    setFormula(existing?.Formula ?? '')
    setHydrated(true)
  }, [hydrated, formulasQuery.data, predictedParameter])

  const [validation, setValidation] = useState<FormulaValidateResult | null>(null)
  const [validating, setValidating] = useState(false)

  // Syntax/whitelist-only check -- no historian row needed, so this is safe
  // to run on every pause in typing, well before Save.
  useEffect(() => {
    if (!formula.trim()) {
      setValidation(null)
      return
    }
    setValidating(true)
    const handle = setTimeout(() => {
      validateFormula(formula)
        .then(setValidation)
        .finally(() => setValidating(false))
    }, 400)
    return () => clearTimeout(handle)
  }, [formula])

  const commitMutation = useMutation({
    mutationFn: async (nextFormula: string) => {
      const rows = await getFormulas()
      const others = rows.filter((r) => (r['Predicted parameter'] ?? '').trim() !== predictedParameter)
      const updated: FormulaRow[] = [...others, { 'Predicted parameter': predictedParameter, Formula: nextFormula }]
      return commitFormulas(updated)
    },
    onSuccess: (rows) => {
      queryClient.setQueryData(['whatif-formulas'], rows)
      // The backend just wrote this parameter's referenced variables into
      // its Input parameter_1..8 cells -- refetch so Model Definition shows
      // them the moment we return.
      queryClient.invalidateQueries({ queryKey: ['whatif-model-mapping'] })
      onBack()
    },
  })

  function insertAtCursor(token: string) {
    const el = textareaRef.current
    if (!el) {
      setFormula((prev) => prev + token)
      return
    }
    const start = el.selectionStart ?? formula.length
    const end = el.selectionEnd ?? formula.length
    const next = formula.slice(0, start) + token + formula.slice(end)
    setFormula(next)
    const cursor = start + token.length
    requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(cursor, cursor)
    })
  }

  const availableNames = useMemo(() => {
    const tags = mappingQuery.data?.historian_tags ?? []
    const params = (mappingQuery.data?.rows ?? [])
      .map((r) => (r['Predicted parameter'] ?? '').trim())
      .filter((p) => p && p !== predictedParameter)
    return Array.from(new Set([...params, ...tags])).sort((a, b) => a.localeCompare(b))
  }, [mappingQuery.data, predictedParameter])

  const [nameFilter, setNameFilter] = useState('')
  const filteredNames = availableNames
    .filter((n) => n.toLowerCase().includes(nameFilter.toLowerCase()))
    .slice(0, 50)

  const canSave = !!formula.trim() && validation?.valid === true && !commitMutation.isPending

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <button className="chip" style={{ alignSelf: 'flex-start' }} onClick={onBack}>
        ← Back to Model Definition
      </button>

      <div>
        <h2 style={{ marginBottom: '0.25rem' }}>Formula Editor</h2>
        <p className="caption">
          Predicted Parameter: <code>{predictedParameter}</code> (First Principle) — define the math expression that
          computes its value from other tags/parameters.
        </p>
      </div>

      <div className="card" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <label>
          <div className="caption">Formula</div>
          <textarea
            ref={textareaRef}
            value={formula}
            onChange={(e) => setFormula(e.target.value)}
            rows={4}
            placeholder="e.g. TAG_A * 2 + sqrt(TAG_B) - 3"
            style={{ width: '100%', fontFamily: 'monospace', fontSize: '0.95rem', boxSizing: 'border-box' }}
          />
        </label>

        <div>
          <div className="caption" style={{ marginBottom: '0.4rem' }}>
            Operators
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            {OPERATORS.map((op) => (
              <button key={op} className="chip" onClick={() => insertAtCursor(` ${op} `)}>
                {op}
              </button>
            ))}
          </div>
        </div>

        <div>
          <div className="caption" style={{ marginBottom: '0.4rem' }}>
            Functions
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            {FUNCTIONS.map((fn) => (
              <button key={fn} className="chip" onClick={() => insertAtCursor(fn)}>
                {fn.replace('(', '')}
              </button>
            ))}
          </div>
        </div>

        <div>
          <div className="caption" style={{ marginBottom: '0.4rem' }}>
            Insert a tag or Predicted Parameter
          </div>
          <input
            type="text"
            placeholder="Search…"
            value={nameFilter}
            onChange={(e) => setNameFilter(e.target.value)}
            style={{ width: '100%', marginBottom: '0.5rem', boxSizing: 'border-box' }}
          />
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', maxHeight: 160, overflowY: 'auto' }}>
            {filteredNames.map((name) => (
              <button key={name} className="chip" onClick={() => insertAtCursor(name)}>
                {name}
              </button>
            ))}
            {filteredNames.length === 0 && <span className="caption">No matches.</span>}
          </div>
        </div>

        {validating && <p className="caption">Validating…</p>}
        {validation && !validation.valid && <Callout variant="error">{validation.errors.join(' ')}</Callout>}
        {validation?.valid && (
          <Callout variant="success">
            Valid — references: {validation.variables.length ? validation.variables.join(', ') : 'none'}
          </Callout>
        )}

        <div>
          <button disabled={!canSave} onClick={() => commitMutation.mutate(formula)}>
            {commitMutation.isPending ? 'Saving…' : '💾 Save Formula'}
          </button>
        </div>
        {commitMutation.isError && <Callout variant="error">Failed to save the formula.</Callout>}
      </div>
    </div>
  )
}
