import { HookableCore } from 'hookable';
import { U as Unhead, s as SSRHeadPayload, v as ServerHeadHooks, e as CreateServerHeadOptions } from './unhead.rdR8o82F.mjs';
import { aw as ResolvableHead } from './unhead.B8_fLxlB.mjs';

interface ServerUnhead<T = ResolvableHead> extends Unhead<T, SSRHeadPayload> {
    hooks: HookableCore<ServerHeadHooks>;
}
declare function createHead<T = ResolvableHead>(options?: CreateServerHeadOptions): ServerUnhead<T>;

export { createHead as c };
export type { ServerUnhead as S };
