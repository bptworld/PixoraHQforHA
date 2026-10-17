// Accept the original HAFlow backup and single-flow export formats.
export function prepareFlowImport(input) {
  const items = Array.isArray(input?.flows) ? input.flows
    : Array.isArray(input?.nodes) && Array.isArray(input?.edges) ? [{flow: input}] : []
  if (!items.length || items.length > 500) throw new Error('Choose a HAFlow backup or exported Flow JSON file (up to 500 flows).')
  return items.map((item, index) => {
    const flow = item?.flow ?? item
    const meta = item?.meta ?? item
    if (!Array.isArray(flow?.nodes) || !Array.isArray(flow?.edges)) throw new Error(`Flow ${index + 1} is missing its nodes or connections. Nothing was imported.`)
    const ids = new Set()
    for (const node of flow.nodes) {
      if (!node || typeof node.id !== 'string' || !node.id || ids.has(node.id) || !node.data || typeof node.data !== 'object' || Array.isArray(node.data)) throw new Error(`Flow ${index + 1} contains an invalid or duplicate node. Nothing was imported.`)
      ids.add(node.id)
    }
    const edgeIds = new Set()
    for (const edge of flow.edges) {
      if (!edge || typeof edge.id !== 'string' || edgeIds.has(edge.id) || !ids.has(edge.source) || !ids.has(edge.target)) throw new Error(`Flow ${index + 1} contains an invalid connection. Nothing was imported.`)
      edgeIds.add(edge.id)
    }
    return {flow, meta: {...meta, name: String(meta?.name || flow.name || 'Imported Flow').slice(0, 200), paused: true}}
  })
}
