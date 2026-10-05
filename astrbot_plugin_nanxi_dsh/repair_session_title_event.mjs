// 会话日志「标题事件」的完整性检查与修复。
//
// ## 坏模式（DSH 的 session/rename 留下的）
//     seq=4011  session/end-seed
//     seq=4011  session/title      ← seq 与上一条撞车
// 后果：整间会话打不开，DSH 报
//     corrupt Zstandard session log: complete frame contains a torn JSONL record
// 正常模式是 seq 严格递增、并以 session/end-seed 收尾：
//     … turn/end(4010) → session/end-seed(4011) → session/title(4012) → session/end-seed(4013)
//
// ## 判据（只看**全局最后两条事件**，跨帧也算）
//     最后一条的 seq 必须 **比倒数第二条更大**（DSH 正常写入永远严格递增：
//     … turn/end(15997) → end-seed(15998) → title(15999) → end-seed(16000)）。
// 实测 `session/rename` 会写出两种坏法，**都要修**：
//     a) 与上一条**相同**：end-seed(32) → title(32)        （撞车）
//     b) 比上一条**更小**：end-seed(34) → title(33)        （倒退，2026-10-04 第二次实测）
// 只缺 end-seed（seq 递增正常）**不算坏**：DSH 加载时会自己补
// （dsh-session/lib/index.js:1352）。所以这种情况一律报 ok，不动文件。
//
// ## 修复做法
// 定位最后一条事件所在的帧，把该帧**重写**成：
//     该帧中它之前的行（原样保留）+ title(prev.seq+1) + end-seed(prev.seq+2)
// —— 以**倒数第二条**为基准重编号，保证末尾重新严格递增、并以 end-seed 收尾。
// 压缩参数与 DSH 写出来的一致（Frame_Header_Descriptor = 0x04，即带 content checksum）。
// 写盘前自动备份成 `*.bak-<时间戳>`。
//
// ⚠️ **DSH 进程内的投影缓存不会因为外部改文件而刷新**（它只认自己写过的事件）。
// 所以修完之后，同一间会话再次改名时基准可能仍是旧的 —— 这不是"修失败了"，
// 而是"外部改文件、DSH 不知道"。安全网每改一次就跑，保证日志**始终合法可读**；
// 想让它彻底对齐，重启对应 DSH 实例即可。
//
// **幂等**：不撞车就什么都不做（status=ok）—— 所以可以当"改完名字无脑跑一遍"的安全网。
//
// ## 用法
//     node tools\repair_session_title_event.mjs <sessionId | 日志文件路径> [--apply] [--home <DSH_HOME>]
//     不带 --apply 只检查并打印判断，不写盘。
//
// ## 给程序看的输出（最后一行）
//     [RESULT] {"status":"ok|repaired|broken|skip|error","sessionId":…,"file":…,"detail":…}
//     ok=检查过无需处理 / repaired=已修好 / broken=检出问题但没写盘（dry-run）/ skip=要人工看 / error=读写失败
// 退出码：ok/repaired → 0；skip/error → 1。

import fs from 'node:fs'
import path from 'node:path'
import zlib from 'node:zlib'

const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])
const CHECKSUM_FLAG = zlib.constants.ZSTD_c_checksumFlag
const DEFAULT_HOME = 'D:\\dsh\\nanxi-dsh'

function emit(status, extra = {}) {
  console.log('[RESULT] ' + JSON.stringify({ status, ...extra }))
  // 只有"确实没事（ok）"和"已经修好了（repaired）"算成功；
  // broken=检出问题但没写盘（dry-run）、skip=要人工看、error=读写失败，一律非零退出。
  return status === 'ok' || status === 'repaired' ? 0 : 1
}

function framesOf(buf) {
  const off = []
  let i = 0
  while ((i = buf.indexOf(MAGIC, i)) !== -1) { off.push(i); i += 4 }
  const out = []
  for (let k = 0; k < off.length; k++) {
    const end = k + 1 < off.length ? off[k + 1] : buf.length
    out.push(buf.subarray(off[k], end))
  }
  return out
}

const decompress = (frame) => zlib.zstdDecompressSync(frame).toString('utf8')
const compress = (text) =>
  zlib.zstdCompressSync(Buffer.from(text, 'utf8'), { params: { [CHECKSUM_FLAG]: 1 } })
const parseEvents = (text) => text.split('\n').filter((l) => l.trim() !== '')

/** 按 sessionId 在 DSH_HOME 的 sessions 下（「分组目录/<会话 id>/」）找会话日志。 */
function locate(sessionId, home) {
  const root = path.join(home, 'sessions')
  if (!fs.existsSync(root)) return null
  for (const name of ['session.v4.jsonl.zstd', 'session.jsonl.zstd']) {
    for (const group of fs.readdirSync(root)) {
      const f = path.join(root, group, sessionId, name)
      if (fs.existsSync(f)) return f
    }
  }
  return null
}

