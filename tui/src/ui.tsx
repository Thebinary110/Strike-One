// Shared visual language. Restrained: a masthead, hairline rules, real
// spacing. Colour ONLY on data: green = first-hit, amber = blocklist-coverable,
// red = good customers harmed. No emoji, no spinner theatre.
import React from 'react';
import {Box, Text} from 'ink';

const noColor = !!process.env.NO_COLOR;
export const C = {
  ink: noColor ? undefined : 'white',
  dim: noColor ? undefined : 'gray',
  stop: noColor ? undefined : '#2ea36b',
  waste: noColor ? undefined : '#c9962e',
  harm: noColor ? undefined : '#d0604c',
  accent: noColor ? undefined : '#7aa5c9',
} as const;

export const fmt = (n: number) => Math.round(n).toLocaleString('en-US');
export const pct = (x: number, d = 1) => `${(100 * x).toFixed(d)}%`;

export const Rule = ({width, heavy = false}: {width: number; heavy?: boolean}) => (
  <Text color={C.dim}>{(heavy ? '━' : '─').repeat(Math.max(width, 1))}</Text>
);

// ---- big block digits (3 rows), used sparingly for the two counters ----
const FONT: Record<string, string[]> = {
  '0': ['█▀█', '█ █', '▀▀▀'], '1': ['▀█ ', ' █ ', '▀▀▀'],
  '2': ['▀▀█', '█▀▀', '▀▀▀'], '3': ['▀▀█', ' ▀█', '▀▀▀'],
  '4': ['█ █', '▀▀█', '  ▀'], '5': ['█▀▀', '▀▀█', '▀▀▀'],
  '6': ['█▀▀', '█▀█', '▀▀▀'], '7': ['▀▀█', '  █', '  ▀'],
  '8': ['█▀█', '█▀█', '▀▀▀'], '9': ['█▀█', '▀▀█', '▀▀▀'],
  '+': ['   ', '▀█▀', ' ▀ '], ',': ['   ', '   ', ' ▀ '],
  '%': ['▀ █', ' █ ', '█ ▀'], ' ': ['  ', '  ', '  '],
};
export const Big = ({s, color}: {s: string; color?: string}) => {
  const rows = [0, 1, 2].map(r =>
    s.split('').map(ch => (FONT[ch] ?? FONT[' '])[r]).join(' '),
  );
  return (
    <Box flexDirection="column">
      {rows.map((r, i) => (
        <Text key={i} color={color} bold>
          {r}
        </Text>
      ))}
    </Box>
  );
};

// ---- braille line chart: readable capacity curves in a terminal --------
type Series = {values: number[]; color?: string; label: string};
export function braillePlot(
  series: Series[], width: number, height: number, ymax?: number,
): {lines: React.ReactNode[]; legend: React.ReactNode} {
  const W = width * 2, H = height * 4;
  const top = ymax ?? (Math.max(...series.flatMap(s => s.values)) * 1.1 || 1);
  const grids = series.map(s => {
    const g: (0 | 1)[][] = Array.from({length: H}, () => Array(W).fill(0));
    const n = s.values.length;
    for (let px = 0; px < W; px++) {
      const t = (px / (W - 1)) * (n - 1);
      const i = Math.floor(t), frac = t - i;
      const v = i >= n - 1 ? s.values[n - 1]
        : s.values[i] * (1 - frac) + s.values[i + 1] * frac;
      const py = Math.min(H - 1, Math.max(0, Math.round((1 - v / top) * (H - 1))));
      g[py][px] = 1;
      if (py + 1 < H) g[py + 1][px] = 1; // thicker line, reads on video
    }
    return g;
  });
  const DOTS = [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]];
  const lines: React.ReactNode[] = [];
  for (let cy = 0; cy < height; cy++) {
    const parts: React.ReactNode[] = [];
    for (let cx = 0; cx < width; cx++) {
      let ch = 0, color: string | undefined;
      for (let si = series.length - 1; si >= 0; si--) {
        let mine = 0;
        for (let dy = 0; dy < 4; dy++)
          for (let dx = 0; dx < 2; dx++)
            if (grids[si][cy * 4 + dy][cx * 2 + dx]) mine |= DOTS[dy][dx];
        if (mine) { ch = mine; color = series[si].color; }
      }
      parts.push(
        <Text key={cx} color={color ?? C.dim}>
          {ch ? String.fromCharCode(0x2800 + ch) : ' '}
        </Text>,
      );
    }
    lines.push(<Box key={cy}>{parts}</Box>);
  }
  const legend = (
    <Box gap={3}>
      {series.map(s => (
        <Text key={s.label} color={s.color}>
          ── {s.label}
        </Text>
      ))}
    </Box>
  );
  return {lines, legend};
}

