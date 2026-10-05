// /dsh 用：向 DSH Web 创建/复用会话并发送任务，收集 agent 回复。
//
// 用法:
//   node dsh_cli.js <baseUrl> <prompt> [--key <sessionKey>] [--cwd <dir>] [--fresh]
//                                   [--progress-interval <ms>]
//
// ── stdout 协议（JSONL：每行一个 JSON；调试信息一律走 stderr）──
//   {"type":"start",    sessionId, sessionKey, workspaceId}
//   {"type":"progress", elapsedMs, eventCount}     心跳，由上层决定是否提示用户
//   {"type":"result",   sessionId, sessionKey, workspaceId, reply, reason}
//   {"type":"error",    error}
//   兼容：result 行同样是 `{` 开头的单行 JSON，旧解析逻辑（从后往前找 JSON 行）依然可用。
//
// ── 进度心跳（阶段1 P0-3）──
//   任务久时每 --progress-interval 毫秒吐一行 progress（默认 15000，设 0 关闭）。
//   ⚠️ 它只用来告诉上层"还活着"。DSH 的中间文本**不要**直接发到群里
//      （主人要求：由南汐转述，不是复制 DSH 输出）。
//
// ── 会话复用 + 工作区归组（阶段1 P0-1 / P0-2，均已实测）──
//   · 传 --key 时：sessionKey --SHA-256--> 确定性 sessionId，再 create({ sessionId, workspaceId })。
//     同一 key 永远复用同一会话（DSH 保证同 id 同 cwd 幂等，实测确认）。
//   · workspaceId 由 workspace.list 按 cwd 匹配；未注册才 workspace.create（幂等）。
//     ⚠️ 只传 cwd 不会把会话归入任何工作区（Web 里显示"未分组"）—— 已实测确认，
//        所以复用模式一律传 workspaceId（它与 cwd 在 session.create 里互斥）。
//   · --fresh：key 追加时间戳 → 强制开新会话。
//   · 不传 --key 时保持旧行为（仅 create({cwd})，每次新建、不归组）—— 保留作回退路径。
import { NodeApiClient, unwrap, createTurnCollector } from './qq-bridge/src/dsh-client.js';
import { createHash } from 'node:crypto';

const DEFAULT_CWD = 'D:\\dsh\\QQbot\\nx_dsh';
const DEFAULT_PROGRESS_MS = 15000;
const PROMPT_TIMEOUT_MS = 300000;
/**
 * DSH 0.2.0：session/follow 的**开场历史快照**排空等待（毫秒）。
 * 快照会回放历史事件，其中的 turn/end 必须全部流过去、且在 prompt 前重建 collector，
 * 否则会把上一次的回复当成这次的结果返回。设为 0 可关闭（不建议）。
 */
const SNAPSHOT_DRAIN_MS = 1500;

/** 一行一个 JSON 写 stdout（JSONL）。 */
function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

