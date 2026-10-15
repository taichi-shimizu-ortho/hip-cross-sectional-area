"""Swap the 3D views and legend of the edited grant deck for the --thigh renders.

The deck in output/ has been edited by hand, so it is updated in place rather
than rebuilt: the CT panels, headings and every other text stay untouched.
A copy of the previous deck is kept next to the new images.

    uv run --with python-pptx python scripts/grant_figures/update_ppt.py --images <render_figure.py --out dir>
"""
from pathlib import Path
import argparse
import copy
import shutil
import sys

from PIL import ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.util import Emu

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import hip_paths

PX = 9525  # EMU per slide pixel (the deck is laid out on a 1650 x 850 px grid)

# Same order and colours as render_figure.py --thigh.
LEGEND = [
	("中殿筋", "337ABA"),
	("小殿筋", "DE4F3B"),
	("腸腰筋", "9CA3AB"),
	("ハムストリングス", "8C6BBF"),
	("内転筋群", "4F9961"),
]
NOTE = "骨盤・大腿骨・腸腰筋は位置関係の参照、ハムストリングス・内転筋群は筋群として表示"

# The 3D column of the slide, in slide pixels.
COLUMN = (625, 1625)
SWATCH, SWATCH_GAP, ITEM_GAP = 22, 10, 34

MEASURE_FONT = ["C:/Windows/Fonts/meiryo.ttc", "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"]


def text_px(text, pt):
	path = next(f for f in MEASURE_FONT if Path(f).exists())
	return ImageFont.truetype(path, round(pt * 96 / 72)).getlength(text)


def replace_picture(slide, pic, image):
	_, rid = slide.part.get_or_add_image_part(str(image))
	pic._element.xpath("./p:blipFill/a:blip")[0].set(qn("r:embed"), rid)


def set_text(shape, text):
	"""Replace the text but keep the first run's formatting."""
	para = shape.text_frame.paragraphs[0]
	runs = para.runs
	for r in runs[1:]:
		r._r.getparent().remove(r._r)
	runs[0].text = text


def clone(slide, shape, name):
	el = copy.deepcopy(shape._element)
	c_nv = el.xpath("./p:nvSpPr/p:cNvPr")[0]
	c_nv.set("id", str(max(s.shape_id for s in slide.shapes) + 1))
	c_nv.set("name", name)
	for ext in c_nv.xpath("./a:extLst"):
		c_nv.remove(ext)  # creationId must stay unique
	shape._element.addnext(el)
	return next(s for s in slide.shapes if s.name == name)


def main():
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument("--deck", type=Path, default=hip_paths.OUTPUT_DIR / "grant figure.pptx")
	ap.add_argument("--images", type=Path, required=True)
	args = ap.parse_args()

	backup = args.images / "grant figure (before update).pptx"
	if not backup.exists():
		shutil.copy2(args.deck, backup)

	prs = Presentation(args.deck)
	slide = prs.slides[0]

	# Anterior / posterior 3D: the two pictures in the right-hand column, left to right.
	pics = sorted((s for s in slide.shapes if s.shape_type == 13 and s.left >= COLUMN[0] * PX - PX * 5),
				  key=lambda s: s.left)
	assert len(pics) == 2, f"expected two 3D pictures, found {len(pics)}"
	replace_picture(slide, pics[0], args.images / "gluteal_context_anterior.png")
	replace_picture(slide, pics[1], args.images / "gluteal_context_posterior.png")

	# Legend: reuse what is there, clone the first entry for new ones.
	by_name = {s.name: s for s in slide.shapes}
	tmpl_sw, tmpl_tx = by_name[f"{LEGEND[0][0]} color"], by_name[f"{LEGEND[0][0]} legend"]
	pt = tmpl_tx.text_frame.paragraphs[0].runs[0].font.size.pt
	entries = []
	for label, color in LEGEND:
		sw = by_name.get(f"{label} color")
		if sw is None:
			sw = clone(slide, tmpl_sw, f"{label} color")
			tx = clone(slide, tmpl_tx, f"{label} legend")
			set_text(tx, label)
		else:
			tx = by_name[f"{label} legend"]
		sw.fill.solid()
		sw.fill.fore_color.rgb = RGBColor.from_string(color)
		entries.append((sw, tx, text_px(label, pt) * 1.08 + 4))

	total = sum(SWATCH + SWATCH_GAP + w for *_, w in entries) + ITEM_GAP * (len(entries) - 1)
	x = (COLUMN[0] + COLUMN[1] - total) / 2
	for sw, tx, w in entries:
		sw.left, sw.width = Emu(round(x * PX)), Emu(SWATCH * PX)
		tx.left, tx.width = Emu(round((x + SWATCH + SWATCH_GAP) * PX)), Emu(round(w * PX))
		x += SWATCH + SWATCH_GAP + w + ITEM_GAP

	set_text(by_name["Anatomic context note"], NOTE)

	prs.save(args.deck)
	shutil.copy2(args.deck, args.images / "grant_figure_editable.pptx")
	print(f"updated {args.deck}\nbackup  {backup}")


if __name__ == "__main__":
	main()
