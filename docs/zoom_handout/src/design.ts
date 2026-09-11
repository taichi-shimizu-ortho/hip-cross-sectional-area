/** Shared design tokens for the handout deck. */

export const SLIDE = { w: 13.333, h: 7.5 };

export const COLOR = {
	ink: '1B2A3A',        // headings
	body: '33414F',       // body text
	muted: '7A8899',      // footnotes, meta
	accent: '2E6FA7',     // rules, step numbers
	accentSoft: 'E8F0F7', // chip / table header fill
	line: 'D8DFE6',
	white: 'FFFFFF',
} as const;

/** Ships with Windows 10/11 and installs free on macOS; falls back gracefully. */
export const FONT = 'BIZ UDGothic';

/** Common frame: title band, body area, footer. Inches. */
export const FRAME = {
	marginX: 0.62,
	contentW: SLIDE.w - 0.62 * 2,
	titleY: 0.38,
	titleH: 0.62,
	ruleY: 1.06,
	leadY: 1.14,
	leadH: 0.42,
	bodyY: 1.72,
	bodyH: 4.6,
	footY: 6.52,
	footH: 0.36,
	pageW: 0.9,
} as const;

/** Prototype slide number in the layout template, per handout layout name. */
export const PROTOTYPE: Record<string, number> = {
	title: 1,
	bullets: 2,
	steps: 3,
	flow: 4,
	image: 5,
	table: 6,
	closing: 7,
};
