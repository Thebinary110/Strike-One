import React from 'react';
import {Box, Text} from 'ink';
import {Banner, Bar, Big, C, Rule, Stat, braillePlot, fmt, pct} from './ui.js';

export type Session = {
  status: 'none' | 'loading' | 'error' | 'ready';
  label?: string;
  error?: string;
  meta?: any; check?: any; audit?: any; route?: any;
  policy?: any; ranges?: any; worstCorner?: any;
  stream?: any; featured?: any[]; caseData?: any;
};

const Sentence = ({text, width}: {text: string; width: number}) => (
  <Box borderStyle="round" borderColor={C.accent} paddingX={2}
       width={Math.min(width, 96)}>
    <Text bold wrap="wrap">{text}</Text>
  </Box>
);

// ------------------------------------------------------------- CONNECT
export const Connect = ({s, width, pathBuf}: {s: Session; width: number;
                         pathBuf: string | null}) => (
  <Box flexDirection="column" gap={1}>
    <Banner width={width} />
    <Text bold>Point strikeone at labelled transactions. Nothing leaves this
 machine: no telemetry, no network calls.</Text>
    <Box flexDirection="column">
      <Text><Text bold color={C.accent}>[i]</Text>  the frozen IEEE-CIS worked
 example (proves the method; not a deployable model)</Text>
      <Text><Text bold color={C.accent}>[s]</Text>  synthetic demo, generated
 on the fly and labelled as such</Text>
      <Text><Text bold color={C.accent}>[p]</Text>  a path to your own
 parquet/CSV (uses the mapping in .strikeone.toml; set it up once with
 `strikeone check --map ... --save-config`)</Text>
    </Box>
    {pathBuf !== null && (
      <Text>path: <Text bold>{pathBuf}</Text><Text color={C.dim}> (enter to
 load, esc to cancel)</Text></Text>
    )}
    {s.status === 'loading' && <Text color={C.dim}>loading {s.label} ...</Text>}
    {s.status === 'error' && (
      <Box flexDirection="column">
        <Text color={C.harm} bold>could not load</Text>
        <Text wrap="wrap" color={C.dim}>{s.error}</Text>
      </Box>
    )}
    {s.status === 'ready' && s.check && (
      <Box flexDirection="column">
        <Rule width={Math.min(width - 2, 96)} />
        <Text bold>
          contract check: {s.check.ok
            ? <Text color={C.stop}>PASS</Text>
            : <Text color={C.harm}>FAIL</Text>}
          <Text color={C.dim}>  {s.label}</Text>
        </Text>
        {s.check.errors.map((e: string, i: number) => (
          <Text key={i} color={C.harm} wrap="wrap">  error  {e}</Text>
        ))}
        {s.check.warnings.map((w: string, i: number) => (
          <Text key={i} color={C.waste} wrap="wrap">  warning  {w}</Text>
        ))}
        {Object.entries(s.check.stats).map(([k, v]) => (
          <Text key={k} color={C.dim}>  {k}: {String(v)}</Text>
        ))}
        <Text color={C.dim}>next: press <Text color={C.ink}>2</Text> for the
 audit</Text>
      </Box>
    )}
  </Box>
);

