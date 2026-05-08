# MSI Blue Template — Slide Deck

HTML/CSS/JS slide deck implementation generated from a Claude Design handoff bundle.

## Files

- `index.html` — entry shell; loads styles and slide fragments, then bootstraps the deck
- `styles.css` — all slide styling (16:9 layout, brand palette, motifs, etc.)
- `deck.js` — slide navigation (keyboard, click, hash, viewport scaling)
- `slides-a.html` — slides 1–34 (Cover → Stakeholders intro)
- `slides-b.html` — slides 35–68 (Stakeholder messages → Translations)

## Run locally

The HTML uses `fetch()` to load the slide fragments, so it must be served (not opened via `file://`):

```
cd blue-template
python3 -m http.server 8000
```

Then open <http://localhost:8000/>.

## Controls

- ←/→, PgUp/PgDn, Space — navigate slides
- Home / End — first / last
- Click left/right halves — prev/next
- `#N` URL hash — deep-link to slide N

## Notes

- Slide 6 (Framework: Purpose) is a custom version inspired by, but distinct from, the original layout.
- The "M" mark is a stylized stand-in (not the trademarked Motorola logo).
- A photo placeholder appears on slide 12 / 20 since no image assets shipped with the bundle.
