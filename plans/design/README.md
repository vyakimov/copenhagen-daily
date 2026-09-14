# Broadsheet design notes

Working mockups for block 3. `device.html` renders three 1872 × 1404 compositions (`?v=A`, `?v=B`, `?v=C`); `web.html` is the web edition of the same day as composition B. They are design references for the templates, not production templates. Fonts load from Google Fonts here only; production bundles them locally. The production stylesheets in `publisher/assets/css/` are authoritative on type and tokens; the mockups are references for geometry and composition.

Render a composition with headless Chrome:

```
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu \
  --hide-scrollbars --force-device-scale-factor=1 --window-size=1920,1500 \
  --screenshot=/tmp/A.png "file://$PWD/plans/design/device.html?v=A"
```

## Tokens

| Token | Device | Web |
|---|---|---|
| Paper | `#ffffff` | `#f7f6f3` |
| Ink / secondary / tertiary | `#000000` / `#333333` / `#555555` | `#000000` / `#2b2b2b` / `#5a5a5a` |
| Rule / hairline / fill | `#111111` / `#bbbbbb` / `#dddddd` | `#111111` / `#c8c6c0` / `#e9e7e2` |
| Accent | none | `#8a1c1c`, links and pull-quote bar only |
| Display face | Newsreader (variable, optical sizes): 800 masthead, 600 lead headline, 700 secondary headlines, 500 figures, italic quotes and decks | same |
| Text face | Newsreader 400 at text optical size; Libre Franklin (variable) capitals for kickers, datelines, source rows, citations, navigation | same |
| Body size | 30 px / 1.42 (minimum 26 px, briefs) | 19 px / 1.5 |
| Margins / gutter | 64 px / 36 px | 40 px / 32 px |

Device greys are chosen so every colour maps to one of the 16 levels without dithering: fills sit at levels 13 and 14, hairlines at 11, secondary ink at 3, and text is pure black on pure white.

## Story roles

| Role | Count per edition | Anatomy |
|---|---|---|
| H1 lead | exactly one | kicker, display headline 72–88 px, italic deck, optional callout, optional body (one or two columns, drop cap when two), source row |
| H2 secondary | 0–4 per page | kicker, 36–44 px text-face headline, brief or standard body, optional callout, source row |
| H3 brief | 0–8 per page | 31 px headline, one-line lede |

Callouts belong to a story, never float alone. Every callout carries attribution in the story's source row, and quotes name the speaker and the publisher that reported them.

| Callout | Use | Device rendering |
|---|---|---|
| `quote` | a spoken or written sentence worth lifting | 6 px left rule, display italic 38–46 px, speaker line |
| `figure` | one number that is the story | display 96 px numeral between a 3 px and a 1 px rule, italic label |
| `facts` | two to four short bullets | level-14 fill, 3 px top rule, dashes |
| `box` | a single phrase to set apart | level-13 fill, small-caps label over bold phrase |
| `timeline` | dated sequence, two to four rows | 1 px top rule, bold dates in a two-column list |

Other elements the compositor may use: masthead ears (edition name and cutoff on the left, a short "Inside" or weather line on the right), an edition number, a fleuron between the lead and the secondary band, vertical rules between columns, a full-width rule above a briefs strip, and page folio with edition.

## Compositions

```
A  lead-wide             B  lead-tall              C  lead-centred
+--------------------+   +-------------+------+   +---------------+----+
| H1 + deck          |   | H1 + deck   | H2   |   |   H1 centred  | H3 |
+------+------+------+   | quote       +------+   |    fleuron    | H3 |
| H2   | H2   | H2   |   | body 2 col  | H2   |   +---+---+---+---+ H3 |
+------+------+------+   |             | fig. |   |H2 |H2 |H2 |H2 | H3 |
| H3 | H3 | H3 | H3  |   |             |      |   |   |   |   |   | H3 |
+--------------------+   +-------------+------+   +---+---+---+---+----+
```

The mockups show preferred densities: A has 2–3 H2 and 3–4 H3, B has 1–3 H2 and no H3, and C has 3–4 H2 and 4–6 H3. Production occupancy limits are A: 0–3/0–4, B: 0–3/0, C: 0–4/0–6. Supporting bands can be empty; remove their rules and retain whitespace without filler. The lead alone and lead-plus-one-brief are required sparse fixtures. Callouts may occupy lead/secondary slots, subject to actual measurement. A slot uses the first approved candidate or none; release 1 does not restore dropped callouts.

An early physical-device typography sheet and one provisional composition validate body, briefs,
attribution, rules, and every callout kind before all device layouts are frozen. Explicit font weights
must match the vendored faces; the existing HTML remains a design reference, not a production baseline.
Retain new baselines after that trial. Type sizes may differ by declared role/composition token, but
the renderer never scales them in response to copy length. Variation comes from composition, counts,
and callouts with those tokens, margins, rules, and palette unchanged.

## Previews

`preview/` holds the rendered pages: `device-{A,B,C}.png` are the 1872 × 1404 masters, `device-{A,B,C}-16gray.png` are the same pages quantized to 16 evenly spaced grey levels with no dithering (16 levels used, text edges are the only pixels that moved), and `web-desktop.png` / `web-narrow.png` show the web edition. The production pipeline writes true 4-bit grayscale PNG with ImageMagick; the preview files are 8-bit renderings of the same levels.
