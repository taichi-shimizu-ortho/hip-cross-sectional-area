# Zoom handout — gluteal muscle area

`handout.json` is the draft handout: meta, agenda, one entry per slide (title,
body, speaker notes) and an appendix with the command cheat sheet, glossary and
FAQ. Edit the JSON, rebuild, and the deck follows.

The repository is public, so `handout.json` carries the structure with the
measured values blanked out. Keep the real numbers — and any local output path —
in `handout.local.json`, which is gitignored and takes precedence when present:

```bash
cp handout.json handout.local.json   # then fill in the measurements
```

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
folder by editing that field — in `handout.local.json`, so the path stays out of
the repository — or for one run:

```bash
HANDOUT_OUT_DIR=./out npm run build
```

The figures come from `data/area/` and `data/mesh/`, so run `measure_area.py`
and `reconstruct_3d.py` first. Both the figures and the deck that embeds them
are patient-derived: `out/` and `node_modules/` are gitignored, and the built
deck must not be committed.
