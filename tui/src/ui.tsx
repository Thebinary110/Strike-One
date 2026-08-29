// Shared visual language. Restrained: a masthead, hairline rules, real
// spacing. Colour ONLY on data: green = prevented, amber = wasted,
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
