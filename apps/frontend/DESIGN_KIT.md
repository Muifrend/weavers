# weavers — Design Kit

The whole app is built from one source of truth: the **left sidebar**. It is clean,
editorial, and light — white surfaces, a single confident red accent, navy ink, and a
Georgia-italic display face. Every other surface is designed to feel like it belongs next
to that sidebar.

Tokens live in [`src/styles/tokens.css`](src/styles/tokens.css); the theme that consumes
them is [`src/styles.css`](src/styles.css).

---

## Palette

| Token | Hex | Use |
| --- | --- | --- |
| `--paper` | `#ffffff` | Cards, sidebar, primary surfaces |
| `--canvas` | `#f7f9fa` | App background behind cards |
| `--panel-soft` | `#f1f4f6` | Hover / active subtle fills, neutral pills |
| `--navy` | `#0f2530` | Inverted surfaces (status panel, score orb) |
| `--ink` | `#102331` | Primary text + headlines |
| `--ink-soft` | `#244459` | Body / secondary text |
| `--ink-muted` | `#8b9aa5` | Labels, meta, captions |
| `--ink-invert` | `#fdfaf4` | Text on navy |
| `--line` | `#d9dee2` | Hairline borders & dividers |
| `--accent` | `#ff4438` | **The weavers red** — one accent, used sparingly |
| `--accent-strong` | `#e23a2f` | Accent hover/pressed |
| `--accent-soft` | `rgba(255,68,56,.10)` | Accent tint (focus ring, pills, badges) |

**Sentiment / data viz:** `--negative #ff4438`, `--mixed #d9a441`, `--positive #3f8f5b`
(each with a `-soft` tint). Status dots: `--status-busy` (blue), `--status-ok` (green),
`--status-fail` (red), `--status-idle` (grey).

---

## Type

- **Display / headlines:** `--font-serif` (Georgia), *italic*, tight tracking. Used for the
  brand, `h1`, `h2`, and blockquotes. This is the editorial signature.
- **Body / UI:** `--font-sans` (Avenir Next → system sans). `h3`/`h4` are sans + bold.
- **Eyebrow:** `.wv-eyebrow` / `.eyebrow` — uppercase, 0.74rem, 0.16em tracking, accent color.

Scale: h1 `clamp(2.2–3.2rem)`, h2 `clamp(1.5–2.1rem)`, h3 `1.12rem`, body `1rem`,
meta `0.8–0.86rem`.

---

## Spacing, radii, elevation

- Spacing scale: `--space-1..7` = `4 / 8 / 12 / 16 / 24 / 32 / 48`px.
- Radii: `--radius-sm 8`, `--radius-md 14` (inputs, cards), `--radius-lg 20` (panels),
  `--radius-pill`.
- Elevation: `--shadow-card` for resting cards, `--shadow-pop` for overlays. Keep shadows
  faint — the look is defined by hairline `--line` borders, not heavy drop shadows.

---

## Primitives (classes)

| Class | What it is |
| --- | --- |
| `.wv-card` / `.panel` | White surface, hairline border, `--radius-lg`, soft shadow |
| `.wv-button` | Primary action — accent fill, white text |
| `.wv-button--ghost` | Secondary action — white fill, hairline border |
| `.wv-input` / `.wv-number` / `.wv-select` | Form fields; accent focus ring |
| `.toggle` | Inline checkbox row |
| `.wv-eyebrow` | Section kicker label |
| `.pill` / `.tag-row span` | Small status/segment chips |
| `.status-panel` | Navy inverted info card (`.status-dot` reflects run state) |

Within `.simulation-app`, the bare `button`, `input`, `select`, `textarea`, `label`, and
`h1–h4` elements are already styled to the primitives above, so most markup needs no extra
classes.

---

## Do / Don't

- **Do** keep one accent. Red signals action and alarm (primary buttons, active tab marker,
  red flags, negative sentiment) — nothing else should compete with it.
- **Do** lead sections with a serif-italic headline + an uppercase accent eyebrow.
- **Do** separate with hairline `--line` borders before reaching for shadow.
- **Don't** reintroduce dark panels, cream-on-charcoal text, or the old clay/gold palette.
- **Don't** use serif for body or UI controls — serif is for display + quotes only.
- **Don't** add new one-off colors; extend `tokens.css` if a genuinely new role appears.
