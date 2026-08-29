// JSON-RPC client for the Python core: newline-delimited JSON over the
// child process's stdio. No HTTP, no ports, fully offline. The Python CLI
// stays independently usable; this process is a surface on top of it.
import {spawn, ChildProcess} from 'node:child_process';
import {createInterface} from 'node:readline';
import path from 'node:path';

type Pending = {resolve: (v: any) => void; reject: (e: Error) => void};

export class Rpc {
  private child: ChildProcess;
  private pending = new Map<number, Pending>();
  private nextId = 1;
  public dead: string | null = null;

  constructor() {
    const py = process.env.STRIKEONE_PY ?? 'python3';
    const root =
      process.env.STRIKEONE_ROOT ?? path.resolve(process.cwd(), '..');
    this.child = spawn(py, ['-m', 'strikeone.rpc'], {
      cwd: root,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: {...process.env, PYTHONUNBUFFERED: '1'},
    });
    const rl = createInterface({input: this.child.stdout!});
    rl.on('line', line => {
      let msg: any;
      try {
        msg = JSON.parse(line);
      } catch {
        return;
      }
      const p = this.pending.get(msg.id);
      if (!p) return;
      this.pending.delete(msg.id);
      if (msg.error) p.reject(new Error(msg.error));
      else p.resolve(msg.result);
    });
    this.child.on('exit', code => {
      this.dead = `python backend exited (${code})`;
      for (const p of this.pending.values())
        p.reject(new Error(this.dead));
      this.pending.clear();
    });
    this.child.stderr!.on('data', () => {});
  }

  call<T = any>(method: string, params: object = {}): Promise<T> {
    if (this.dead) return Promise.reject(new Error(this.dead));
    const id = this.nextId++;
    const line = JSON.stringify({id, method, params}) + '\n';
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, {resolve, reject});
      this.child.stdin!.write(line);
    });
  }

  kill() {
    this.child.kill();
  }
}
