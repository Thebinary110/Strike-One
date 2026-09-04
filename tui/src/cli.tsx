#!/usr/bin/env node
// strikeone tui — Ink parent process; python -m strikeone.rpc is the child.
import React from 'react';
import {render} from 'ink';
import {App} from './app.js';

const args = process.argv.slice(2);

if (args.includes('--help') || args.includes('-h')) {
  process.stdout.write(`strikeone tui - the Strike One terminal UI

USAGE
  strikeone tui                       open on CONNECT, pick a dataset
  strikeone tui --example ieee-cis    load the worked example
  strikeone tui --example synthetic   instant demo on generated data
  strikeone tui --source FILE         your parquet/CSV (mapping is read
                                      from .strikeone.toml beside the file;
                                      create it once with:
                                      strikeone check FILE --map ... --save-config)
  strikeone tui --no-motion           disable animations

PANELS (tab / shift-tab, or type the number + enter)
  1 CONNECT     point at data, see the contract check
  2 AUDIT       your headline metric vs fraud cases stopped first-attempt
  3 ROUTE       your scorer with vs without a blocklist lane
  4 ECONOMICS   set your costs, get approve/verify/block recommendations
  5 STREAM      replay the decisions; catches highlighted
  6 CASE        one fraud case, start to finish

KEYS
  h l or arrows   change review budget (AUDIT/ROUTE), adjust value (ECONOMICS)
  j k             pick an economics input      space   pause the stream
  n               next case (CASE)             ?       in-app help
  q               quit

Runs fully offline: a local Python process computes everything over stdio.
No telemetry, no network calls, your data never leaves the machine.
`);
  process.exit(0);
}

const get = (flag: string): string | undefined => {
  const i = args.indexOf(flag);
  return i >= 0 ? args[i + 1] : undefined;
};
const TAB_NAMES = ['connect', 'audit', 'route', 'economics', 'stream', 'case'];
const frameName = get('--frame');
const frameTab = frameName ? TAB_NAMES.indexOf(frameName) : undefined;
const source = get('--source');
const example = get('--example')
  ?? (frameName && !source ? 'ieee-cis' : undefined);
const motion = frameName === undefined && !args.includes('--no-motion')
  && !process.env.STRIKEONE_NO_MOTION;

// headless captures: honor COLUMNS/LINES so frames render at video width
if (!process.stdout.isTTY) {
  (process.stdout as any).columns = Number(process.env.COLUMNS ?? 132);
  (process.stdout as any).rows = Number(process.env.LINES ?? 44);
}

const interactive = process.stdout.isTTY && frameName === undefined;
if (interactive) process.stdout.write('\x1b[?1049h\x1b[H'); // alt buffer

const instance = render(
  <App initialSource={source} initialExample={example}
       frameTab={frameTab === -1 ? undefined : frameTab}
       motion={motion} />,
  {exitOnCtrlC: true},
);

instance.waitUntilExit().then(() => {
  if (interactive) process.stdout.write('\x1b[?1049l');
  process.exit(0);
});
