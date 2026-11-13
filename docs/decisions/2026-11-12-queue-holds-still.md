# The Queue holds still: values in place, places behind a bar, actions on the card's page (2026-11-12)

**Status:** agreed with Paul on 2026-11-12 from the mockups; the design is TD-1558 (§4.5 screen 12 *The page
holds still*, *Previews*, *The card's page*, *Addresses*), built by TD-1761, TD-1762 and TD-1763.

## The problem

The Queue re-reads on every `queue` event, whenever the Inbox's counts move, and on a 30 s poll, about every 10 s on a busy day
(2026-11-07). Each re-read replaced the card lists whole (`lists.innerHTML = …`) and then reopened the menus and
folds that had been open. Cards re-ordered, changed group and jumped while Paul read and pressed. Once, an
**Answer…** sent its words to another card's ask (TD-1555, cured by binding the box at the press). The movement
was still there.

## What others do

A survey, by a Sonnet research agent on 2026-11-11. The sources are snippet-level, and the facts below are the
ones it checked.

- **A "new posts" bar.** X/Twitter stopped auto-loading new posts on the web in November 2021. A bar loads them
  on a press, so the timeline does not change under the reader
  ([Business Insider](https://www.businessinsider.in/tech/news/twitter-stops-auto-loading-new-tweets-on-web/articleshow/87731899.cms)).
- **Pause on hover or engagement.** Trading screens freeze a ladder under the pointer (NinjaTrader's forum).
  Their users ask that positions freeze but values stay live. Atoti puts a pause on each widget.
- **WCAG 2.2.2, Pause, Stop, Hide** (Level A). Content that updates on its own beside other content needs a way
  to pause it, or to control when it updates; one control for the page is better than one per element
  ([W3C](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide)).
- **Scroll anchoring.** Browsers keep the visible content in place when content above it changes
  ([MDN `overflow-anchor`](https://developer.mozilla.org/docs/Web/CSS/overflow-anchor)). A browser anchors on a
  node that survives, so an `innerHTML` swap defeats it.
- **Layout shift.** Unexpected shifts make people press the wrong thing
  ([web.dev CLS](https://web.dev/articles/cls)).
- **Morphing instead of swapping.** Turbo 8's page refreshes and htmx use idiomorph, which keeps nodes matched
  by id, so focus, folds and form state survive
  ([Turbo](https://turbo.hotwired.dev/handbook/page_refreshes),
  [idiomorph](https://github.com/bigskysoftware/idiomorph/)).
- **FLIP** (First, Last, Invert, Play). A move is animated from the old place to the new one, so the eye can
  follow it ([Aerotwist](https://aerotwist.com/blog/flip-your-animations/)).

## The decision

There are two problems, and each gets its own fix:

1. **Values change in place.** A re-read patches words, pills and counts into the nodes already drawn, found by
   key. An item that went keeps its place, marked *gone — refresh*.
2. **Places wait.** Cards that move, arrive or leave are counted in an always-drawn bar (*1 new ask for you · 2
   cards moved — Refresh*). **Refresh** draws the moves, which slide to their places. The person's own actions
   draw at once. The card under the pointer or focus holds. A hidden page draws whole.

On top of these, Paul's own direction: **the Queue reads, and a card's page acts.** Each item on the Queue is a
one-line preview carrying only its one-press answers (the recommended one, an `act`'s Done, a permission's
Allow/Deny, a lone Open). Every box, choice and menu is on `/card/<id>`, a page that holds still, the whole page
holding while a box is open. Links written as `/queue?card=…` redirect there. `/queue#TD-n` stays the Queue's
*where is TD-n*.

## Choices made with Paul

- The Queue keeps the one-press answers (Go on a recommended answer, and the others above) rather than none.
- The card's page is a page of its own (`/card/<id>`), not a panel over the Queue.
- A new ask for the person is counted in the bar, first and in amber, and moves nothing.
- The bar is always drawn, reading *up to date* when nothing waits.

## Not chosen

- **A fully read-only Queue.** It costs a page visit for each Go. A held list keeps the one-press answer safe.
- **The Queue fixes without a card's page.** That still answers on a list that changes underneath.
- **Freezing the whole page while the person is on it.** Trading users report that it hides values. Only the
  card under the pointer holds.
- **A pause toggle.** The bar is the page's one pause (WCAG 2.2.2): nothing moves until it is pressed.
