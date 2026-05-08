import { useEffect, useMemo, useState } from "preact/hooks";
import MiniSearch from "minisearch";

interface PageDoc {
  id: string; // `${card_id}-p${page}`
  card_id: string;
  page: number;
  title: string;
  text: string;
}

interface Props {
  base: string;
}

type Status = "loading" | "missing" | "ready" | "error";

export default function SearchIsland({ base }: Props) {
  const [status, setStatus] = useState<Status>("loading");
  const [docs, setDocs] = useState<PageDoc[]>([]);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const url = `${base}/data/pages.json`;
    fetch(url)
      .then((r) => {
        if (r.status === 404) {
          setStatus("missing");
          return null;
        }
        if (!r.ok) throw new Error(`fetch ${url}: ${r.status}`);
        return r.json() as Promise<PageDoc[]>;
      })
      .then((d) => {
        if (d) {
          setDocs(d);
          setStatus("ready");
        }
      })
      .catch((err) => {
        console.error(err);
        setStatus("error");
      });
  }, [base]);

  const search = useMemo(() => {
    if (status !== "ready" || docs.length === 0) return null;
    const ms = new MiniSearch<PageDoc>({
      fields: ["title", "text"],
      storeFields: ["card_id", "page", "title"],
      idField: "id",
      searchOptions: {
        boost: { title: 2 },
        prefix: true,
        fuzzy: 0.2,
      },
    });
    ms.addAll(docs);
    return ms;
  }, [status, docs]);

  const results = useMemo(() => {
    if (!search || !query.trim()) return [];
    return search.search(query, { combineWith: "AND" }).slice(0, 50);
  }, [search, query]);

  return (
    <div class="space-y-4">
      {status === "loading" && (
        <p class="text-sm text-neutral-500">Loading OCR index…</p>
      )}
      {status === "missing" && (
        <div class="rounded-md border border-neutral-800 bg-neutral-925 p-4 text-sm text-neutral-400">
          <p class="font-medium text-neutral-200 mb-1">OCR pending</p>
          <p>
            The Tesseract pass hasn't completed yet (or the next deploy hasn't
            shipped the index). Once it's published as
            <code class="mx-1 text-neutral-300">/data/pages.json</code>
            this search will activate automatically.
          </p>
        </div>
      )}
      {status === "error" && (
        <p class="text-sm text-red-400">Failed to load search index.</p>
      )}
      {status === "ready" && search && (
        <>
          <div>
            <input
              type="search"
              value={query}
              onInput={(e) => setQuery((e.target as HTMLInputElement).value)}
              placeholder="search across all OCR'd pages…"
              class="w-full rounded-md bg-neutral-900 border border-neutral-800 px-3 py-2 text-sm focus:border-neutral-500 focus:outline-none"
              autofocus
            />
            <p class="mt-1 text-xs text-neutral-500">
              {docs.length.toLocaleString()} pages indexed across the corpus.
            </p>
          </div>
          {query.trim() && (
            <div class="text-xs text-neutral-500">
              {results.length} match{results.length === 1 ? "" : "es"}
              {results.length === 50 && " (capped)"}
            </div>
          )}
          <ul class="space-y-2">
            {results.map((r) => (
              <li class="rounded border border-neutral-800 bg-neutral-925 p-3 hover:border-neutral-600 transition-colors">
                <a href={`${base}/card/${r.card_id}#page-${r.page}`} class="block space-y-1">
                  <div class="text-xs text-neutral-500">
                    page {r.page} · score {r.score.toFixed(2)}
                  </div>
                  <div class="text-sm text-neutral-200 line-clamp-2">
                    {r.title}
                  </div>
                </a>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
