/**
 * Serialize a JSON-LD object for an inline `<script type="application/ld+json">`.
 *
 * Card JSON-LD carries upstream strings (titles, agencies, filenames), so the
 * payload must not contain anything an HTML parser could read as markup inside
 * a script element. Escaping only `</script` is not enough: `<!--` and
 * `<script` can move the parser into the script-data escaped states, where the
 * real closing tag no longer ends the element. Every `<`, `>` and `&` is
 * therefore written as its JSON `\u` escape, as are U+2028 and U+2029. JSON
 * parsers read these back to the identical characters, so the data is
 * unchanged.
 */

const ESCAPES: Record<string, string> = {
  "<": "\\u003c",
  ">": "\\u003e",
  "&": "\\u0026",
  "\u2028": "\\u2028",
  "\u2029": "\\u2029",
};

export function safeJsonLd(value: unknown): string {
  return JSON.stringify(value).replace(/[<>&\u2028\u2029]/g, (ch) => ESCAPES[ch]);
}
