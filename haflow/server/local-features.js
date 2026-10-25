// Local-only additions. Existing Flow graphs and HA entity identities stay intact.
import crypto from 'node:crypto'

export function variableValue(type, value) {
  if (type === 'boolean') {
    if (value === true || value === 'true') return true
    if (value === false || value === 'false') return false
    throw new Error('Choose true or false.')
  }
  if (type === 'number') {
    if (!['string', 'number'].includes(typeof value) || String(value).trim() === '' || !Number.isFinite(Number(value))) throw new Error('Enter a finite number.')
    return Number(value)
  }
  if (type !== 'text' || typeof value !== 'string' || value.length > 2000) throw new Error('Text variables allow up to 2,000 characters.')
  return value
}

export function variableEntity(variable) {
  return { entity_id: `haflow_variable.${variable.id}`, state: String(variable.value), last_changed: variable.updatedAt, last_updated: variable.updatedAt,
    domain: 'haflow_variable', catalogType: 'entity', areaName: 'Global variables', deviceType: 'Variable', friendlyName: variable.name,
    valueOptions: variable.type === 'boolean' ? ['true', 'false'] : [], attributes: { friendly_name: variable.name, variable_type: variable.type } }
}

export function normalizePhrase(value) {
  return String(value || '').normalize('NFKC').toLocaleLowerCase('en').trim().replace(/[.!?,;:]+$/u, '').replace(/\s+/g, ' ').trim()
}

export function validatePhrase(value) {
  const phrase = normalizePhrase(value)
  if (!phrase || phrase.length > 100 || !/[\p{L}\p{N}]/u.test(phrase) || /[{}[\]*]/u.test(phrase)) throw new Error('Enter an exact voice phrase, up to 100 characters, without wildcards.')
  return phrase
}

export function reachable(flow, start) {
  const found = new Set(), pending = [start]
  const links = new Map()
  for (const edge of flow.edges || []) {
    if (!links.has(edge.source)) links.set(edge.source, [])
    links.get(edge.source).push(edge.target)
  }
  while (pending.length) {
    const id = pending.pop()
    if (found.has(id)) continue
    found.add(id)
    pending.push(...(links.get(id) || []))
  }
  return found
}

export function overlapping(first, second) {
  return [...first].some(id => second.has(id))
}

// Ignore presentation-only changes when deciding whether a pending hold's
// captured graph is stale. Functional changes must discard the old callback.
export function flowExecutionSignature(flow) {
  const cosmetic = new Set(['label', 'entityDisplayName', 'entityContext', 'actionEntities', 'entitySuggestions', 'runtimeStatus', 'lastExecutedAt', 'remainingMs', 'validation', 'suppressValidation'])
  const stable = value => Array.isArray(value) ? value.map(stable) : value && typeof value === 'object'
    ? Object.fromEntries(Object.entries(value).sort(([a],[b]) => a.localeCompare(b)).map(([key,val]) => [key, stable(val)])) : value
  return JSON.stringify(stable({
    nodes: (flow.nodes || []).map(n => ({ id: n.id, data: Object.fromEntries(Object.entries(n.data || {}).filter(([key]) => !cosmetic.has(key))) })).sort((a,b) => a.id.localeCompare(b.id)),
    edges: (flow.edges || []).map(e => ({ source: e.source, target: e.target, sourceHandle: e.sourceHandle || '', targetHandle: e.targetHandle || '' })).sort((a,b) => JSON.stringify(a).localeCompare(JSON.stringify(b))),
  }))
}

export function importVariables(input, existing, importedFlows) {
  if (input === undefined) return { variables: existing, flows: importedFlows }
  if (!Array.isArray(input) || input.length > 256) throw new Error('Invalid variable backup.')
  const variables = [...existing], mappings = new Map(), ids = new Set()
  for (const item of input) {
    if (!item || typeof item.id !== 'string' || !/^[a-zA-Z0-9_-]{1,80}$/.test(item.id) || ids.has(item.id) || typeof item.name !== 'string' || !item.name.trim() || item.name.length > 80) throw new Error('Invalid variable in backup. Nothing was imported.')
    ids.add(item.id)
    const value = variableValue(item.type, item.value)
    const same = existing.find(v => v.id === item.id && v.name === item.name && v.type === item.type && v.value === value)
    if (same) continue
    const id = variables.some(v => v.id === item.id) ? crypto.randomUUID() : item.id
    let name = item.name.trim(), suffix = 2
    while (variables.some(v => v.name.toLowerCase() === name.toLowerCase())) name = `${item.name.trim()} (${suffix++})`
    mappings.set(`haflow_variable.${item.id}`, `haflow_variable.${id}`)
    variables.push({ id, name, type: item.type, value, updatedAt: new Date().toISOString() })
  }
  if (variables.length > 256) throw new Error('Up to 256 global variables are supported.')
  // Rewrite only declared variable references, never free text or HA identities.
  const rewrite = value => {
    if (Array.isArray(value)) return value.map(rewrite)
    if (!value || typeof value !== 'object') return value
    return Object.fromEntries(Object.entries(value).map(([key, val]) => [key,
      ['entityId', 'variableId', 'expectedVariableId'].includes(key) && typeof val === 'string' ? mappings.get(val) || val : rewrite(val)]))
  }
  return { variables, flows: importedFlows.map(rewrite) }
}
