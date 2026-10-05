// 读星驿接管过的会话的**标题历史**（session/title 事件序列），用来找回被覆盖前的原名。
//
// 为什么不能直接 zlib.zstdDecompressSync：session.*.jsonl.zstd 是**多帧 zstd**
// （DSH 边写边追加，一帧一段）—— zstdDecompressSync 只解第一帧（症状：3.6 MB 的文件
// 只解出 258 字符），流式 createZstdDecompress 直接 "The operation was aborted"。
// 可行解就是这里做的：按帧魔数 0x28B52FFD 切分后逐帧解压再拼接。
//
// 用法：
//   node tools\relay-title-history.mjs                      # 默认扫 mas 分组的所有会话
//   node tools\relay-title-history.mjs <sessionId> [更多…]   # 只看指定的几间
//   $env:SCAN_ROOT='D:\dsh\nanxi-dsh\sessions\--D-dsh-QQbot-nx_dsh--'; node tools\relay-title-history.mjs
//
// 输出的「最初 / 现在 / 全部」就是标题变迁史：source 为 user 的是星驿或用户手工改的，
// fallback/provider 的是 DSH 自动生成的。**倒着数第二条 = 被星驿覆盖前的名字。**
import fs from 'node:fs'
import path from 'node:path'
import zlib from 'node:zlib'

const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]) // zstd 帧魔数（小端 0xFD2FB528）

function decodeMultiFrame(buf) {
  const offsets = []
  let i = 0
  while ((i = buf.indexOf(MAGIC, i)) !== -1) { offsets.push(i); i += 4 }
  const parts = []
  let ok = 0
  let bad = 0
  for (let k = 0; k < offsets.length; k++) {
    const end = k + 1 < offsets.length ? offsets[k + 1] : buf.length
    const frame = buf.subarray(offsets[k], end)
    try { parts.push(zlib.zstdDecompressSync(frame)); ok++ } catch { bad++ }
  }
  return { text: Buffer.concat(parts).toString('utf8'), frames: offsets.length, ok, bad }
}

function pickTitle(ev) {
  const d = ev?.data ?? ev?.payload ?? ev
  const t = d?.title
  return typeof t === 'string' ? { title: t, source: d?.source?.kind ?? '?' } : null
}

const ROOT = process.env.SCAN_ROOT ?? 'D:\\dsh\\nanxi-dsh\\sessions\\--D-dsh-mas--'
const only = process.argv.slice(2)

function scanOne(sessionId) {
  const dir = path.join(ROOT, sessionId)
  if (!fs.existsSync(dir)) return null
  for (const name of ['session.v4.jsonl.zstd', 'session.jsonl.zstd', 'session.v3.jsonl.zstd']) {
    const f = path.join(dir, name)
    if (!fs.existsSync(f)) continue
    const buf = fs.readFileSync(f)
    const r = decodeMultiFrame(buf)
    if (r.text.length < 200) continue
    const titles = []
    for (const line of r.text.split('\n')) {
      if (!line.includes('"title"')) continue
      let ev
      try { ev = JSON.parse(line) } catch { continue }
      const t = pickTitle(ev)
      if (t) titles.push(t)
    }
    return { file: name, ...r, titles }
  }
  return null
}

const targets = only.length > 0
  ? only
  : fs.readdirSync(ROOT, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name)

for (const sid of targets) {
  const r = scanOne(sid)
  if (r === null) { console.log(`  ?? ${sid}: 没有可读日志`); continue }
  const uniq = [...new Set(r.titles.map((t) => t.title))]
  const tag = uniq.length > 1 ? '  <<< 改过名' : ''
  console.log(`  ${sid}`)
  console.log(`      ${r.file}  ${r.frames} 帧(ok=${r.ok} bad=${r.bad})  ${r.text.length} 字符  title 事件 ${r.titles.length} 条${tag}`)
  if (r.titles.length > 0) {
    console.log(`      最初: ${JSON.stringify(r.titles[0].title)} [${r.titles[0].source}]`)
    console.log(`      现在: ${JSON.stringify(r.titles[r.titles.length - 1].title)} [${r.titles[r.titles.length - 1].source}]`)
    if (uniq.length > 1) console.log(`      全部: ${JSON.stringify(uniq)}`)
  }
}