/** sessionKey → 确定性 UUID（SHA-256 前 32 位十六进制按 UUID 形态重排）。 */
function deriveSessionId(sessionKey) {
  const h = createHash('sha256').update(sessionKey).digest('hex');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20, 32)}`;
}

function parseArgv(argv) {
  const positional = [];
  const flags = { fresh: false, key: undefined, cwd: undefined, progressInterval: undefined, listSessions: false, cancel: undefined };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--fresh') flags.fresh = true;
    else if (a === '--list-sessions') flags.listSessions = true;
    else if (a === '--fork') { flags.fork = argv[i + 1]; i += 1; }
    else if (a === '--session-id') { flags.sessionId = argv[i + 1]; i += 1; }
    else if (a === '--cancel') { flags.cancel = argv[i + 1]; i += 1; }
    else if (a === '--key') { flags.key = argv[i + 1]; i += 1; }
    else if (a === '--cwd') { flags.cwd = argv[i + 1]; i += 1; }
    else if (a === '--progress-interval') { flags.progressInterval = Number(argv[i + 1]); i += 1; }
    else positional.push(a);
  }
  return { positional, flags };
}

function normalizePath(p) {
  return String(p ?? '').replace(/[\\/]+$/, '').replace(/\//g, '\\').toLowerCase();
}

/** 按 cwd 取（必要时注册）工作区。返回 { workspaceId, title, sessionIds, created }。
 *
 * ⚠️ 2026-10-03 适配 DSH 0.2.0：`workspace.list` 端点**已被移除**（实测 404），
 * 而 `workspace.create` 是**幂等**的 —— 工作区已注册时直接返回现有那份（含 sessionIds），
 * 不会重复创建。所以这里不再"先 list 匹配、未命中才 create"，直接 create 即可。
 */
async function resolveWorkspace(api, cwd) {
  const made = unwrap(await api.workspace.create({ path: cwd }), 'workspace.create');
  const ws = made?.workspace ?? made;
  return {
    workspaceId: String(ws.workspaceId),
    title: ws.title,
    sessionIds: (ws.sessionIds ?? []).map(String),
    created: false, // 幂等语义下无法区分新建/命中，恒为 false（仅用于日志）
  };
}

async function main() {
  const { positional, flags } = parseArgv(process.argv.slice(2));
  const baseUrl = positional[0] ?? 'http://127.0.0.1:3080';
  const promptText = positional[1] ?? '';
  const cwd = flags.cwd ?? DEFAULT_CWD;
  const progressInterval = Number.isFinite(flags.progressInterval)
    ? flags.progressInterval
    : DEFAULT_PROGRESS_MS;

  let sessionKey = flags.key ? String(flags.key) : '';
  if (sessionKey && flags.fresh) sessionKey = `${sessionKey}:fresh:${Date.now()}`;

  const api = new NodeApiClient(baseUrl);

  // 0) --fork <sourceSessionId>：从源会话分支出新会话（带源的历史前缀 → 可命中 prompt cache）。
  //    语义见 dsh-host-apiproxy sessions.d.ts：取源会话最后一个**已完成回合**为切点，
  //    子会话继承源 cwd / 模型目标 / parentSessionId 血缘。用于 mas 答疑这类"要复用已有知识"的场景。
  if (flags.fork) {
    try {
      const r = unwrap(await api.sessions.fork({ sessionId: flags.fork }), 'session.fork');
      emit({ type: 'forked', source: flags.fork, sessionId: String(r.sessionId), ok: true });
    } catch (e) {
      emit({ type: 'forked', source: flags.fork, ok: false, error: String(e?.message ?? e) });
    }
    process.exit(0);
  }

  // 0.5) --cancel <sessionId>：中断该会话**正在进行**的回合（供 AstrBot 侧 `@南汐 stop` 急停用）。
  //    DSH 语义：停掉 active turn，pending inbox 的工作保留、取消结算后按 FIFO 继续。
  if (flags.cancel) {
    try {
      unwrap(await api.sessions.cancel({ sessionId: flags.cancel }), 'session.cancel');
      emit({ type: 'cancelled', sessionId: flags.cancel, ok: true });
    } catch (e) {
      emit({ type: 'cancelled', sessionId: flags.cancel, ok: false, error: String(e?.message ?? e) });
    }
    process.exit(0);
  }

  // 0.5) --list-sessions：只列本工作区的会话（供 AstrBot 侧 `/dsh 会话` 用）
  //    不创建会话、不执行任务；current 标出「发 /dsh 时会继续用」的那一个。
  if (flags.listSessions) {
    const w = await resolveWorkspace(api, cwd);
    const list = unwrap(await api.sessions.list({}), 'session.list');
    const byId = new Map((list.items ?? []).map((s) => [String(s.sessionId), s]));
    const currentId = sessionKey ? deriveSessionId(sessionKey) : null;
    const items = w.sessionIds.map((id, i) => {
      const s = byId.get(id);
      return {
        index: i + 1,
        sessionId: id,
        title: s?.title ?? null,
        updatedAt: s?.updatedAt ?? null,
        blank: s?.blank ?? null,
        isCurrent: currentId !== null && id === currentId,
      };
    });
    emit({
      type: 'sessions',
      workspaceId: w.workspaceId,
      workspaceTitle: w.title,
      current: currentId,
      count: items.length,
      items,
    });
    process.exit(0);
  }

  // 1) 会话从哪来：--session-id（指定，如 fork 出的分支会话）> --key（确定性复用）> 旧行为（每次新建）
  let workspaceId = null;
  let created;
  if (flags.sessionId) {
    // 直接用指定会话 —— fork 出来的分支会话带着源的历史前缀，可命中 prompt cache；
    // 这里不 create 也不 fork，只解析出工作区用于归组/日志。
    const w = await resolveWorkspace(api, cwd);
    workspaceId = w.workspaceId;
    created = { sessionId: String(flags.sessionId) };
  } else if (sessionKey) {
    const ws = await resolveWorkspace(api, cwd);
    workspaceId = ws.workspaceId;
    created = unwrap(
      await api.sessions.create({ sessionId: deriveSessionId(sessionKey), workspaceId }),
      'session.create',
    );
  } else {
    // 回退路径：旧行为，仅 cwd（每次新建、不归组）
    created = unwrap(await api.sessions.create({ cwd }), 'session.create');
  }
  const sessionId = created.sessionId;

  // 给会话起个认得出的标题（本次指令的前 24 字），否则 `/dsh 会话` 列表全是「无标题」
  if (sessionKey && promptText.trim()) {
    const title = promptText.replace(/\s+/g, ' ').trim().slice(0, 24);
    try {
      unwrap(await api.sessions.rename({ sessionId, title }), 'session.rename');
    } catch {
      /* 改名失败不影响任务本身 */
    }
  }

  emit({ type: 'start', sessionId, sessionKey: sessionKey || null, workspaceId });

  // 2) 进度心跳（定时吐，与事件流解耦，保证任务卡住时上层也能收到"还活着"）
  const startedAt = Date.now();
  let eventCount = 0;
  let progressTimer = null;
  if (progressInterval > 0) {
    progressTimer = setInterval(() => {
      emit({ type: 'progress', elapsedMs: Date.now() - startedAt, eventCount });
    }, progressInterval);
    progressTimer.unref?.();
  }
  const stopProgress = () => {
    if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
  };

  // 3) 订阅事件流（必须在 prompt 前，避免漏事件）
  //    ⚠️ DSH 0.2.0 起事件走 /api/remote.mux，且**必须先用 events.follow(sessionId) 订阅本会话**
  //    （新版 events.mux 会把 session/follow 的帧映射回旧的 session/event 信封，所以下面的消费逻辑不变）。
  let collector = createTurnCollector();
  let resolveOpened;
  const opened = new Promise((r) => { resolveOpened = r; });
  const done = new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error(`等待回复超时(${PROMPT_TIMEOUT_MS / 1000}s)`)),
      PROMPT_TIMEOUT_MS,
    );
    (async () => {
      for await (const envelope of api.events.mux({}, undefined, () => resolveOpened())) {
        const frame = envelope.payload;
        if (frame.type === 'stream/error') {
          clearTimeout(timer); reject(new Error('事件流错误: ' + JSON.stringify(frame.error))); return;
        }
        if (frame.type === 'session/event' && frame.sessionId === sessionId) {
          eventCount += 1;
          const ended = collector.push(frame.event);
          if (ended) { clearTimeout(timer); resolve(ended); return; }
        }
      }
    })().catch((e) => { clearTimeout(timer); reject(e); });
  });
  await opened;

  // 3.5) 订阅本会话，并让 follow 的**开场历史快照**排空。
  //      ⚠️ 这是 0.2.0 最容易踩的坑：session/follow 打开时会先回放历史事件，
  //      其中历史轮次的 turn/end 一旦被 collector 认下，就会把**上一次的回复**当成这次的结果返回。
  //      对策：先 follow → 等快照流过去 → **重建 collector** 丢掉历史轮次 → 再 prompt。
  api.events.follow(sessionId);
  if (SNAPSHOT_DRAIN_MS > 0) {
    await new Promise((r) => setTimeout(r, SNAPSHOT_DRAIN_MS));
  }
  collector = createTurnCollector();

  // 4) 发送任务（DSH 只负责执行，人格转述由 AstrBot 南汐负责）
  unwrap(await api.sessions.prompt({ sessionId, mode: 'queue', content: [{ type: 'text', text: promptText }] }), 'session.prompt');

  // 5) 等回复
  const ended = await done;
  stopProgress();
  emit({
    type: 'result',
    sessionId,
    sessionKey: sessionKey || null,
    workspaceId,
    elapsedMs: Date.now() - startedAt,
    reply: ended.text || '',
    reason: ended.reason?.kind,
  });
  process.exit(0);
}

main().catch((e) => {
  process.stdout.write(JSON.stringify({ type: 'error', error: String(e?.message || e) }) + '\n');
  process.exit(1);
});
