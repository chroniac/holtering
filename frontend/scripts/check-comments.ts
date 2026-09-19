// Catches what Biome does not: banner separators, walls of comments, TODO without a link.
// Rules: AGENTS.md -> Code; a run of consecutive comment lines is at most MAX_BLOCK long.
import { readdir } from "node:fs/promises";
import { join, relative } from "node:path";

const MAX_BLOCK = 6;
const LINE_COMMENT = /^\s*(\/\/|\/\*|\*|<!--)/;
const DIRECTIVE = /^\s*\/\/\s*(biome-ignore|@ts-|eslint|prettier)/;
const BANNER = /^\s*(\/\/|\/\*|\*|<!--)\s*[-=*#~_]{4,}/;
const TODO = /^\s*(\/\/|\/\*|\*|<!--)\s*(TODO|FIXME|XXX)\b(?!.*(Q-\d+|#\d+|https?:\/\/))/i;
const EXT = /\.(js|ts|css|html)$/;
const SKIP_DIRS: Record<string, true> = { node_modules: true, dist: true, ".git": true };

const walk = async function* (dir: string): AsyncGenerator<string> {
  for (const e of await readdir(dir, { withFileTypes: true })) {
    if (e.isDirectory()) {
      if (!SKIP_DIRS[e.name]) yield* walk(join(dir, e.name));
    } else if (EXT.test(e.name)) yield join(dir, e.name);
  }
};

const scan = (path: string, text: string): string[] => {
  const errors: string[] = [];
  let runStart = 0;
  let run = 0;
  const flush = () => {
    if (run > MAX_BLOCK) errors.push(`${path}:${runStart}: comment block of ${run} lines (maximum ${MAX_BLOCK})`);
    runStart = 0;
    run = 0;
  };
  text.split("\n").forEach((line, i) => {
    const n = i + 1;
    if (LINE_COMMENT.test(line) && !DIRECTIVE.test(line)) {
      runStart ||= n;
      run += 1;
      if (BANNER.test(line)) errors.push(`${path}:${n}: banner separator`);
      if (TODO.test(line)) errors.push(`${path}:${n}: TODO without an issue link`);
    } else flush();
  });
  flush();
  return errors;
};

const root = join(import.meta.dir, "..");
const args = Bun.argv.slice(2);
const files: string[] = [];
if (args.length) files.push(...args);
else for await (const f of walk(root)) files.push(f);

const errors: string[] = [];
for (const f of files) errors.push(...scan(relative(root, f), await Bun.file(f).text()));
if (errors.length) console.log(errors.join("\n"));
process.exit(errors.length ? 1 : 0);
