export { C as ClientUnhead, c as createHead } from './shared/unhead.BaYoUAzl.js';
import { R as RenderDomHeadOptions } from './shared/unhead.Dur2vr49.js';
import { p as HeadRenderer, U as Unhead } from './shared/unhead.71V9w6oU.js';
export { c as CreateClientHeadOptions } from './shared/unhead.71V9w6oU.js';
import 'hookable';
import './shared/unhead.B8_fLxlB.js';

declare function createDomRenderer(options?: RenderDomHeadOptions): HeadRenderer<boolean>;

declare function createDebouncedFn(callee: () => void, delayer: (fn: () => void) => void): () => void;

/** @deprecated Use `head.render()` instead */
declare function renderDOMHead(head: Unhead<any>, options?: RenderDomHeadOptions): boolean;

export { Unhead, createDebouncedFn, createDomRenderer, renderDOMHead };