// --------------------------------------------------------------- AUDIT
export const Audit = ({s, capIdx, width}: {s: Session; capIdx: number;
                       width: number}) => {
  const a = s.audit;
  if (!a) return <NeedData />;
  const b = a.budgets?.[capIdx];
  return (
    <Box flexDirection="column" gap={1}>
      <Box gap={6}>
        <Stat label="transactions" value={fmt(a.stats.rows)} />
        <Stat label="days" value={a.stats.days.toFixed(0)} />
        <Stat label="fraud cases" value={fmt(a.stats.episodes)} />
        <Stat label="later attempts on known entities"
          value={`${fmt(a.stats.propagated_rows)} (${pct(a.stats.propagated_share_of_positives, 0)} of fraud rows)`}
          color={C.waste} />
      </Box>
      <Box flexDirection="column">
        <Text bold>A plain blocklist, no model at all
          <Text color={C.dim}> ({a.stats.label_delay_days}-day label delay)
          </Text></Text>
        <Text>  recovers <Text bold color={C.waste}>
          {pct(a.blocklist.recovered_share, 0)}</Text> of your labelled fraud
          ({pct(a.blocklist.recovered_amount_share, 0)} of fraud amount) at
          {' '}{pct(a.blocklist.precision, 0)} precision, and stops
          <Text bold color={C.harm}> 0</Text> cases at the first attempt</Text>
      </Box>
      {a.headline && b && (
        <>
          <Rule width={Math.min(width - 2, 96)} />
          <Text bold>Your scorer
            <Text color={C.dim}>  headline AP {a.headline.ap.toFixed(4)},
            ROC-AUC {a.headline.roc_auc.toFixed(4)}   |   h/l to change the
            review budget</Text></Text>
          <Box gap={5}>
            <Box flexDirection="column">
              <Big s={pct(b.headline_recall, 0).replace('%', '')} color={C.ink} />
              <Text color={C.dim}>% headline recall</Text>
              <Text color={C.dim}>at {fmt(b.per_day)} alerts/day</Text>
            </Box>
            <Box flexDirection="column">
              <Big s={pct(b.fs_recall, 0).replace('%', '')} color={C.stop} />
              <Text color={C.dim}>% of fraud cases stopped</Text>
              <Text color={C.dim}>on the first attempt</Text>
            </Box>
            <Box flexDirection="column">
              <Big s={pct(b.redundancy_rate, 0).replace('%', '')}
                   color={C.waste} />
              <Text color={C.dim}>% of correct alerts wasted on</Text>
              <Text color={C.dim}>fraudsters already caught</Text>
            </Box>
          </Box>
          <Text color={C.harm} bold>
            {`wrongly flagged good customers at this budget: ${fmt(b.false_positives)}`}
            <Text color={C.dim}> (each worse than a wasted review)</Text>
          </Text>
          <Box flexDirection="column">
            <Text color={C.dim}>
              {'  alerts/day   headline   first-attempt   wasted-on-known   wrongly-flagged'}
            </Text>
            {a.budgets.map((r: any, i: number) => (
              <Text key={r.per_day} inverse={i === capIdx}>
                {`  ${String(r.per_day).padStart(9)}   ${pct(r.headline_recall).padStart(7)}   ${pct(r.fs_recall).padStart(12)}   ${pct(r.redundancy_rate).padStart(14)}   ${fmt(r.false_positives).padStart(14)}`}
                {r.primary ? <Text color={C.accent}>  {'<-'} matched to your
 fraud volume</Text> : null}
              </Text>
            ))}
          </Box>
        </>
      )}
      <Sentence text={a.sentence} width={width} />
    </Box>
  );
};