// ------------------------------------------------------------------ 参数 ---

const argv = process.argv.slice(2)
const apply = argv.includes('--apply')
const homeIdx = argv.indexOf('--home')
const home = homeIdx >= 0 ? argv[homeIdx + 1] : DEFAULT_HOME
const positional = argv.filter((a, i) => {
  if (a.startsWith('--')) return false
  // --home 后面那一项是它的值；没有 --home 时（homeIdx = -1）不能误杀 argv[0]。
  if (homeIdx >= 0 && i === homeIdx + 1) return false
  return true
})
const target = positional[0]

if (!target) {
  console.error('用法: node repair_session_title_event.mjs <sessionId|日志路径> [--apply] [--home <DSH_HOME>]')
  process.exit(2)
}

let file = target
let sessionId = ''
if (target.endsWith('.zstd')) {
  sessionId = path.basename(path.dirname(target))
} else {
  sessionId = target
  file = locate(sessionId, home)
  if (!file) process.exit(emit('error', { sessionId, detail: `在 ${home}\\sessions 下找不到这间会话的日志` }))
}
if (!fs.existsSync(file)) process.exit(emit('error', { sessionId, file, detail: '日志文件不存在' }))

const buf = fs.readFileSync(file)
const frames = framesOf(buf)
if (frames.length < 1) process.exit(emit('skip', { sessionId, file, detail: '一帧都没有' }))

const lastFrame = frames[frames.length - 1]
let lastText
try { lastText = decompress(lastFrame) } catch (e) {
  process.exit(emit('error', { sessionId, file, detail: '末帧解压失败: ' + e.message }))
}
const lastFrameEvents = parseEvents(lastText)

// 全局倒数第二条：优先在本帧里找，本帧只有一条就去上一帧拿。
let prevRaw = null
if (lastFrameEvents.length >= 2) {
  prevRaw = lastFrameEvents[lastFrameEvents.length - 2]
} else if (frames.length >= 2) {
  try { prevRaw = parseEvents(decompress(frames[frames.length - 2])).slice(-1)[0] ?? null } catch { prevRaw = null }
}

const parseOrNull = (s) => { try { return JSON.parse(s) } catch { return null } }
const lastEv = parseOrNull(lastFrameEvents[lastFrameEvents.length - 1])
const prevEv = prevRaw === null ? null : parseOrNull(prevRaw)

if (lastEv === null) process.exit(emit('skip', { sessionId, file, detail: '末条事件不是合法 JSON' }))

// 判据：末尾 seq 必须比前一条**更大**（DSH 正常写入永远严格递增）。
// rename 会写出「相同」或「更小」两种坏法，都归到这里。
const broken = prevEv !== null && lastEv.seq <= prevEv.seq
if (!broken) {
  process.exit(emit('ok', {
    sessionId, file,
    detail: `末尾正常（${prevEv ? `${prevEv.type}(${prevEv.seq}) → ` : ''}${lastEv.type}(${lastEv.seq})），无需处理`,
  }))
}

if (lastEv.type !== 'session/title') {
  process.exit(emit('skip', {
    sessionId, file,
    detail: `末条 seq 异常（${prevEv.type}(${prevEv.seq}) 之后是 ${lastEv.type}(${lastEv.seq})），但末条不是 session/title，交人工确认`,
  }))
}

// 以**倒数第二条**为基准重编号：title = prev+1、end-seed = prev+2，
// 让末尾重新变成「严格递增 + 以 end-seed 收尾」。
const newTitle = { ...lastEv, seq: prevEv.seq + 1 }
const endSeed = { type: 'session/end-seed', seq: prevEv.seq + 2, time: lastEv.time, data: {} }
const head = lastFrameEvents.slice(0, -1).join('\n')
const newFrame = compress((head === '' ? '' : head + '\n') + JSON.stringify(newTitle) + '\n' + JSON.stringify(endSeed) + '\n')

if (!apply) {
  process.exit(emit('broken', {
    sessionId, file,
    detail: `末条 seq 异常（${prevEv.type}(${prevEv.seq}) → ${lastEv.type}(${lastEv.seq})）；加 --apply 即修成 title(${prevEv.seq + 1}) + end-seed(${prevEv.seq + 2})`,
  }))
}

const stamp = new Date().toISOString().replace(/[:.]/g, '-')
const backup = `${file}.bak-${stamp}`
fs.copyFileSync(file, backup)
fs.writeFileSync(file, Buffer.concat([Buffer.concat(frames.slice(0, frames.length - 1)), newFrame]))

try {
  const check = framesOf(fs.readFileSync(file))
  decompress(check[check.length - 1])
} catch (e) {
  process.exit(emit('error', { sessionId, file, backup, detail: '写回后自检失败: ' + e.message }))
}

process.exit(emit('repaired', {
  sessionId, file, backup,
  detail: `末条 seq 已重编号：title(${prevEv.seq + 1}) + end-seed(${prevEv.seq + 2})`,
}))
