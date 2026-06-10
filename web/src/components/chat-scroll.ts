/**
 * Auto-scroll stickiness for the streaming chat transcript.
 *
 * Decides whether subsequent streamed deltas should keep pinning the
 * transcript to its bottom (user is reading "live" at the tail) or leave
 * the user where they are (user scrolled up to re-read earlier content).
 *
 * Extracted from ChatIsland so the policy is unit-testable without a
 * DOM. The previous behavior — unconditional `scrollTop = scrollHeight`
 * on every `messages` change — fought users who tried to scroll back
 * during a long streaming response.
 */

/** Default px tolerance for "close enough to bottom counts as at-bottom". */
const DEFAULT_STICKY_TOLERANCE_PX = 50;

/**
 * Returns true if the scroll position is at (or within `tolerance` px of)
 * the bottom of the container.
 *
 * @param scrollHeight  Total scrollable height (clientHeight + offscreen).
 * @param scrollTop     Current scroll position.
 * @param clientHeight  Visible viewport height.
 * @param tolerance     Px threshold; distance < tolerance counts as sticky.
 *                      Defaults to 50.
 *
 * Boundary is strict-less-than, so `dist === tolerance` is NOT sticky.
 * Negative distance (overscroll, content shorter than viewport) clamps
 * to sticky.
 */
export function shouldStickToBottom(
  scrollHeight: number,
  scrollTop: number,
  clientHeight: number,
  tolerance: number = DEFAULT_STICKY_TOLERANCE_PX,
): boolean {
  const distFromBottom = scrollHeight - scrollTop - clientHeight;
  return distFromBottom < tolerance;
}
