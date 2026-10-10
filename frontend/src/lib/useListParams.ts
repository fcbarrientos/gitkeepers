import { useSearchParams } from "react-router-dom";

/** Search text, paging offset and other list filters, kept in the URL so Back works. */
export function useListParams() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const offset = Math.max(0, Number(params.get("offset")) || 0);
  const update = (changes: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setParams(next);
  };
  return {
    params,
    q,
    offset,
    update,
    setQuery: (text: string) => update({ q: text, offset: undefined }),
    setOffset: (value: number) => update({ offset: value ? String(value) : undefined }),
  };
}
