#!/usr/bin/env node
// wf-syntax-check.mjs — syntax-check Workflow scripts the way the Workflow runtime runs them (#1350).
//
// WHY: a Workflow script opens with `export const meta` (legal only in ESM) and uses a top-level
// `return`/`await` (legal only inside a function). As a standalone file it is valid JavaScript
// under NEITHER module goal, so `node --check` is the wrong test. Node 22's module detection let
// it through, and Node 24 rejects it with "Illegal return statement". This compiles the script as
// the body of an async function, which is how the runtime evaluates it, and never executes it.
//
// HOW: strip `import` statements (same regex as skills/nextwave/bundle.mjs; each is replaced by
// as many newlines as it spanned), drop the `export` keyword from top-level declarations, and
// compile `(async function () {<source>\n})` with vm.Script. The wrapper sits on line 1, ahead
// of the source, so error line numbers match the file.
//
// Plain modules (gate.js, dispatch.js, …) are real ESM: keep `node --check` for them.
//
// USAGE: node scripts/ci/wf-syntax-check.mjs <workflow.js>...   (exit 1 on any syntax error)

import { readFileSync } from 'node:fs'
import { Script } from 'node:vm'

function keepLines(match) {
  return '\n'.repeat((match.match(/\n/g) || []).length)
}

export function asFunctionBody(src) {
  return src
    .replace(/^import\s+[\s\S]*?from\s*['"][^'"]+['"];?[ \t]*$/gm, keepLines)
    .replace(/^export\s+(?=(async\s+function|function|const|let|var|class)\b)/gm, '')
}

const files = process.argv.slice(2)
if (files.length === 0) {
  console.error('usage: wf-syntax-check.mjs <workflow.js>...')
  process.exit(2)
}

let failed = 0
for (const file of files) {
  try {
    new Script(`(async function () {${asFunctionBody(readFileSync(file, 'utf8'))}\n})`, { filename: file })
  } catch (err) {
    console.error(`${file}: ${err.message}`)
    if (err.stack) console.error(err.stack.split('\n')[0])
    failed = 1
  }
}
process.exit(failed)
