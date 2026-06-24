import { dt as defineCliFlags, ft as parseCliFlags, lt as CliFlagsSchema, r as DevframeDefinition, ut as InferCliFlags } from "../devframe-BuR6n9ZD.mjs";
import { CAC } from "cac";
import { H3 } from "h3";

//#region src/adapters/cli.d.ts
interface CreateCliOptions {
  /** Default port for `dev` (default: 9999). */
  defaultPort?: number;
  /**
   * Final CAC hook invoked after devframe's built-in subcommands and
   * after the definition's `cli.configure`. Use this to add app-level
   * flags and commands at the assembly stage.
   */
  configureCli?: (cli: CAC) => void;
  /**
   * Called once the dev server is listening. Use this to print a
   * startup banner or trigger side-effects that depend on the live URL.
   */
  onReady?: (info: {
    origin: string;
    port: number;
    app: H3;
  }) => void | Promise<void>;
}
interface CliHandle {
  /**
   * Raw CAC instance. Mutate before calling `parse()` for last-mile
   * flag or command additions that don't fit `configureCli`.
   */
  cli: CAC;
  parse: (argv?: string[]) => Promise<void>;
}
declare function createCli(d: DevframeDefinition, options?: CreateCliOptions): CliHandle;
//#endregion
export { type CliFlagsSchema, CliHandle, CreateCliOptions, type InferCliFlags, createCli, defineCliFlags, parseCliFlags };