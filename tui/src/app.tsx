import React, {useEffect, useMemo, useRef, useState} from 'react';
import {Box, Text, useApp, useInput, useStdout} from 'ink';
import {Rpc} from './rpc.js';
import {C, Rule} from './ui.js';
import {Audit, Case, Connect, Econ, Route, Session, Stream} from './screens.js';

const TABS = ['CONNECT', 'AUDIT', 'ROUTE', 'ECONOMICS', 'STREAM', 'CASE'];
const CENTRAL = {m: 0.15, a: 0.125, e: 0.775, c_h: 30.0};

export const App = ({initialExample, frameTab, motion}: {
  initialExample?: string; frameTab?: number; motion: boolean;
}) => {
  const {exit} = useApp();
  const {stdout} = useStdout();
  const [size, setSize] = useState({w: stdout.columns ?? 120,
                                    h: stdout.rows ?? 34});
  const [tab, setTab] = useState(frameTab ?? 0);
  const [help, setHelp] = useState(false);
  const [sess, setSess] = useState<Session>({status: 'none'});
  const [capIdx, setCapIdx] = useState(0);
  const [params, setParams] = useState<any>({...CENTRAL});
  const [econSel, setEconSel] = useState(0);
  const [paused, setPaused] = useState(false);
  const [streamPos, setStreamPos] = useState(0);
  const [caseIdx, setCaseIdx] = useState(0);
  const [reveal, setReveal] = useState(0);
  const [pathBuf, setPathBuf] = useState<string | null>(null);
  const rpc = useMemo(() => new Rpc(), []);
  const econTimer = useRef<any>(null);

  useEffect(() => {
    const onResize = () =>
      setSize({w: stdout.columns ?? 120, h: stdout.rows ?? 34});
    stdout.on('resize', onResize);
    return () => { stdout.off('resize', onResize); rpc.kill(); };
  }, []);

  async function load(kind: {example?: string; source?: string}) {
    const label = kind.example ?? kind.source!;
    setSess({status: 'loading', label});
    try {
      await rpc.call('init', kind.example
        ? {example: kind.example} : {source: kind.source});
      const [meta, check] = await Promise.all(
        [rpc.call('meta'), rpc.call('check')]);
      const next: Session = {status: 'ready', label, meta, check};
      setSess({...next});
      if (meta.has_label) {
        const [audit, route, featured] = await Promise.all([
          rpc.call('audit'), rpc.call('route_curve'), rpc.call('featured'),
        ]);
        next.audit = audit; next.route = route; next.featured = featured;
        const pi = audit.budgets?.findIndex((b: any) => b.primary) ?? 0;
        setCapIdx(Math.max(pi, 0));
        setSess({...next});
        if (meta.has_score) {
          next.stream = await rpc.call('stream', {limit: 400});
          setSess({...next});
        }
        if (featured?.length) {
          next.caseData = await rpc.call('case',
            {entity: featured[0].entity});
          setReveal(motion ? 0 : next.caseData.rows.length);
          setSess({...next});
        }
        if (meta.has_p) {
          const pol = await rpc.call('policy', {...CENTRAL, grid: true});
          next.policy = pol; next.ranges = pol.ranges;
          next.worstCorner = pol.worst_corner;
          setSess({...next});
        }
      }
    } catch (e: any) {
      setSess({status: 'error', label, error: String(e.message ?? e)});
    }
  }

  useEffect(() => {
    if (initialExample) load({example: initialExample});
  }, []);

  // frame mode: render once loaded, then exit (used for captures/tests)
  useEffect(() => {
    if (frameTab === undefined) return;
    if (sess.status === 'ready' && (frameTab !== 5 || sess.caseData)) {
      const t = setTimeout(() => exit(), 400);
      return () => clearTimeout(t);
    }
  }, [sess, frameTab]);

  // stream ticker
  useEffect(() => {
    if (!motion || paused || tab !== 4 || !sess.stream) return;
    const t = setInterval(() => setStreamPos(p => p + 1), 650);
    return () => clearInterval(t);
  }, [motion, paused, tab, sess.stream]);

  // case unfolding
  useEffect(() => {
    if (!sess.caseData) return;
    if (!motion) { setReveal(sess.caseData.rows.length); return; }
    if (reveal >= sess.caseData.rows.length) return;
    const t = setTimeout(() => setReveal(r => r + 1), 240);
    return () => clearTimeout(t);
  }, [reveal, sess.caseData, motion]);

  function econAdjust(dir: 1 | -1) {
    const meta = [['m', 0.01], ['a', 0.005], ['e', 0.01], ['c_h', 2.5]] as const;
    const [k, step] = meta[econSel];
    const rng = (sess.ranges ?? {})[k] ?? [0, 1e9];
    setParams((p: any) => {
      const v = Math.min(Math.max(p[k] + dir * step, rng[0]),
                         rng[rng.length - 1]);
      const np = {...p, [k]: Number(v.toFixed(4))};
      clearTimeout(econTimer.current);
      econTimer.current = setTimeout(async () => {
        try {
          const pol = await rpc.call('policy', {...np, grid: false});
          setSess(s => ({...s, policy: pol}));
        } catch { /* surfaced elsewhere */ }
      }, 140);
      return np;
    });
  }

  async function nextCase() {
    if (!sess.featured?.length) return;
    const i = (caseIdx + 1) % sess.featured.length;
    setCaseIdx(i);
    const cd = await rpc.call('case', {entity: sess.featured[i].entity});
    setReveal(motion ? 0 : cd.rows.length);
    setSess(s => ({...s, caseData: cd}));
  }

  useInput((input, key) => {
    if (pathBuf !== null) {
      if (key.return) { const p = pathBuf; setPathBuf(null); load({source: p}); }
      else if (key.escape) setPathBuf(null);
      else if (key.backspace || key.delete)
        setPathBuf(pathBuf.slice(0, -1));
      else if (input) setPathBuf(pathBuf + input);
      return;
    }
    if (input === 'q') { exit(); return; }
    if (input === '?') { setHelp(h => !h); return; }
    if (key.tab && key.shift) { setTab(t => (t + 5) % 6); return; }
    if (key.tab) { setTab(t => (t + 1) % 6); return; }
    if (/[1-6]/.test(input)) { setTab(Number(input) - 1); return; }
    const nb = sess.audit?.budgets?.length ?? 0;
    if (tab === 0) {
      if (input === 'i') load({example: 'ieee-cis'});
      if (input === 's') load({example: 'synthetic'});
      if (input === 'p') setPathBuf('');
    } else if (tab === 1 || tab === 2) {
      if ((input === 'l' || key.rightArrow) && nb)
        setCapIdx(i => Math.min(i + 1, nb - 1));
      if ((input === 'h' || key.leftArrow) && nb)
        setCapIdx(i => Math.max(i - 1, 0));
    } else if (tab === 3) {
      if (input === 'j' || key.downArrow) setEconSel(s => (s + 1) % 4);
      if (input === 'k' || key.upArrow) setEconSel(s => (s + 3) % 4);
      if (input === 'l' || key.rightArrow) econAdjust(1);
      if (input === 'h' || key.leftArrow) econAdjust(-1);
    } else if (tab === 4) {
      if (input === ' ') setPaused(p => !p);
    } else if (tab === 5) {
      if (input === 'n') nextCase();
    }
  }, {isActive: process.stdin.isTTY === true});

  const shownRows = useMemo(() => {
    const rows = sess.stream?.rows ?? [];
    if (!rows.length) return [];
    const end = motion ? (streamPos % (rows.length + 12)) : 12;
    return rows.slice(Math.max(0, end - 12), Math.max(end, 12));
  }, [sess.stream, streamPos, motion]);

  const width = size.w;
  const narrow = width < 100;
  return (
    <Box flexDirection="column" paddingX={1}>
      <Box justifyContent="space-between">
        <Text>
          <Text backgroundColor={process.env.NO_COLOR ? undefined : 'white'}
                color={process.env.NO_COLOR ? undefined : 'black'}
                bold> S1 </Text>
          <Text bold> STRIKE ONE</Text>
          <Text color={C.dim}>  the corrected fraud evaluation</Text>
        </Text>
        <Text color={C.dim}>? help  q quit</Text>
      </Box>
      <Rule width={width - 2} heavy />
      <Box gap={narrow ? 1 : 3}>
        {TABS.map((t, i) => (
          <Text key={t} inverse={i === tab}
                color={i === tab ? undefined : C.dim} bold={i === tab}>
            {` ${i + 1} ${t} `}
          </Text>
        ))}
        {sess.status === 'ready' && (
          <Text color={C.dim}>
            {sess.meta?.rows ? ` ${sess.label}` : ''}
          </Text>
        )}
      </Box>
      <Rule width={width - 2} />
      <Box marginTop={1} flexDirection="column" minHeight={20}>
        {help ? <Help /> : (
          tab === 0 ? <Connect s={sess} width={width} pathBuf={pathBuf} /> :
          tab === 1 ? <Audit s={sess} capIdx={capIdx} width={width} /> :
          tab === 2 ? <Route s={sess} width={width} /> :
          tab === 3 ? <Econ s={sess} params={params} sel={econSel}
                            width={width} /> :
          tab === 4 ? <Stream s={sess} shownRows={shownRows} paused={paused}
                              width={width} /> :
                      <Case s={sess} reveal={reveal} width={width} />
        )}
      </Box>
      <Rule width={width - 2} />
      <Text color={C.dim} wrap="truncate">
        we ship the method and the measurement; you bring the scorer. The
 IEEE-CIS run is a worked example, not a deployable model.
      </Text>
    </Box>
  );
};

const Help = () => (
  <Box flexDirection="column" gap={1}>
    <Text bold>Keys</Text>
    <Text color={C.dim}>{`  tab / shift-tab   next / previous panel
  1..6              jump to a panel
  h l  (or arrows)  change budget (AUDIT, ROUTE) or adjust a value (ECONOMICS)
  j k               select an economics input
  space             pause the decision stream
  n                 next case (CASE)
  ?                 toggle this help     q  quit`}</Text>
    <Text color={C.dim} wrap="wrap">Every figure is computed live by the local
 Python core over stdio. No HTTP, no ports, no telemetry.</Text>
  </Box>
);
