# Zoom handout — gluteal muscle area

`handout.json` is the draft handout: meta, agenda, one entry per slide (title,
body, speaker notes) and an appendix with the command cheat sheet, glossary and
FAQ. Edit the JSON, rebuild, and the deck follows.

It holds measurements from a real series and a local output path, so it is
**gitignored and never published** — this repository is public. Keep it (and any
backup of it) outside the repo's history.

Its shape, for rebuilding one from scratch:

```jsonc
{
  "meta":   { "title": "...", "output_dir": "out", "font": "BIZ UDGothic" },
  "agenda": [{ "title": "...", "minutes": 5 }],
  "slides": [
    // layout: title | bullets | steps | flow | image | table | closing
    { "id": "...", "layout": "bullets", "title": "...", "lead": "...",
      "bullets": [{ "text": "...", "level": 0 }],
      "footnote": "...", "notes": "speaker notes" }
  ],
  "appendix": { "commands": [], "glossary": [], "faq": [] }
}
```

Per layout: `steps` takes `steps[{label, command, detail}]`, `flow` takes
`items[{step, title, detail}]`, `image` takes `image` + `caption` (+ `bullets`
alongside), `table` takes `table{headers, rows}`, `title` takes `subtitle` +
`meta[]`.

```bash
npm install
npm run all          # template + deck
```

- `npm run template` — regenerates `template/handout_layouts.pptx`, the design:
  one prototype slide per layout (title, bullets, steps, flow, image, table,
  closing) with named shapes. Swap in a corporate template that uses the same
  shape names and the build keeps working.
- `npm run build` — pptx-automizer clones the prototype for each slide in
  `handout.json`, fills the named shapes, draws the content-dependent elements
  (pipeline boxes, figures) through pptxGenJS, and writes the speaker notes into
  the copied notes parts.

The deck is written to `meta.output_dir` (default `out/`). Point it at a shared
folder by editing that field, or for one run:

```bash
HANDOUT_OUT_DIR=./out npm run build
```

The figures come from `data/area/` and `data/mesh/`, so run `measure_area.py`
and `reconstruct_3d.py` first. Both the figures and the deck that embeds them
are patient-derived: `handout.json`, `out/` and `node_modules/` are gitignored,
and the built deck must not be committed.
