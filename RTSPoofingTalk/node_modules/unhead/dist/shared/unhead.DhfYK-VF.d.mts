import { HookableCore } from 'hookable';
import { U as Unhead, C as ClientHeadHooks, c as CreateClientHeadOptions } from './unhead.rdR8o82F.mjs';
import { aw as ResolvableHead } from './unhead.B8_fLxlB.mjs';

interface ClientUnhead<T = ResolvableHead> extends Unhead<T, boolean> {
    hooks: HookableCore<ClientHeadHooks>;
    dirty: boolean;
    invalidate: () => void;
}
declare function createHead<T = ResolvableHead>(options?: CreateClientHeadOptions): ClientUnhead<T>;

export { createHead as c };
export type { ClientUnhead as C };
