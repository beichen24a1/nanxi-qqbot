// 离线单测：验证打过 nanxi-patch 的 applySessionTitle 行为。
// 只 import 星驿的 session-title.js（它只依赖纯函数 location.js），不需要 dsh 运行时。
import { applySessionTitle, TITLE_MAX_BYTES } from
  'file:///D:/dsh/nanxi-dsh/profiles/nanxi/node_modules/dsh-astrbot-relay/lib/session-title.js'

const TEMPLATE = '星驿 · {platform}/{messageType}/{sessionId}'
const UMO = 'onebot-qq:GroupMessage:100001'
const RENDERED = '星驿 · onebot-qq/GroupMessage/100001'
const SESSION = { id: 'session-test' }

function fakeTitles(current, opts = {}) {
  const calls = []
  return {
    calls,
    get() {
      if (opts.getThrows) throw new Error('get boom')
      if (current === null || current === undefined) return null
      return { title: current, source: { kind: 'user' }, eventSeq: 1 }
    },
    rename(session, title) {
      calls.push(title)
      if (opts.renameThrows) throw new Error('session is not live in this store')
      return { title, eventSeq: 2 }
    },
  }
}

let pass = 0
let fail = 0
function check(name, cond, extra = '') {
  if (cond) { pass++; console.log(`  ok   ${name}`) }
  else { fail++; console.log(`  FAIL ${name} ${extra}`) }
}

function run({ current, suffix, opts = {}, session = SESSION, titles, noService = false } = {}) {
  const t = noService
    ? undefined
    : (titles === undefined ? fakeTitles(current, opts) : titles)
  const res = applySessionTitle({
    titles: t, session, template: TEMPLATE, conversation: UMO, suffix,
  })
  return { res, written: t === undefined ? [] : t.calls }
}

console.log('--- 渲染基线 ---')
{
  const { res } = run({ current: '', suffix: '_南汐' })
  check('模板渲染值符合预期', res.ok && res.title === RENDERED, JSON.stringify(res))
}

console.log('--- 星驿自己的会话（没名字 / 已经是模板名）---')
{
  const a = run({ current: null, suffix: '_南汐' })
  check('空标题 → 写模板', a.written.length === 1 && a.written[0] === RENDERED, JSON.stringify(a.written))
}
{
  const b = run({ current: RENDERED, suffix: '_南汐' })
  check('已是模板名 → 重写模板（幂等）', b.written.length === 1 && b.written[0] === RENDERED, JSON.stringify(b.written))
}

console.log('--- 用户自己起的名字（本次定制的核心）---')
{
  const c = run({ current: 'skill', suffix: '_南汐' })
  check('skill → skill_南汐', c.written.length === 1 && c.written[0] === 'skill_南汐', JSON.stringify(c.written))
  check('ok=true 且 rendered 是交出去原文', c.res.ok && c.res.rendered === 'skill_南汐')
}
{
  const d = run({ current: 'skill_南汐', suffix: '_南汐' })
  check('已缀过 → 不写（幂等）', d.written.length === 0, JSON.stringify(d.written))
}
{
  const e = run({ current: 'debug-skill', suffix: '_南汐' })
  check('debug-skill → debug-skill_南汐', e.written[0] === 'debug-skill_南汐', JSON.stringify(e.written))
}
{
  const f = run({ current: '配置移动功能', suffix: '_南汐' })
  check('中文名也能缀', f.written[0] === '配置移动功能_南汐', JSON.stringify(f.written))
}

console.log('--- suffix 配成空串 = 完全不碰用户会话 ---')
{
  const g = run({ current: 'skill', suffix: '' })
  check('不写', g.written.length === 0, JSON.stringify(g.written))
  check('仍返回 ok', g.res.ok === true)
}
{
  const h = run({ current: null, suffix: '' })
  check('没名字的仍写模板', h.written[0] === RENDERED, JSON.stringify(h.written))
}

console.log('--- 降级路径 ---')
{
  const i = run({ current: 'skill', suffix: '_南汐', session: null })
  check('session 为 null → NO_SESSION 且不写', !i.res.ok && i.res.reason === 'no-session', JSON.stringify(i.res))
}
{
  const j = run({ current: 'skill', suffix: '_南汐', noService: true })
  check('服务缺席 → service-missing', !j.res.ok && j.res.reason === 'service-missing', JSON.stringify(j.res))
}
{
  const k = run({ current: 'skill', suffix: '_南汐', opts: { renameThrows: true } })
  check('rename 抛错 → rename-failed 且不抛', !k.res.ok && k.res.reason === 'rename-failed', JSON.stringify(k.res))
}
{
  const l = run({ current: 'skill', suffix: '_南汐', opts: { getThrows: true } })
  check('get 抛错 → 当空串，仍按模板写', l.written[0] === RENDERED, JSON.stringify(l.written))
}

console.log('--- 字节上限（80）---')
{
  const long = '你'.repeat(40) // 120 字节
  const m = run({ current: long, suffix: '_南汐' })
  const out = m.written[0] || ''
  const bytes = Buffer.byteLength(out, 'utf8')
  check('总长不超过 80 字节', bytes <= TITLE_MAX_BYTES, `bytes=${bytes}`)
  check('后缀被保住', out.endsWith('_南汐'), out)
  check('没有劈坏多字节字符', !out.includes('\uFFFD'), out)
}

console.log()
console.log(`结果：${pass} 通过 / ${fail} 失败`)
process.exit(fail === 0 ? 0 : 1)
