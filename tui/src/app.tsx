import React, {useEffect, useMemo, useRef, useState} from 'react';
import {Box, Text, useApp, useInput, useStdout} from 'ink';
import {Rpc} from './rpc.js';
import {C, Ed, edApply, edNew, EditorText, Rule} from './ui.js';
import {Ai, Audit, Case, Connect, Econ, Route, Session, Stream, Wizard, Wiz} from './screens.js';

const TABS = ['CONNECT', 'AUDIT', 'ROUTE', 'ECONOMICS', 'STREAM', 'CASE', 'AI'];

// live suggestions under the input box, Claude-Code style
const PALETTE: Array<{fill: string; desc: string}> = [
  {fill: 'audit',    desc: 'the corrected evaluation (audit 50 = at 50 reviews/day)'},
  {fill: 'why ',      desc: 'why one transaction got its decision (AI, cited)'},
  {fill: 'timeline ', desc: 'narrate one fraud case (entity id)'},
  {fill: 'compare ',  desc: 'blocklist lane vs scorer on one transaction'},
  {fill: 'evidence why ', desc: 'the raw evidence for a transaction (no AI)'},
  {fill: 'onboard ',  desc: 'map a new file (wizard; label always confirmed)'},
  {fill: 'source ',   desc: 'load a mapped file'},
  {fill: 'example synthetic', desc: 'load the instant demo data'},
  {fill: 'capacity ', desc: 're-run the audit at your real reviews/day'},
  {fill: 'case ',     desc: 'inspect one entity\u2019s case'},
  {fill: 'route',    desc: 'blocklist-lane lift, on vs off'},
  {fill: 'policy ',   desc: 'reprice decisions (policy e=0.8 s=0.5)'},
  {fill: 'stream',   desc: 'watch the decision stream'},
  {fill: 'provider', desc: 'where AI requests would go'},
  {fill: 'setup ollama ', desc: 'configure a local AI model'},
  {fill: 'pause',    desc: 'pause/resume the stream'},
  {fill: 'next',     desc: 'next featured case'},
  {fill: 'help',     desc: 'all commands and keys'},
  {fill: 'quit',     desc: 'leave'},
];
function suggest(text: string): Array<{fill: string; desc: string}> {
  const t = text.trimStart().replace(/^\//, '').toLowerCase();
  if (!t) return [];
  return PALETTE.filter(p => p.fill.startsWith(t) && p.fill.trim() !== t);
}
const CENTRAL = {m: 0.15, a: 0.125, e: 0.775, c_h: 30.0};

export const App = ({initialExample, initialSource, frameTab, motion}: {
  initialExample?: string; initialSource?: string; frameTab?: number;
  motion: boolean;
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
  const [cmdEd, setCmdEd] = useState<Ed>(edNew());
  const [note, setNote] = useState<string | null>(null);
  const hist = useRef<string[]>([]);
  const histIdx = useRef(-1);
  const [wiz, setWiz] = useState<Wiz | null>(null);
  const rpc = useMemo(() => new Rpc(), []);
  const econTimer = useRef<any>(null);

  useEffect(() => {
    const onResize = () =>
      setSize({w: stdout.columns ?? 120, h: stdout.rows ?? 34});
    stdout.on('resize', onResize);
    return () => { stdout.off('resize', onResize); rpc.kill(); };
  }, []);

  // mouse-click cursor positioning in the command bar: xterm SGR mouse
  // reporting while the bar is open; a raw stdin listener (Ink cannot
  // parse mouse reports) maps the click column onto the cursor index.
  const CMD_TEXT_X = 6;   // app pad + bar border + bar pad + '/ ' prompt
  useEffect(() => {
    if (process.stdin.isTTY !== true) return;
    stdout.write('\x1b[?1000h\x1b[?1006h');
    return () => { stdout.write('\x1b[?1000l\x1b[?1006l'); };
  }, []);
  useEffect(() => {
    if (process.stdin.isTTY !== true) return;
    const onData = (d: Buffer) => {
      const m = /\x1b\[<0;(\d+);\d+M/.exec(d.toString('latin1'));
      if (!m) return;
      const x = Number(m[1]);
      setCmdEd(ed => ({...ed, cur: Math.max(0, Math.min(ed.text.length,
                                                         x - CMD_TEXT_X))}));
    };
    process.stdin.on('data', onData);
    return () => { process.stdin.off('data', onData); };
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
    if (initialSource) load({source: initialSource});
    else if (initialExample) load({example: initialExample});
  }, []);

  // frame mode: exit only once the tab's own content has arrived
  useEffect(() => {
    if (frameTab === undefined) return;
    if (sess.status === 'error') {
      const t = setTimeout(() => exit(), 200);
      return () => clearTimeout(t);
    }
    if (sess.status !== 'ready') return;
    const contentReady = [
      !!sess.check,
      !!sess.audit,
      !!sess.route,
      !!sess.policy || !sess.meta?.has_p,
      !!sess.stream || !sess.meta?.has_score,
      !!sess.caseData,
    ][frameTab];
    if (contentReady) {
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

  async function recap(n: number) {
    if (!Number.isFinite(n) || n <= 0) throw new Error('capacity must be a positive number');
    const audit = await rpc.call('audit', {capacity: n});
    const pi = audit.budgets?.findIndex((b: any) => b.primary) ?? 0;
    setCapIdx(Math.max(pi, 0));
    setSess(s => ({...s, audit}));
  }

  // ------------------- in-TUI onboarding wizard (same gates as the CLI:
  // label/entity/competing timestamps are always human questions; every
  // answer is validated on the real data; nothing written until finish)
  async function startOnboard(path: string) {
    setTab(6);
    setSess(s => ({...s, ai: {title: `onboard ${path}`,
                              text: 'scanning dataset...', busy: true}}));
    try {
      const scan = await rpc.call('onboard_scan', {source: path});
      setSess(s => ({...s, ai: undefined}));
      if (!scan.pending.length) {
        setWiz({source: path, rows: scan.rows, queue: [], idx: 0,
                phase: 'delay', ed: edNew(), tomlExists: scan.toml_exists,
                aiNote: scan.ai_note, labelSet: false});
        return;
      }
      setWiz({source: path, rows: scan.rows, queue: scan.pending, idx: 0,
              phase: 'ask', ed: edNew(), tomlExists: scan.toml_exists,
              aiNote: scan.ai_note, labelSet: false});
    } catch (e: any) {
      setSess(s => ({...s, ai: {title: `onboard ${path}`,
                                text: `error: ${String(e?.message ?? e)}`}}));
    }
  }

  async function wizAdvance(w: Wiz, labelSet: boolean) {
    if (w.idx + 1 < w.queue.length) {
      setWiz({...w, idx: w.idx + 1, phase: 'ask', ed: edNew(), msg: undefined,
              labelSet});
    } else if (labelSet) {
      setWiz({...w, phase: 'delay', ed: edNew(), msg: undefined, labelSet});
    } else {
      await wizFinish({...w, labelSet}, '7');
    }
  }

  async function wizSubmit(w: Wiz, text: string) {
    const t = w.queue[w.idx];
    const row = w.rows.find((r: any) => r.target === t);
    const src = text.trim() || row?.source;
    try {
      if (!src || src === 'skip') {
        if (row?.required) { setWiz({...w, ed: edNew(), msg: `${t} is required; type a column name (esc aborts)`}); return; }
        await rpc.call('onboard_skip', {target: t});
        await wizAdvance(w, w.labelSet);
        return;
      }
      const v = await rpc.call('onboard_validate', {target: t, source: src});
      if (v.hard?.length) {
        setWiz({...w, ed: edNew(), msg: `REJECTED: ${v.hard.join('; ')}`});
        return;
      }
      if (v.soft?.length) {
        setWiz({...w, phase: 'consent', pendingSrc: v.source,
                warnings: v.soft, ed: edNew()});
        return;
      }
      await rpc.call('onboard_accept', {target: t, source: v.source});
      await wizAdvance(w, w.labelSet || t === 'label');
    } catch (e: any) {
      setWiz({...w, ed: edNew(), msg: String(e?.message ?? e)});
    }
  }

  async function wizConsent(w: Wiz, yes: boolean) {
    const t = w.queue[w.idx];
    if (!yes) { setWiz({...w, phase: 'ask', ed: edNew(), pendingSrc: undefined,
                        warnings: undefined,
                        msg: 'declined; pick another column'}); return; }
    try {
      await rpc.call('onboard_accept', {target: t, source: w.pendingSrc});
      await wizAdvance({...w, pendingSrc: undefined, warnings: undefined},
                       w.labelSet || t === 'label');
    } catch (e: any) {
      setWiz({...w, phase: 'ask', ed: edNew(), msg: String(e?.message ?? e)});
    }
  }

  async function wizFinish(w: Wiz, delayText: string, overwrite = false) {
    const delay = Number(delayText.trim() || '7');
    if (!Number.isFinite(delay) || delay < 0) {
      setWiz({...w, ed: edNew(), msg: 'delay must be a number of days'});
      return;
    }
    try {
      const r = await rpc.call('onboard_finish', {delay, overwrite});
      if (r.needs_overwrite) {
        setWiz({...w, phase: 'overwrite', delay: String(delay), ed: edNew()});
        return;
      }
      setWiz(null);
      setSess(s => ({...s, ai: {title: `onboard ${w.source}`,
        text: `${r.auto} mapping(s) auto-accepted, ${r.confirmed} human-confirmed` +
          String.fromCharCode(10) + `written: ${r.written.join(', ')}` +
          String.fromCharCode(10) + String.fromCharCode(10) +
          `load it now: /source ${w.source}`}}));
    } catch (e: any) {
      setWiz({...w, msg: String(e?.message ?? e)});
    }
  }

  // deterministic slash-command router: the input line maps 1:1 onto rpc
  // methods and tab switches; no model ever chooses what runs.
  async function runCommand(raw: string) {
    const parts = raw.trim().replace(/^\//, '').split(/\s+/).filter(Boolean);
    if (!parts.length) return;
    const c = parts[0].toLowerCase();
    const arg = parts.slice(1);
    const show = (title: string, text: string, busy = false) =>
      setSess(s => ({...s, ai: {title, text, busy}}));
    try {
      switch (c) {
        case 'help': setHelp(true); return;
        case 'quit': case 'exit': case 'q': exit(); return;
        case '1': case '2': case '3': case '4': case '5': case '6':
        case '7': setTab(Number(c) - 1); return;
        case 'pause': setPaused(v => !v); setTab(4); return;
        case 'next': void nextCase(); setTab(5); return;
        case 'example': load({example: arg[0] ?? 'synthetic'}); return;
        case 'source': case 'open':
          if (arg[0]) load({source: arg[0]});
          else setNote('usage: /source <path>');
          return;
        case 'connect': case 'check': setTab(0); return;
        case 'audit':
          setTab(1);
          if (arg[0] !== undefined) await recap(Number(arg[0]));
          return;
        case 'capacity':
          if (arg[0] === undefined) { setNote('usage: /capacity <reviews per day>'); return; }
          await recap(Number(arg[0])); setTab(1);
          return;
        case 'route': setTab(2); return;
        case 'policy': {
          setTab(3);
          if (arg.length) {
            const np: any = {...params};
            for (const kv of arg) {
              const [k, v] = kv.split('=');
              if (k && v !== undefined && Number.isFinite(Number(v))) np[k] = Number(v);
            }
            setParams(np);
            const pol = await rpc.call('policy', {...np, grid: false});
            setSess(s => ({...s, policy: pol}));
          }
          return;
        }
        case 'stream': setTab(4); return;
        case 'case':
          setTab(5);
          if (arg.length) {
            const cd = await rpc.call('case', {entity: arg.join(' ')});
            setReveal(motion ? 0 : cd.rows.length);
            setSess(s => ({...s, caseData: cd}));
          }
          return;
        case 'why': case 'timeline': case 'compare': {
          setTab(6);
          if (!arg[0]) { show(c, `usage: /${c} <${c === 'timeline' ? 'case id' : 'transaction id'}>`); return; }
          show(`${c} ${arg[0]}`, 'narrating - every claim will be validated against the evidence contract...', true);
          const r = await rpc.call('ai', {cmd: c, target: arg[0]});
          show(`${c} ${arg[0]}`, r.text ?? r.error_text ?? '(no output)');
          return;
        }
        case 'evidence': {
          setTab(6);
          if (!arg[0] || !arg[1]) { show('evidence', 'usage: /evidence <why|timeline|compare> <id>  (deterministic, no model)'); return; }
          show(`evidence ${arg[0]} ${arg[1]}`, 'computing...', true);
          const r = await rpc.call('evidence', {cmd: arg[0], target: arg[1]});
          show(`evidence ${arg[0]} ${arg[1]}`, r.text);
          return;
        }
        case 'provider': {
          setTab(6);
          const r = await rpc.call('provider_chain');
          show('provider', r.text);
          return;
        }
        case 'onboard': {
          if (!arg[0]) { setTab(6); show('onboard', 'usage: /onboard <file.csv|parquet>'); return; }
          void startOnboard(arg[0]);
          return;
        }
        case 'setup': {
          setTab(6);
          const usage = 'usage:\n  /setup ollama <model> [think:off]\n  /setup openai <base_url> <model> <API_KEY_ENV_NAME>\nnever type a key itself - export it in your shell and give its NAME';
          if (!arg[0]) { show('setup', usage); return; }
          const kind = arg[0].toLowerCase();
          let params: any = null;
          if (kind === 'ollama' && arg[1])
            params = {provider: 'ollama', model: arg[1],
                      think: (arg[2] ?? '').replace('think:', '')};
          else if ((kind === 'openai' || kind === 'openai-compatible') && arg[1] && arg[2])
            params = {provider: 'openai-compatible', base_url: arg[1],
                      model: arg[2], api_key_env: arg[3]};
          if (!params) { show('setup', usage); return; }
          show('setup', 'writing provider config...', true);
          const r = await rpc.call('ai_setup', params);
          show('setup', r.text);
          return;
        }
        default:
          setTab(6);
          show(raw, `unknown command: /${c}\n\ncommands: audit [n] . capacity n . route . policy k=v . stream . case [id]\nwhy <txn> . timeline <case> . compare <txn> . evidence <cmd> <id> . provider\nsource <path> . example <name> . onboard . setup . help . quit`);
          return;
      }
    } catch (e: any) {
      setTab(6);
      show(raw, `error: ${String(e?.message ?? e)}`);
    }
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
    if (wiz) {
      if (key.escape) {
        void rpc.call('onboard_abort');
        setWiz(null);
        setNote('onboarding aborted; nothing was written');
        return;
      }
      if (wiz.phase === 'consent') {
        const ch = (input ?? '').toLowerCase();
        if (ch === 'y') void wizConsent(wiz, true);
        else if (ch === 'n') void wizConsent(wiz, false);
        return;
      }
      if (wiz.phase === 'overwrite') {
        const ch = (input ?? '').toLowerCase();
        if (ch === 'y') void wizFinish(wiz, wiz.delay ?? '7', true);
        else if (ch === 'n') {
          setWiz(null);
          setNote('kept the existing .strikeone.toml; nothing written');
        }
        return;
      }
      // text phases: ask, delay - full line editor
      const r = edApply(wiz.ed, input, key);
      if (r.submit === undefined && !r.cancel && r.ed === wiz.ed) return;
      if (r.cancel) {
        void rpc.call('onboard_abort');
        setWiz(null);
        setNote('onboarding aborted; nothing was written');
        return;
      }
      if (r.submit !== undefined) {
        if (wiz.phase === 'delay')
          void wizFinish({...wiz, ed: edNew()}, r.submit);
        else void wizSubmit({...wiz, ed: edNew()}, r.submit);
      } else setWiz({...wiz, ed: r.ed});
      return;
    }
    // ------- chat-first input: the box is ALWAYS focused. Type, enter.
    // tab completes a suggestion when typing, switches panels otherwise;
    // up/down = history; left/right when empty = budget row (AUDIT/ROUTE)
    if (key.upArrow || key.downArrow) {
      if (tab === 3 && cmdEd.text === '') {   // econ selection stays on arrows
        if (key.downArrow) setEconSel(v => (v + 1) % 4);
        else setEconSel(v => (v + 3) % 4);
        return;
      }
      const h = hist.current;
      if (h.length) {
        histIdx.current = key.upArrow
          ? Math.min(histIdx.current + 1, h.length - 1)
          : Math.max(histIdx.current - 1, -1);
        setCmdEd(edNew(histIdx.current < 0
          ? '' : h[h.length - 1 - histIdx.current]));
      }
      return;
    }
    if ((key.leftArrow || key.rightArrow) && cmdEd.text === '') {
      const nb = sess.audit?.budgets?.length ?? 0;
      if ((tab === 1 || tab === 2) && nb) {
        setCapIdx(i => key.rightArrow ? Math.min(i + 1, nb - 1)
                                      : Math.max(i - 1, 0));
        return;
      }
      if (tab === 3) { econAdjust(key.rightArrow ? 1 : -1); return; }
      return;
    }
    if (key.tab) {
      const sugg = suggest(cmdEd.text);
      if (!key.shift && cmdEd.text.trim() !== '' && sugg.length) {
        setCmdEd(edNew(sugg[0].fill));
        return;
      }
      setTab(t => (t + (key.shift ? 6 : 1)) % 7);
      return;
    }
    if (key.escape) {
      if (cmdEd.text !== '') setCmdEd(edNew());
      else setHelp(false);
      return;
    }
    const r = edApply(cmdEd, input, key);
    if (r.submit === undefined && !r.cancel && r.ed === cmdEd) return;
    if (r.submit !== undefined) {
      const c = r.submit.trim().replace(/^\//, '');
      setCmdEd(edNew()); setNote(null);
      if (c) {
        hist.current.push(c); histIdx.current = -1;
        setHelp(false);
        void runCommand(c);
      }
      return;
    }
    if (!r.cancel) setCmdEd(r.ed);
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
        <Text color={C.dim}>/ commands  ? help  q quit</Text>
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
          tab === 0 ? <Connect s={sess} width={width} /> :
          tab === 1 ? <Audit s={sess} capIdx={capIdx} width={width} /> :
          tab === 2 ? <Route s={sess} width={width} /> :
          tab === 3 ? <Econ s={sess} params={params} sel={econSel}
                            width={width} /> :
          tab === 4 ? <Stream s={sess} shownRows={shownRows} paused={paused}
                              width={width} /> :
          tab === 5 ? <Case s={sess} reveal={reveal} width={width} /> :
          wiz       ? <Wizard w={wiz} width={width} /> :
                      <Ai s={sess} width={width} />
        )}
      </Box>
      <Rule width={width - 2} />
      {(() => {
        const sugg = cmdEd.text.trim() ? suggest(cmdEd.text) : [];
        return (
          <Box flexDirection="column">
            <Box borderStyle="round" borderColor={C.accent} paddingX={1}>
              <Text bold color={C.accent}>{'> '}</Text>
              <EditorText ed={cmdEd} />
              {cmdEd.text === '' ? (
                <Text color={C.dim}>{wiz
                  ? ' onboarding in progress above - esc aborts it'
                  : ' try: audit 50 · why <txn> · onboard <file> · help'}
                </Text>
              ) : null}
            </Box>
            {sugg.slice(0, 3).map(g => (
              <Text key={g.fill} color={C.dim}>
                {'    '}<Text bold>{g.fill}</Text>{'  '}{g.desc}
              </Text>
            ))}
            <Text color={C.dim}>
              {note ?? 'enter run · tab complete / panels · up-down history · click moves cursor · q + enter quits'}
            </Text>
          </Box>
        );
      })()}
    </Box>
  );
};

const Help = () => (
  <Box flexDirection="column" gap={1}>
    <Text bold>Just type in the box below and press enter.</Text>
    <Text color={C.dim}>{`  audit 50            the corrected evaluation at 50 reviews/day
  why <txn>           why one decision (AI, citations validated)
  timeline <case>     narrate one fraud case      compare <txn>  two systems
  evidence why <txn>  the raw evidence, no AI     provider       AI egress
  onboard <file>      map a new file (wizard)     source <file>  load it
  example synthetic   instant demo data           policy e=0.8   reprice
  capacity 50 . case <id> . route . stream . pause . next . 1-7 . quit

keys: enter run . tab complete (or switch panels when empty) . up/down
history . left/right budget row or cursor . click moves the cursor .
esc clear . ctrl+c quit`}</Text>
    <Text color={C.dim} wrap="wrap">Every figure is computed live by the local
 Python core over stdio. No HTTP, no ports, no telemetry.</Text>
  </Box>
);
