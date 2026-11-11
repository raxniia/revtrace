export function Marked({ text }: { text: string }) {
  const parts = text.split("**");
  return <>{parts.map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : part))}</>;
}
