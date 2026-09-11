/**
 * Renders handout.json into the Zoom handout deck.
 *
 * pptx-automizer clones a prototype slide per layout from the layout template
 * and fills its named shapes; pptxGenJS (through slide.generate) draws the
 * elements whose count depends on the content — the pipeline boxes and the
 * figures. Speaker notes are written back into the copied notesSlide parts
 * after the deck is assembled.
 *
 *     npm run build
 */

import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { basename, dirname, posix, resolve, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import JSZip from 'jszip';
import { Automizer, modify } from 'pptx-automizer';
import type { ISlide, TableData } from 'pptx-automizer';
import type { MultiTextParagraph } from 'pptx-automizer/dist/interfaces/imulti-text';
import { COLOR, FONT, FRAME, PROTOTYPE, SLIDE } from './design.js';

const here = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(here, '..');
const OUT_NAME = 'gluteal_area_handout.pptx';
const MONO = 'Consolas';

type Bullet = { text: string; level?: number };
type Slide = {
	id: string;
	layout: keyof typeof PROTOTYPE;
	title?: string;
	subtitle?: string;
	lead?: string;
	meta?: string[];
	bullets?: Bullet[];
	steps?: { label: string; command: string; detail?: string }[];
	items?: { step: string; title: string; detail?: string }[];
	image?: string;
	caption?: string;
	table?: { headers: string[]; rows: string[][] };
	footnote?: string;
	notes?: string;
};
type Handout = { meta: Record<string, string | number>; slides: Slide[] };

// handout.json is the public draft, with the measured values blanked out.
// handout.local.json holds the real ones and stays out of the repository.
const source = ['handout.local.json', 'handout.json']
	.map((name) => resolve(ROOT, name))
	.find((path) => existsSync(path))!;
const handout: Handout = JSON.parse(readFileSync(source, 'utf8'));

/** Where the deck is written: meta.output_dir, or HANDOUT_OUT_DIR to override. */
const OUT_DIR = resolve(ROOT, process.env.HANDOUT_OUT_DIR ?? String(handout.meta.output_dir ?? 'out'));
const srgb = (value: string) => ({ type: 'srgbClr' as const, value });

const EMU_PER_INCH = 914400;
const emu = (inches: number) => Math.round(inches * EMU_PER_INCH);

/** PNG intrinsic size, straight out of the IHDR chunk. */
function pngSize(file: string): { w: number; h: number } {
	const buf = readFileSync(file);
	return { w: buf.readUInt32BE(16), h: buf.readUInt32BE(20) };
}

/** Largest box-fitting rectangle, centred in the box. */
function fit(file: string, box: { x: number; y: number; w: number; h: number }) {
	const { w, h } = pngSize(file);
	const scale = Math.min(box.w / w, box.h / h);
	const [iw, ih] = [w * scale, h * scale];
	return { x: box.x + (box.w - iw) / 2, y: box.y + (box.h - ih) / 2, w: iw, h: ih };
}

function bulletParagraphs(bullets: Bullet[], baseSize = 1500): MultiTextParagraph[] {
	return bullets.map((b) => ({
		paragraph: {
			level: b.level ?? 0,
			bullet: true,
			bulletChar: (b.level ?? 0) === 0 ? '•' : '–',
			marginLeft: (b.level ?? 0) === 0 ? 228600 : 571500,
			indent: -228600,
			spaceAfter: { percent: (b.level ?? 0) === 0 ? 45 : 25 },
			lineSpacing: { percent: 118 },
		},
		text: b.text,
		style: {
			size: (b.level ?? 0) === 0 ? baseSize : Math.round(baseSize * 0.84),
			color: srgb((b.level ?? 0) === 0 ? COLOR.body : COLOR.muted),
			fontFamily: FONT,
		},
	}));
}

/** One paragraph per step: label, command in a monospace face, then the detail. */
function stepParagraphs(steps: NonNullable<Slide['steps']>): MultiTextParagraph[] {
	return steps.map((s, i) => ({
		paragraph: { spaceAfter: { percent: 60 }, lineSpacing: { percent: 120 } },
		textRuns: [
			{ text: `${String(i + 1).padStart(2, '0')}  ${s.label}`,
			  style: { size: 1400, isBold: true, color: srgb(COLOR.accent), fontFamily: FONT } },
			{ break: true },
			{ text: `$ ${s.command}`,
			  style: { size: 1150, color: srgb(COLOR.ink), fontFamily: MONO } },
			...(s.detail
				? [{ break: true } as const,
				   { text: s.detail, style: { size: 1200, color: srgb(COLOR.muted), fontFamily: FONT } }]
				: []),
		],
	}));
}

function tableData(table: NonNullable<Slide['table']>): TableData {
	const cell = (color: string, bold = false) => ({
		size: 1150, color: srgb(color), fontFamily: FONT, isBold: bold,
	});
	// setTable only writes `body`, so the header travels as its first row.
	return {
		body: [
			{
				values: table.headers,
				styles: table.headers.map(() => ({
					...cell(COLOR.ink, true), background: srgb(COLOR.accentSoft),
				})),
			},
			...table.rows.map((row, r) => ({
				values: row,
				styles: row.map((_, c) => ({
					...cell(c === 0 ? COLOR.ink : COLOR.body, c === 0),
					background: srgb(COLOR.white),
					// The prototype's closing row is sliced away, so the last data
					// row has to draw the bottom edge of the table itself.
					...(r === table.rows.length - 1
						? { border: [{ tag: 'lnB' as const, type: 'solid', weight: 9525, color: srgb(COLOR.line) }] }
						: {}),
				})),
			})),
		],
	};
}

/** Pipeline boxes, drawn left to right with a chevron between them. */
function drawFlow(slide: ISlide, items: NonNullable<Slide['items']>) {
	const gap = 0.22;
	const w = (FRAME.contentW - gap * (items.length - 1)) / items.length;
	items.forEach((item, i) => {
		const x = FRAME.marginX + i * (w + gap);
		slide.generate((pgen, pptx) => {
			pgen.addShape(pptx.ShapeType.roundRect, {
				x, y: 2.35, w, h: 2.1, rectRadius: 0.06,
				fill: { color: COLOR.accentSoft }, line: { color: COLOR.line, width: 1 },
			});
			pgen.addText(item.step, {
				x, y: 2.5, w, h: 0.4,
				fontFace: FONT, fontSize: 13, bold: true, color: COLOR.accent, align: 'center',
			});
			pgen.addText(item.title, {
				x: x + 0.1, y: 2.9, w: w - 0.2, h: 0.5,
				fontFace: FONT, fontSize: 14, bold: true, color: COLOR.ink, align: 'center', valign: 'top',
			});
			pgen.addText(item.detail ?? '', {
				x: x + 0.12, y: 3.42, w: w - 0.24, h: 0.95,
				fontFace: FONT, fontSize: 11, color: COLOR.body, align: 'center', valign: 'top',
			});
			if (i < items.length - 1) {
				pgen.addText('›', {
					x: x + w, y: 3.1, w: gap, h: 0.4,
					fontFace: FONT, fontSize: 18, color: COLOR.accent, align: 'center',
				});
			}
		}, `flow-${i}`);
	});
}

const automizer = new Automizer({
	templateDir: resolve(ROOT, 'template'),
	outputDir: OUT_DIR,
	mediaDir: resolve(ROOT, '..', '..'),
	removeExistingSlides: true,
	cleanup: true,
	compression: 6,
	verbosity: 0,
});

const pres = automizer
	.loadRoot('handout_layouts.pptx')
	.load('handout_layouts.pptx', 'layout');

// Figures are pulled in as media so the picture placeholders can point at them.
for (const file of handout.slides.filter((s) => s.image).map((s) => resolve(ROOT, s.image!))) {
	pres.loadMedia(basename(file), dirname(file));
}

const total = handout.slides.length;

handout.slides.forEach((s, index) => {
	const page = index + 1;
	pres.addSlide('layout', PROTOTYPE[s.layout], (slide) => {
		if (s.title) slide.modifyElement('title', modify.setText(s.title));

		// Frame text: drop the placeholder when the slide has nothing to say.
		if (s.layout !== 'title') {
			slide.modifyElement('pageNo', modify.setText(`${page} / ${total}`));
			if (s.footnote) slide.modifyElement('footnote', modify.setText(s.footnote));
			else slide.removeElement('footnote');
			if (s.lead) slide.modifyElement('lead', modify.setText(s.lead));
			else if (['bullets', 'steps', 'flow', 'table'].includes(s.layout)) slide.removeElement('lead');
		}

		switch (s.layout) {
			case 'title':
				if (s.subtitle) slide.modifyElement('subtitle', modify.setText(s.subtitle));
				slide.modifyElement('meta', modify.setMultiText(
					(s.meta ?? []).map((line) => ({
						paragraph: { spaceAfter: { percent: 30 } },
						text: line,
						style: { size: 1200, color: srgb(COLOR.muted), fontFamily: FONT },
					})),
				));
				break;

			case 'bullets':
				slide.modifyElement('body', modify.setMultiText(bulletParagraphs(s.bullets ?? [])));
				break;

			case 'closing':   // fewer lines, so they carry more weight
				slide.modifyElement('body', modify.setMultiText(bulletParagraphs(s.bullets ?? [], 1800)));
				break;

			case 'steps':
				slide.modifyElement('body', modify.setMultiText(stepParagraphs(s.steps ?? [])));
				break;

			case 'flow':
				drawFlow(slide, s.items ?? []);
				break;

			case 'table':
				slide.modifyElement('table', modify.setTable(tableData(s.table!)));
				break;

			case 'image': {
				// Retarget the template's picture instead of adding a new one, so
				// the prototype's relation is used up rather than left dangling.
				const file = resolve(ROOT, s.image!);
				const box = fit(file, { x: FRAME.marginX, y: 1.3, w: 7.3, h: 4.7 });
				slide.modifyElement('figure', [
					modify.setRelationTarget(basename(file)),
					modify.setPosition({ x: emu(box.x), y: emu(box.y), w: emu(box.w), h: emu(box.h) }),
				]);
				if (s.caption) slide.modifyElement('caption', modify.setText(s.caption));
				else slide.removeElement('caption');
				slide.modifyElement('body', modify.setMultiText(bulletParagraphs(s.bullets ?? [])));
				break;
			}
		}
	});
});

mkdirSync(OUT_DIR, { recursive: true });
await pres.write(OUT_NAME);

/**
 * pptx-automizer appends the assembled slides after the prototypes and then
 * drops the prototypes, so part numbers no longer match slide order. This pass
 * resolves the real order from presentation.xml, writes each slide's speaker
 * notes into its copied notesSlide, and prunes the parts the removed prototype
 * slides left behind.
 */
async function finalize(file: string, slides: Slide[]) {
	const zip = await JSZip.loadAsync(readFileSync(file));
	const read = (path: string) => zip.file(path)?.async('string');
	const escape = (t: string) =>
		t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

	// rId -> slide part, then the sldIdLst order -> position of each slide.
	const presRels = (await read('ppt/_rels/presentation.xml.rels')) ?? '';
	const byId = new Map(
		[...presRels.matchAll(/Id="([^"]+)"[^>]*Target="slides\/(slide\d+\.xml)"/g)]
			.map((m) => [m[1], m[2]] as const),
	);
	const presentation = (await read('ppt/presentation.xml')) ?? '';
	const order = [...presentation.matchAll(/<p:sldId[^>]*r:id="([^"]+)"/g)]
		.map((m) => byId.get(m[1]))
		.filter((part): part is string => Boolean(part));
	const position = new Map(order.map((part, i) => [part, i]));

	let written = 0;
	const dropped: string[] = [];
	for (const path of Object.keys(zip.files)) {
		const number = path.match(/^ppt\/notesSlides\/notesSlide(\d+)\.xml$/)?.[1];
		if (!number) continue;
		const relsPath = `ppt/notesSlides/_rels/notesSlide${number}.xml.rels`;
		const slidePart = (await read(relsPath))?.match(/slides\/(slide\d+\.xml)/)?.[1];
		const index = slidePart ? position.get(slidePart) : undefined;

		if (index === undefined) {           // notes of a removed prototype slide
			zip.remove(path);
			zip.remove(relsPath);
			dropped.push(`notesSlide${number}.xml`);
			continue;
		}
		const notes = slides[index]?.notes;
		if (!notes) continue;
		zip.file(path, (await read(path))!.replace('{{notes}}', escape(notes)));
		written += 1;
	}

	// Relationship parts of the prototype slides that were removed, and the
	// unused picture relations left behind when a placeholder was retargeted.
	for (const path of Object.keys(zip.files)) {
		const part = path.match(/^ppt\/slides\/_rels\/(slide\d+\.xml)\.rels$/)?.[1];
		if (!part) continue;
		if (!position.has(part)) {
			zip.remove(path);
			continue;
		}
		const slideXml = (await read(`ppt/slides/${part}`)) ?? '';
		const rels = (await read(path))!;
		const pruned = rels.replace(/<Relationship\b[^>]*\/>/g, (tag) => {
			const id = tag.match(/Id="([^"]+)"/)?.[1];
			const target = tag.match(/Target="([^"]+)"/)?.[1];
			if (!id || !target || /TargetMode="External"/.test(tag)) return tag;
			if (zip.file(posix.normalize(posix.join('ppt/slides', target)))) return tag;
			if (slideXml.includes(`"${id}"`)) {
				console.warn(`warning: ${part} still uses missing target ${target}`);
				return tag;
			}
			return '';
		});
		if (pruned !== rels) zip.file(path, pruned);
	}

	if (dropped.length) {
		const types = (await read('[Content_Types].xml'))!;
		zip.file('[Content_Types].xml', types.replace(
			/<Override[^>]*PartName="\/ppt\/notesSlides\/([^"]+)"[^>]*\/>/g,
			(tag, part: string) => (dropped.includes(part) ? '' : tag),
		));
	}

	writeFileSync(file, await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' }));
	return { written, order: order.length, dropped: dropped.length };
}

const outFile = resolve(OUT_DIR, OUT_NAME);
const result = await finalize(outFile, handout.slides);

console.log(`source   : ${basename(source)}`);
console.log(`slides   : ${result.order} (expected ${total})`);
console.log(`notes    : ${result.written} / ${total}`);
console.log(`pruned   : ${result.dropped} prototype notes parts`);
const shown = relative(process.cwd(), outFile);
console.log(`deck     -> ${shown.startsWith('..') ? outFile : shown}`);
