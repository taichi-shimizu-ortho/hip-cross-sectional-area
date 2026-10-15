"""Keep the grant figure deck as JSON + source images, and rebuild the PPTX from them.

    # PPTX -> JSON (images are referenced by path when a matching file exists)
    uv run --with python-pptx python scripts/grant_figures/deck_json.py to-json "<deck>.pptx" "<deck>.json"

    # JSON -> PPTX
    uv run --with python-pptx python scripts/grant_figures/deck_json.py build "<deck>.json" [--out x.pptx] [--force]

The JSON lists every shape in z-order with its box in slide pixels (1 px =
9525 EMU, the 1650 x 850 grid the deck was laid out on), its fill and line,
its text with resolved run formatting, and for pictures the image path
relative to the JSON file. Image files are matched by content, so the JSON
points at the same PNGs render_figure.py writes.

Only the features these decks use are supported: rectangles and other preset
shapes with solid fill / line, text boxes, stretched pictures, a solid
background and speaker notes. to-json refuses anything else instead of
dropping it silently.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn
from pptx.shapes.autoshape import AutoShapeType
from pptx.util import Emu

PX = 9525
FORMAT = "grant-deck/1"
DROP_RUN_ATTRS = {"dirty", "err", "lang", "altLang"}  # editor / spell-check bookkeeping, not formatting


def px(emu):
	return round(emu / PX, 3)


def emu(v):
	return Emu(round(v * PX))


def fail(msg):
	raise SystemExit(f"unsupported in this deck: {msg}")


def local(el):
	return etree.QName(el).localname


# --- PPTX -> JSON -----------------------------------------------------------------

def solid_color(parent):
	"""'RRGGBB' for <a:solidFill><a:srgbClr>, None for <a:noFill> or nothing."""
	if parent is None:
		return None
	sf = parent.find(qn("a:solidFill"))
	if sf is None:
		return None
	clr = sf.find(qn("a:srgbClr"))
	if clr is None or len(clr):
		fail("fill colour other than a plain sRGB value")
	return clr.get("val")


def run_props(rpr_chain):
	"""Resolve size / bold / italic / colour / font / lang through run -> paragraph -> list defaults."""
	out = {}
	for rpr in rpr_chain:
		if rpr is None:
			continue
		for k, key in (("sz", "size"), ("b", "bold"), ("i", "italic")):
			if key not in out and rpr.get(k) is not None:
				v = rpr.get(k)
				out[key] = int(v) / 100 if k == "sz" else v == "1" if k in ("b", "i") else v
		if "color" not in out and solid_color(rpr):
			out["color"] = solid_color(rpr)
		for tag in ("latin", "ea", "cs"):
			f = rpr.find(qn(f"a:{tag}"))
			if f is not None and f"font_{tag}" not in out:
				out[f"font_{tag}"] = f.get("typeface")
		extra = set(rpr.attrib) - {"sz", "b", "i"} - DROP_RUN_ATTRS
		if extra:
			fail(f"run attributes {sorted(extra)}")
		kids = {local(c) for c in rpr} - {"solidFill", "latin", "ea", "cs"}
		if kids:
			fail(f"run formatting {sorted(kids)}")
	# One typeface for latin / east-asian / complex script is the common case.
	fonts = {out.pop(f"font_{t}") for t in ("latin", "ea", "cs") if f"font_{t}" in out}
	if len(fonts) > 1:
		fail(f"different latin / east-asian fonts {sorted(fonts)}")
	if fonts:
		out["font"] = fonts.pop()
	return out


def text_of(sp):
	body = sp.find(qn("p:txBody"))
	if body is None:
		return None
	body_pr = body.find(qn("a:bodyPr"))
	if len(body_pr):
		fail("text body settings beyond plain attributes (autofit etc.)")
	lst = body.find(qn("a:lstStyle"))
	lst_def = lst.find(qn("a:defPPr")) if lst is not None else None
	lst_rpr = lst_def.find(qn("a:defRPr")) if lst_def is not None else None
	paras = []
	for p in body.findall(qn("a:p")):
		ppr = p.find(qn("a:pPr"))
		ppr_rpr = ppr.find(qn("a:defRPr")) if ppr is not None else None
		align = (ppr.get("algn") if ppr is not None else None) or (lst_def.get("algn") if lst_def is not None else None)
		runs = []
		for c in p:
			tag = local(c)
			if tag in ("pPr", "endParaRPr"):
				continue
			if tag != "r":
				fail(f"paragraph content <{tag}> (line break / field)")
			run = dict(text=c.findtext(qn("a:t")) or "", **run_props([c.find(qn("a:rPr")), ppr_rpr, lst_rpr]))
			if runs and {**runs[-1], "text": ""} == {**run, "text": ""}:
				runs[-1]["text"] += run["text"]  # editing splits runs; same formatting reads as one
			else:
				runs.append(run)
		paras.append(dict(align=align, runs=runs))
	if all(not p["runs"] for p in paras):
		return None
	return dict(body=dict(body_pr.attrib), paragraphs=paras)


def box_of(el):
	xfrm = el.find(qn("p:spPr")).find(qn("a:xfrm"))
	if xfrm.attrib:
		fail(f"rotated / flipped shape {dict(xfrm.attrib)}")
	off, ext = xfrm.find(qn("a:off")), xfrm.find(qn("a:ext"))
	return [px(int(off.get("x"))), px(int(off.get("y"))), px(int(ext.get("cx"))), px(int(ext.get("cy")))]


def name_of(el):
	return el.find(".//" + qn("p:cNvPr")).get("name")


def shape_to_dict(sp):
	sppr = sp.find(qn("p:spPr"))
	kids = {local(c) for c in sppr} - {"xfrm", "prstGeom", "solidFill", "noFill", "ln"}
	if kids:
		fail(f"shape properties {sorted(kids)}")
	geom = sppr.find(qn("a:prstGeom"))
	if geom is None:
		fail("custom geometry")
	av = geom.find(qn("a:avLst"))
	if av is not None and len(av):
		fail("adjusted preset geometry")
	if sp.find(qn("p:style")) is not None:
		fail("theme-styled shape")
	ln = sppr.find(qn("a:ln"))
	line = None
	if ln is not None and solid_color(ln):
		if {local(c) for c in ln} - {"solidFill"}:
			fail("line dash / arrow heads")
		line = dict(color=solid_color(ln), width_pt=int(ln.get("w", "12700")) / 12700)
	d = dict(type="shape", name=name_of(sp), geometry=geom.get("prst"), box=box_of(sp),
			 fill=solid_color(sppr), line=line)
	text = text_of(sp)
	if text:
		d["text"] = text
	return d


def picture_to_dict(pic, slide, files, json_dir, img_dir):
	bf = pic.find(qn("p:blipFill"))
	if bf.find(qn("a:srcRect")) is not None and bf.find(qn("a:srcRect")).attrib:
		fail("cropped picture")
	if bf.find(qn("a:stretch")) is None:
		fail("tiled picture")
	rid = bf.find(qn("a:blip")).get(qn("r:embed"))
	blob = slide.part.related_part(rid).blob
	path = files.get(hashlib.sha1(blob).hexdigest())
	if path is None:  # no source file on disk: keep the embedded image next to the JSON
		img_dir.mkdir(exist_ok=True)
		path = img_dir / f"{name_of(pic)}.png"
		path.write_bytes(blob)
		print(f"  extracted embedded image -> {path}")
	cnv = pic.find(".//" + qn("p:cNvPr"))
	return dict(type="picture", name=name_of(pic), box=box_of(pic),
				image=Path(os.path.relpath(Path(path).absolute(), json_dir.absolute())).as_posix(),
				alt=cnv.get("descr", ""))


def to_json(pptx, out, search):
	prs = Presentation(pptx)
	if len(prs.slides) != 1:
		fail(f"{len(prs.slides)} slides (one expected)")
	slide = prs.slides[0]
	files = {}
	for root in search:
		for f in sorted(Path(root).rglob("*.png")):
			files.setdefault(hashlib.sha1(f.read_bytes()).hexdigest(), f)

	bg = slide._element.find(qn("p:cSld")).find(qn("p:bg"))
	background = solid_color(bg.find(qn("p:bgPr"))) if bg is not None else None
	shapes = []
	for el in slide.shapes._spTree.iterchildren():
		tag = local(el)
		if tag in ("nvGrpSpPr", "grpSpPr", "extLst"):
			continue
		if tag == "sp":
			shapes.append(shape_to_dict(el))
		elif tag == "pic":
			shapes.append(picture_to_dict(el, slide, files, out.parent, out.with_name(out.stem + "_images")))
		else:
			fail(f"<{tag}> on the slide (group / table / chart)")
	notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""
	deck = dict(format=FORMAT,
				slide=dict(width=px(prs.slide_width), height=px(prs.slide_height), background=background),
				notes=notes, shapes=shapes)
	out.write_text(json.dumps(deck, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
	return deck


# --- JSON -> PPTX -----------------------------------------------------------------

PRESETS = {}
for member in MSO_SHAPE:
	try:
		PRESETS.setdefault(AutoShapeType(member).prst, member)
	except KeyError:
		pass


def set_fill(parent, color, after):
	"""Write <a:solidFill> or <a:noFill> into spPr / ln, replacing what python-pptx put there."""
	for tag in ("a:solidFill", "a:noFill"):
		for old in parent.findall(qn(tag)):
			parent.remove(old)
	if color:
		el = etree.SubElement(parent, qn("a:solidFill"))
		etree.SubElement(el, qn("a:srgbClr")).set("val", color)
	else:
		el = etree.SubElement(parent, qn("a:noFill"))
	if after is not None:
		after.addnext(el)
	else:
		parent.insert(0, el)


def write_text(sp, text):
	body = sp.find(qn("p:txBody"))
	body_pr = body.find(qn("a:bodyPr"))
	for k in list(body_pr.attrib):
		del body_pr.attrib[k]
	for k, v in (text or {}).get("body", {}).items():
		body_pr.set(k, v)
	for p in body.findall(qn("a:p")):
		body.remove(p)
	for para in (text or {}).get("paragraphs", [dict(align=None, runs=[])]):
		p = etree.SubElement(body, qn("a:p"))
		if para.get("align"):
			etree.SubElement(p, qn("a:pPr")).set("algn", para["align"])
		for run in para["runs"]:
			r = etree.SubElement(p, qn("a:r"))
			rpr = etree.SubElement(r, qn("a:rPr"))
			if "size" in run:
				rpr.set("sz", str(round(run["size"] * 100)))
			for key, attr in (("bold", "b"), ("italic", "i")):
				if key in run:
					rpr.set(attr, "1" if run[key] else "0")
			if "color" in run:
				etree.SubElement(etree.SubElement(rpr, qn("a:solidFill")), qn("a:srgbClr")).set("val", run["color"])
			if "font" in run:
				for tag in ("latin", "ea", "cs"):
					etree.SubElement(rpr, qn(f"a:{tag}")).set("typeface", run["font"])
			etree.SubElement(r, qn("a:t")).text = run["text"]


def build(deck_path, out):
	deck = json.loads(deck_path.read_text(encoding="utf-8"))
	if deck.get("format") != FORMAT:
		raise SystemExit(f"{deck_path}: not a {FORMAT} file")
	base = deck_path.parent
	prs = Presentation()
	prs.slide_width, prs.slide_height = emu(deck["slide"]["width"]), emu(deck["slide"]["height"])
	slide = prs.slides.add_slide(next(l for l in prs.slide_layouts if l.name == "Blank"))
	if deck["slide"].get("background"):
		slide.background.fill.solid()
		slide.background.fill.fore_color.rgb = RGBColor.from_string(deck["slide"]["background"])

	for s in deck["shapes"]:
		x, y, w, h = (emu(v) for v in s["box"])
		if s["type"] == "picture":
			pic = slide.shapes.add_picture(str(base / s["image"]), x, y, w, h)
			pic.name = s["name"]
			pic._element.find(".//" + qn("p:cNvPr")).set("descr", s.get("alt", ""))
			continue
		if s["geometry"] not in PRESETS:
			raise SystemExit(f"unknown preset geometry {s['geometry']!r}")
		shp = slide.shapes.add_shape(PRESETS[s["geometry"]], x, y, w, h)
		shp.name = s["name"]
		sp = shp._element
		style = sp.find(qn("p:style"))
		if style is not None:  # theme colours/effects would override the deck's own
			sp.remove(style)
		sppr = sp.find(qn("p:spPr"))
		set_fill(sppr, s.get("fill"), sppr.find(qn("a:prstGeom")))
		ln = sppr.find(qn("a:ln"))
		if ln is None:
			ln = etree.SubElement(sppr, qn("a:ln"))
		for k in list(ln.attrib):
			del ln.attrib[k]
		line = s.get("line")
		if line:
			ln.set("w", str(round(line["width_pt"] * 12700)))
		set_fill(ln, line["color"] if line else None, None)
		write_text(sp, s.get("text"))

	if deck.get("notes"):
		slide.notes_slide.notes_text_frame.text = deck["notes"]
	prs.save(out)


def main():
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	sub = ap.add_subparsers(dest="cmd", required=True)
	a = sub.add_parser("to-json", help="PPTX -> JSON")
	a.add_argument("pptx", type=Path)
	a.add_argument("json", type=Path)
	a.add_argument("--search", type=Path, action="append",
				   help="folder to look for the source images in (default: the JSON's folder)")
	b = sub.add_parser("build", help="JSON -> PPTX")
	b.add_argument("json", type=Path)
	b.add_argument("--out", type=Path, help="default: the JSON path with .pptx")
	b.add_argument("--force", action="store_true", help="overwrite an existing PPTX")
	args = ap.parse_args()

	if args.cmd == "to-json":
		deck = to_json(args.pptx, args.json, args.search or [args.json.parent])
		print(f"{args.json}: {len(deck['shapes'])} shapes")
	else:
		out = args.out or args.json.with_suffix(".pptx")
		if out.exists() and not args.force:
			raise SystemExit(f"{out} exists; pass --force or --out")
		build(args.json, out)
		print(f"built {out}")


if __name__ == "__main__":
	main()
