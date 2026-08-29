#!/usr/bin/env node
// strikeone tui — Ink parent process; python -m strikeone.rpc is the child.
import React from 'react';
import {render} from 'ink';
import {App} from './app.js';

const args = process.argv.slice(2);
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
