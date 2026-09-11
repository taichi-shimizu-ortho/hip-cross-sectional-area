/**
 * Builds the layout template for the handout deck.
 *
 * The template holds one prototype slide per layout (title, bullets, steps,
 * flow, image, table, closing) with named shapes and dummy content. It carries
 * the whole design; build_pptx.ts only fills the named shapes with the content
 * of handout.json. Replace this template with a corporate .pptx of the same
 * shape names and the build keeps working.
 *
 *     npm run template
 */

import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import PptxGenJS from 'pptxgenjs';
import { COLOR, FONT, FRAME, SLIDE } from './design.js';

const here = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(here, '..', 'template', 'handout_layouts.pptx');

// 1x1 transparent PNG — a stand-in so the image prototype has a picture frame.
const PLACEHOLDER_PNG =
	'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';

const pptx = new PptxGenJS();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'BayesianUNet gluteal pipeline';
pptx.title = 'Gluteal muscle area — handout';

/** Title, accent rule, optional lead-in line, footnote and page number. */
function addFrame(slide: PptxGenJS.Slide, opts: { lead?: boolean } = {}) {
	slide.addText('{{title}}', {
		objectName: 'title',
		x: FRAME.marginX, y: FRAME.titleY, w: FRAME.contentW, h: FRAME.titleH,
		fontFace: FONT, fontSize: 26, bold: true, color: COLOR.ink, valign: 'middle',
	});
	slide.addShape(pptx.ShapeType.rect, {
		objectName: 'titleRule',
		x: FRAME.marginX, y: FRAME.ruleY, w: 1.6, h: 0.045,
		fill: { color: COLOR.accent }, line: { color: COLOR.accent, width: 0 },
	});
	if (opts.lead) {
		slide.addText('{{lead}}', {
			objectName: 'lead',
			x: FRAME.marginX, y: FRAME.leadY, w: FRAME.contentW, h: FRAME.leadH,
			fontFace: FONT, fontSize: 13, color: COLOR.muted, valign: 'middle',
		});
	}
	slide.addShape(pptx.ShapeType.rect, {
		objectName: 'footRule',
		x: FRAME.marginX, y: FRAME.footY - 0.1, w: FRAME.contentW, h: 0.01,
		fill: { color: COLOR.line }, line: { color: COLOR.line, width: 0 },
	});
	slide.addText('{{footnote}}', {
		objectName: 'footnote',
		x: FRAME.marginX, y: FRAME.footY, w: FRAME.contentW - FRAME.pageW, h: FRAME.footH,
		fontFace: FONT, fontSize: 10, color: COLOR.muted, valign: 'middle',
	});
	slide.addText('0', {
		objectName: 'pageNo',
		x: SLIDE.w - FRAME.marginX - FRAME.pageW, y: FRAME.footY, w: FRAME.pageW, h: FRAME.footH,
		fontFace: FONT, fontSize: 10, color: COLOR.muted, align: 'right', valign: 'middle',
	});
	slide.addNotes('{{notes}}');
}

// 1 — title -------------------------------------------------------------
{
	const slide = pptx.addSlide();
	slide.addShape(pptx.ShapeType.rect, {
		objectName: 'coverBar',
		x: 0.9, y: 2.12, w: 0.13, h: 2.0,
		fill: { color: COLOR.accent }, line: { color: COLOR.accent, width: 0 },
	});
	slide.addText('{{title}}', {
		objectName: 'title',
		x: 1.28, y: 2.1, w: 10.9, h: 1.05,
		fontFace: FONT, fontSize: 38, bold: true, color: COLOR.ink, valign: 'middle',
	});
	slide.addText('{{subtitle}}', {
		objectName: 'subtitle',
		x: 1.28, y: 3.2, w: 10.9, h: 0.9,
		fontFace: FONT, fontSize: 17, color: COLOR.accent, valign: 'top',
	});
	slide.addText('{{meta}}', {
		objectName: 'meta',
		x: 1.28, y: 4.5, w: 10.9, h: 1.4,
		fontFace: FONT, fontSize: 12, color: COLOR.muted, lineSpacingMultiple: 1.5,
	});
	slide.addNotes('{{notes}}');
}

// 2 — bullets -----------------------------------------------------------
{
	const slide = pptx.addSlide();
	addFrame(slide, { lead: true });
	slide.addText('{{body}}', {
		objectName: 'body',
		x: FRAME.marginX, y: FRAME.bodyY, w: FRAME.contentW, h: FRAME.bodyH,
		fontFace: FONT, fontSize: 15, color: COLOR.body, valign: 'top', lineSpacingMultiple: 1.35,
	});
}

// 3 — steps -------------------------------------------------------------
{
	const slide = pptx.addSlide();
	addFrame(slide, { lead: true });
	slide.addText('{{steps}}', {
		objectName: 'body',
		x: FRAME.marginX, y: FRAME.bodyY, w: FRAME.contentW, h: FRAME.bodyH,
		fontFace: FONT, fontSize: 13, color: COLOR.body, valign: 'top',
	});
}

// 4 — flow (boxes are generated at build time) --------------------------
{
	const slide = pptx.addSlide();
	addFrame(slide, { lead: true });
}

// 5 — image + notes column ---------------------------------------------
{
	const slide = pptx.addSlide();
	addFrame(slide, {});
	slide.addImage({
		objectName: 'figure',
		data: PLACEHOLDER_PNG,
		x: FRAME.marginX, y: 1.3, w: 7.3, h: 4.7,
	});
	slide.addText('{{caption}}', {
		objectName: 'caption',
		x: FRAME.marginX, y: 6.06, w: 7.3, h: 0.34,
		fontFace: FONT, fontSize: 10.5, color: COLOR.muted, italic: true, valign: 'middle',
	});
	slide.addText('{{body}}', {
		objectName: 'body',
		x: 8.2, y: 1.36, w: 4.5, h: 4.6,
		fontFace: FONT, fontSize: 13, color: COLOR.body, valign: 'top', lineSpacingMultiple: 1.3,
	});
}

// 6 — table -------------------------------------------------------------
{
	const slide = pptx.addSlide();
	addFrame(slide, { lead: true });
	// Six columns and eight rows is the widest/tallest case; pptx-automizer
	// slices the prototype down to the size of the data it is given.
	const header = Array.from({ length: 6 }, (_, c) => ({
		text: `H${c + 1}`,
		options: { bold: true, color: COLOR.ink, fill: { color: COLOR.accentSoft } },
	}));
	const rows = Array.from({ length: 7 }, (_, r) =>
		Array.from({ length: 6 }, (_, c) => ({ text: `r${r}c${c}` })));
	slide.addTable([header, ...rows], {
		objectName: 'table',
		x: FRAME.marginX, y: FRAME.bodyY, w: FRAME.contentW,
		colW: Array(6).fill(FRAME.contentW / 6),
		rowH: 0.42,
		fontFace: FONT, fontSize: 12, color: COLOR.body, valign: 'middle',
		border: { type: 'solid', color: COLOR.line, pt: 0.75 },
	});
}

// 7 — closing -----------------------------------------------------------
{
	const slide = pptx.addSlide();
	addFrame(slide, {});
	slide.addText('{{body}}', {
		objectName: 'body',
		x: FRAME.marginX, y: 2.0, w: FRAME.contentW, h: 3.6,
		fontFace: FONT, fontSize: 18, color: COLOR.body, valign: 'top', lineSpacingMultiple: 1.6,
	});
}

mkdirSync(dirname(OUT), { recursive: true });
await pptx.writeFile({ fileName: OUT });
console.log(`layout template -> ${OUT}`);