// --------------------------------------------------------------- ROUTE
export const Route = ({s, width}: {s: Session; width: number}) => {
  const r = s.route;
  if (!r) return <NeedData />;
  const w = Math.min(width - 14, 84);
  const plot = r.curve?.length
    ? braillePlot(
        [
          {values: r.curve.map((c: any) => c.fs_recall_off),
           color: C.harm, label: 'your scorer alone'},
          {values: r.curve.map((c: any) => c.fs_recall_on),
           color: C.stop, label: 'with the blocklist lane'},
        ], w, 10)
    : null;
  const prim = r.curve?.find((c: any) => c.primary) ?? r.curve?.[0];
  return (
    <Box flexDirection="column" gap={1}>
      <Text bold wrap="wrap">Lane 1 auto-blocks {fmt(r.lane1.rows)} transactions
 ({pct(r.lane1.row_share)}) on {fmt(r.lane1.entities)} known entities,
 consuming no reviews{typeof r.lane1.legit_blocked === 'number'
   ? <Text color={C.harm}> including {fmt(r.lane1.legit_blocked)} labelled
 legitimate: the standing policy's own cost, counted</Text> : null}</Text>
      {plot && (
        <Box flexDirection="column">
          <Text color={C.dim}>share of fraud cases stopped on the first
 attempt, by review budget (same scorer, lane off vs on)</Text>
          {plot.lines}
          <Box>
            <Text color={C.dim}>
              {r.curve.map((c: any) => String(c.per_day).padEnd(
                Math.floor(w / r.curve.length))).join('')}
            </Text>
          </Box>
          {plot.legend}
        </Box>
      )}
      {prim && (
        <Sentence width={width} text={
          `At ${fmt(prim.per_day)} alerts/day the same scorer stops ` +
          `${pct(prim.fs_recall_off, 1)} of fraud cases alone and ` +
          `${pct(prim.fs_recall_on, 1)} with the blocklist lane in front of ` +
          `it: ${prim.lift === Infinity ? 'from zero' : prim.lift.toFixed(2) + 'x'}` +
          ` the prevention, zero model changes. The routing protects any scorer.`
        } />
      )}
    </Box>
  );
};

// ----------------------------------------------------------- ECONOMICS
const ECON_META = [
  {k: 'm', label: 'Margin lost when you wrongly decline a good order',
   step: 0.01, fmt: (v: number) => pct(v, 0)},
  {k: 'a', label: 'Customers who abandon at a verification step',
   step: 0.005, fmt: (v: number) => pct(v, 1)},
  {k: 'e', label: 'How often a verification step actually stops a fraudster',
   step: 0.01, fmt: (v: number) => pct(v, 0)},
  {k: 'c_h', label: 'What a chargeback costs you to handle (amount units)',
   step: 2.5, fmt: (v: number) => v.toFixed(0)},
];
export const Econ = ({s, params, sel, width}: {s: Session; params: any;
                      sel: number; width: number}) => {
  if (!s.meta) return <NeedData />;
  if (!s.meta.has_p)
    return <Text wrap="wrap" color={C.dim}>This dataset has no calibrated
 probability column, so there is nothing to price. Map one with
 `--map p=&lt;column&gt;` (calibrate your scorer first; that step is yours).
 The IEEE-CIS worked example includes one.</Text>;
  const p = s.policy;
  const ranges = s.ranges ?? {};
  const barW = Math.min(width - 30, 60);
  return (
    <Box flexDirection="column" gap={1}>
      <Text color={C.dim}>Set what mistakes cost you; j/k select, h/l adjust.
 Policy inputs only: the model and its calibration stay frozen, and every
 value stays inside the ranges declared before any result was seen.</Text>
      <Box flexDirection="column">
        {ECON_META.map((m, i) => {
          const rng = ranges[m.k] ?? [0, 1];
          const v = params[m.k];
          const frac = (v - rng[0]) / (rng[rng.length - 1] - rng[0] || 1);
          return (
            <Box key={m.k} flexDirection="column">
              <Text inverse={i === sel}>
                {` ${m.label.padEnd(58)} ${m.fmt(v).padStart(6)} `}
              </Text>
              <Text color={i === sel ? C.accent : C.dim}>
                {' ' + '─'.repeat(Math.round(frac * barW)) + '●'
                 + '─'.repeat(Math.max(0, barW - Math.round(frac * barW)))}
              </Text>
            </Box>
          );
        })}
      </Box>
      {p && (
        <Box flexDirection="column" gap={1}>
          <Box flexDirection="column">
            <Text bold>Recommended actions across the window</Text>
            <Bar width={Math.min(width - 8, 80)} parts={[
              {frac: p.mix.pct[0] / 100, color: C.stop, ch: '█'},
              {frac: p.mix.pct[1] / 100, color: C.waste, ch: '█'},
              {frac: p.mix.pct[2] / 100, color: C.harm, ch: '█'},
            ]} />
            <Text color={C.dim}>
              approve {p.mix.pct[0]}%   ask to verify {p.mix.pct[1]}%   block
              {' '}{p.mix.pct[2]}%
            </Text>
          </Box>
          {p.costs?.policy != null && (
            <Box gap={6}>
              <Stat label="what this window would have cost you"
                    value={fmt(p.costs.policy)} />
              <Stat label="if you approved everything" color={C.dim}
                    value={fmt(p.costs.approve_all)} />
              <Stat label="saved vs approving everything" color={C.stop}
                    value={pct(p.costs.savings)} />
            </Box>
          )}
          {s.worstCorner && (
            <Text wrap="wrap" color={C.waste}>
              honest corner: at m={s.worstCorner.m}, a={s.worstCorner.a},
              e={s.worstCorner.e}, c_h={s.worstCorner.c_h} the cost-derived
              policy's edge over a plain fixed threshold is
              {' '}{pct(s.worstCorner.edge_vs_fixed, 2)} of approve-all cost,
              its weakest point in the declared ranges. Shown, not hidden.
            </Text>
          )}
          <Text color={C.dim}>amounts are in the dataset's own currency units</Text>
        </Box>
      )}
    </Box>
  );
};

// ---------------------------------------------------------------- STREAM
export const Stream = ({s, shownRows, paused, width}: {s: Session;
                        shownRows: any[]; paused: boolean; width: number}) => {
  if (!s.stream) return <NeedData />;
  return (
    <Box flexDirection="column" gap={1}>
      <Text color={C.dim}>
        replaying the decisions at {fmt(s.stream.per_day)} alerts/day
        ({fmt(s.stream.n_events)} events in the window)
        {paused ? '   PAUSED (space)' : '   space to pause'}
      </Text>
      <Box flexDirection="column">
        <Text color={C.dim}>
          {'   day     amount   route            '}
        </Text>
        {shownRows.map((r, i) => (
          <Text key={i} bold={r.caught_fs}
                backgroundColor={r.caught_fs && !process.env.NO_COLOR
                  ? '#0d3524' : undefined}>
            {`  ${r.day.toFixed(2).padStart(6)}  ${r.amount.toFixed(2).padStart(9)}  `}
            {r.lane === 'auto-block'
              ? <Text color={C.harm}>auto-block, no review</Text>
              : <Text color={C.accent}>review</Text>}
            {'   '}
            {r.caught_fs
              ? <Text color={C.stop} bold>FIRST ATTEMPT, STOPPED</Text>
              : r.role === 2
                ? <Text color={C.waste}>already covered</Text>
                : <Text color={C.dim}>{r.label === 0 ? 'legitimate' : ''}</Text>}
          </Text>
        ))}
      </Box>
    </Box>
  );
};

// ----------------------------------------------------------------- CASE
export const Case = ({s, reveal, width}: {s: Session; reveal: number;
                      width: number}) => {
  const c = s.caseData;
  if (!c) return <NeedData />;
  const rows = c.rows as any[];
  const w = Math.min(width - 10, 100);
  const lo = rows[0].day, hi = rows[rows.length - 1].day + 1e-9;
  const X = (d: number) =>
    Math.min(w - 1, Math.max(0, Math.round(((d - lo) / (hi - lo)) * (w - 1))));
  const line: {ch: string; color?: string; bold?: boolean}[] =
    Array.from({length: w}, () => ({ch: '─', color: C.dim}));
  const shown = rows.slice(0, reveal);
  for (const r of shown) {
    const x = X(r.day);
    if (r.role === 2) line[x] = {ch: '▲', color: C.waste, bold: true};
    else if (r.role !== 1) line[x] = {ch: '●', color: C.dim};
  }
  for (const r of shown)  // the first attempt is never overdrawn
    if (r.role === 1) line[X(r.day)] = {ch: '◆', color: C.harm, bold: true};
  const fsX = rows.find(r => r.role === 1) ? X(rows.find(r => r.role === 1).day) : null;
  const frauds = rows.filter(r => r.label === 1);
  const lastFraudX = frauds.length ? X(frauds[frauds.length - 1].day) : null;
  const done = reveal >= rows.length;
  const bandStart = fsX ?? 0;
  const bandLen = lastFraudX !== null && fsX !== null
    ? Math.max(lastFraudX - fsX, 8) : 0;
  return (
    <Box flexDirection="column" gap={1}>
      <Text bold>Customer identity {c.entity}
        <Text color={C.dim}>  {rows.length} transactions,
        {' '}{frauds.length} fraudulent   |   n = next case</Text></Text>
      <Box flexDirection="column">
        {fsX !== null && (
          <Text>
            {' '.repeat(Math.max(0, Math.min(fsX - 8, w - 18)))}
            <Text color={C.harm} bold>THE FIRST ATTEMPT</Text>
          </Text>
        )}
        <Text>
          {line.map((c2, i) => (
            <Text key={i} color={c2.color} bold={c2.bold}>{c2.ch}</Text>
          ))}
        </Text>
        {done && bandLen > 0 && (
          <>
            <Text>
              {' '.repeat(bandStart)}
              <Text color={C.waste}>{'▔'.repeat(bandLen)}</Text>
            </Text>
            <Text>
              {' '.repeat(Math.max(0, Math.min(bandStart,
                w - 62)))}
              <Text color={C.waste}>already covered by the blocklist.
 catching these prevents nothing</Text>
            </Text>
          </>
        )}
      </Box>
      <Text color={C.dim}>
        ● normal purchase   <Text color={C.harm}>◆ the first attempt</Text>
        {'   '}<Text color={C.waste}>▲ later attempt, already covered</Text>
      </Text>
      <Box flexDirection="column">
        {shown.slice(-6).map((r, i) => (
          <Text key={i} color={r.role === 1 ? C.harm
            : r.role === 2 ? C.waste : C.dim}>
            {`  day ${r.day.toFixed(2).padStart(6)}   amount ${r.amount.toFixed(2).padStart(9)}   `}
            {r.role === 1 ? 'THE FIRST ATTEMPT'
              : r.role === 2 ? 'later attempt, already covered'
              : 'normal purchase'}
          </Text>
        ))}
      </Box>
      <Text color={C.dim} wrap="wrap">fraud-case roles are an evaluation
 overlay computed from ground truth; the system never sees them when
 deciding</Text>
    </Box>
  );
};

const NeedData = () => (
  <Text color={C.dim}>no dataset loaded; press 1 and pick a source</Text>
);
