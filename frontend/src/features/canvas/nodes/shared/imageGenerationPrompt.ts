export function dedupeImageGenerationPrompt(
  upstreamText: string,
  nodePrompt: string,
): string {
  const upstream = upstreamText.trim();
  const node = nodePrompt.trim();
  if (!upstream) return node;
  if (!node) return upstream;
  const normalize = (value: string) => value.replace(/\s+/g, " ").trim();
  const normalizedUpstream = normalize(upstream);
  const normalizedNode = normalize(node);
  if (
    normalizedUpstream === normalizedNode ||
    normalizedNode.includes(normalizedUpstream)
  ) {
    return node;
  }
  return `${upstream}\n\n${node}`;
}