// ---- the wordmark: big block logotype for the landing screen -----------
const STRIKE_ROWS = [
  '███████ ████████ ██████  ██ ██   ██ ███████',
  '██         ██    ██   ██ ██ ██  ██  ██     ',
  '███████    ██    ██████  ██ █████   █████  ',
  '     ██    ██    ██   ██ ██ ██  ██  ██     ',
  '███████    ██    ██   ██ ██ ██   ██ ███████',
];
const ONE_ROWS = [
  ' ██████  ███    ██ ███████',
  '██    ██ ████   ██ ██     ',
  '██    ██ ██ ██  ██ █████  ',
  '██    ██ ██  ██ ██ ██     ',
  ' ██████  ██   ████ ███████',
];
export const Banner = ({width}: {width: number}) => {
  if (width < 80) {
    return (
      <Text bold>
        STRIKE <Text color={C.accent}>ONE</Text>
      </Text>
    );
  }
  return (
    <Box flexDirection="column" marginBottom={1}>
      {STRIKE_ROWS.map((row, i) => (
        <Text key={i}>
          <Text bold>{row}</Text>
          {'   '}
          <Text bold color={C.accent}>{ONE_ROWS[i]}</Text>
        </Text>
      ))}
      <Text color={C.dim}>
        {'  the corrected fraud evaluation. bring your scorer; nothing leaves the machine.'}
      </Text>
    </Box>
  );
};

export const Stat = ({label, value, color}: {label: string; value: string;
                      color?: string}) => (
  <Box flexDirection="column" marginRight={4}>
    <Text color={color} bold>{value}</Text>
    <Text color={C.dim}>{label}</Text>
  </Box>
);

export const Bar = ({parts, width}: {
  parts: {frac: number; color?: string; ch?: string}[]; width: number;
}) => (
  <Text>
    {parts.map((p, i) => (
      <Text key={i} color={p.color}>
        {(p.ch ?? '█').repeat(Math.max(0, Math.round(p.frac * width)))}
      </Text>
    ))}
  </Text>
);


// ------------------------------------------------------- line editor
// A real input line: cursor-indexed editing, chunk-safe (fast typing or
// paste can deliver '9\x7f' or 'text\r' as ONE stdin chunk), block
// cursor rendering, and mouse-click positioning handled by the app.
export type Ed = {text: string; cur: number};
export const edNew = (text = ''): Ed => ({text, cur: text.length});

const MOUSE_RE = /(?:\x1b)?\[?<\d+;\d+;\d+[mM]/g; // leaked SGR reports

function wordLeft(t: string, c: number) {
  let i = c;
  while (i > 0 && t[i - 1] === ' ') i--;
  while (i > 0 && t[i - 1] !== ' ') i--;
  return i;
}
function wordRight(t: string, c: number) {
  let i = c;
  while (i < t.length && t[i] === ' ') i++;
  while (i < t.length && t[i] !== ' ') i++;
  return i;
}

export function edApply(ed: Ed, rawInput: string | undefined, key: any):
    {ed: Ed; submit?: string; cancel?: boolean} {
  // a mouse report round-tripping through the key parser must be a
  // strict no-op (SAME object), or its stale-state set clobbers the
  // click handler's cursor move
  if (rawInput && /^(?:\x1b)?\[?<\d+;\d+;\d+[mM]$/.test(rawInput))
    return {ed};
  if (key?.escape) return {ed, cancel: true};
  let {text, cur} = ed;
  if (key?.leftArrow) {
    cur = (key.ctrl || key.meta) ? wordLeft(text, cur) : Math.max(0, cur - 1);
    return {ed: {text, cur}};
  }
  if (key?.rightArrow) {
    cur = (key.ctrl || key.meta) ? wordRight(text, cur)
                                 : Math.min(text.length, cur + 1);
    return {ed: {text, cur}};
  }
  const input = (rawInput ?? '').replace(MOUSE_RE, '');
  if (key?.ctrl) {
    if (input === 'a') return {ed: {text, cur: 0}};
    if (input === 'e') return {ed: {text, cur: text.length}};
    if (input === 'u') return {ed: {text: text.slice(cur), cur: 0}};
    if (input === 'k') return {ed: {text: text.slice(0, cur), cur}};
    if (input === 'w') {
      const w = wordLeft(text, cur);
      return {ed: {text: text.slice(0, w) + text.slice(cur), cur: w}};
    }
  }
  if (key?.return && !input) return {ed, submit: text};
  if ((key?.backspace || key?.delete) && !input) {
    if (cur > 0) { text = text.slice(0, cur - 1) + text.slice(cur); cur--; }
    return {ed: {text, cur}};
  }
  for (const ch of input) {
    if (ch === '\r' || ch === '\n') return {ed: {text, cur}, submit: text};
    if (ch === '\x7f' || ch === '\b') {
      if (cur > 0) { text = text.slice(0, cur - 1) + text.slice(cur); cur--; }
      continue;
    }
    if ((ch.codePointAt(0) ?? 0) < 32) continue;
    text = text.slice(0, cur) + ch + text.slice(cur);
    cur++;
  }
  return {ed: {text, cur}};
}

export const EditorText = ({ed}: {ed: Ed}) => {
  const {text, cur} = ed;
  const at = cur < text.length ? text[cur] : ' ';
  return (
    <Text>
      <Text>{text.slice(0, cur)}</Text>
      <Text inverse>{at}</Text>
      <Text>{cur < text.length ? text.slice(cur + 1) : ''}</Text>
    </Text>
  );
};
