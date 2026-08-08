// Citation construction for /api/retrieve.
//
// Every retrieval lane (dense cosine, literal card_id, literal slug) turns
// an index row into a citation through `buildPassage`. The index and
// `pages.json` are built from the same corpus, so a row without a
// text-bearing page record means the two payloads have drifted — a stale
// row that survived a re-OCR, or a card that left the corpus. Emitting it
// anyway produces a citation with an empty title and snippet, which the
// chat model cites as a real source and the user sees as a blank card.
//
// So a miss is an explicit, logged skip: the remaining hits still answer
// the query, and a query whose hits all miss returns no passages rather
// than blanks.

/**
 * Build a citation from a retrieval hit, or return null if the hit can't
 * produce a usable one.
 *
 * `makeSnippetFn` is injected rather than imported from `retrieve.js` to
 * avoid a circular dependency.
 */
export function buildPassage({
  card_id,
  page,
  pageRec,
  query,
  score,
  makeSnippetFn,
}) {
  if (!pageRec) {
    logSkip(card_id, page, "no pages.json entry");
    return null;
  }
  const title = (pageRec.title || "").trim();
  const text = (pageRec.text || "").trim();
  if (!title) {
    logSkip(card_id, page, "pages.json entry has no title");
    return null;
  }
  if (!text) {
    logSkip(card_id, page, "pages.json entry has no text");
    return null;
  }
  const snippet = makeSnippetFn(pageRec.text, query);
  if (!snippet.trim()) {
    logSkip(card_id, page, "snippet is empty");
    return null;
  }
  return {
    card_id,
    page,
    title: pageRec.title,
    snippet,
    score,
    page_text: pageRec.text,
  };
}

function logSkip(card_id, page, reason) {
  console.warn(
    `retrieve: skipped citation ${card_id}-p${page} — ${reason}`,
  );
}
