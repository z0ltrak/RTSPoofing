export { C as ClientUnhead, c as createHead } from './shared/unhead.DhfYK-VF.mjs';
import { R as RenderDomHeadOptions } from './shared/unhead.BwirKaJy.mjs';
import { p as HeadRenderer, U as Unhead } from './shared/unhead.rdR8o82F.mjs';
export { c as CreateClientHeadOptions } from './shared/unhead.rdR8o82F.mjs';
import 'hookable';
import './shared/unhead.B8_fLxlB.mjs';

declare function createDomRenderer(options?: RenderDomHeadOptions): HeadRenderer<boolean>;

declare function createDebouncedFn(callee: () => void, delayer: (fn: () => void) => void): () => void;

/** @deprecated Use `head.render()` instead */
declare function renderDOMHead(head: Unhead<any>, options?: RenderDomHeadOptions): boolean;

export { Unhead, createDebouncedFn, createDomRenderer, renderDOMHead };
