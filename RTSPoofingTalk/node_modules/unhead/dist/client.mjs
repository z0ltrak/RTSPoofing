import { r as renderDOMHead$1 } from './shared/unhead.BBvzuk-m.mjs';
export { c as createDomRenderer } from './shared/unhead.BBvzuk-m.mjs';
export { c as createHead } from './shared/unhead.DqXjmljN.mjs';
import './shared/unhead.fg-0ge_u.mjs';
import './shared/unhead.Cdnk2khL.mjs';
import './shared/unhead.mB5lMBMV.mjs';
import 'hookable';
import './shared/unhead.CfgPMHXt.mjs';

function createDebouncedFn(callee, delayer) {
  let ctxId = 0;
  return () => {
    const delayFnCtxId = ++ctxId;
    delayer(() => {
      if (ctxId === delayFnCtxId) {
        callee();
      }
    });
  };
}

function renderDOMHead(head, options) {
  return renderDOMHead$1(head, options);
}

export { createDebouncedFn, renderDOMHead };
