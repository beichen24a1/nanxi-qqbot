/**
 * dsh-nanxi-browser —— 南汐自己的浏览器，做成**正规 DSH 插件**。
 *
 * ## 为什么要有它
 *
 * AstrBot 那套 `astrbot_plugin_nanxi_dsh/browser.py` 是**聊天侧**的手：只服务于 QQ 那条线，
 * 而且要绕 AstrBot 进程。这个插件让 **DSH 侧的 agent 自己**就能开浏览器 ——
 * 不经过 AstrBot，也不依赖那 4 个改 node_modules 的补丁（那些升级就丢）。
 *
 * ## 技术选型（实测过才这么写）
 *
 * Chrome 自带 DevTools Protocol：HTTP `/json/list` 拿调试目标 + WebSocket 发命令。
 * **Node 24 内置 `fetch` 与 `WebSocket`，所以这个插件零依赖**。
 * 不用 playwright（要下几百 MB 浏览器），也不用 `ws` 包。
 *
 * ⚠️ 调试端口用 **9334**，与 AstrBot 那套（9333）**刻意错开** —— 两边各自管一个
 * headless Chrome，互不干扰；共用一个实例会互相抢页面。
 *
 * ⚠️ `Page.startScreencast` 推来的帧是 **CDP 事件**（不是响应），而且**每帧都要回
 * `Page.screencastFrameAck`**，不回 ack 浏览器就不再推下一帧 —— 这是最容易漏的一步。
 */
import { defineTool } from '@deepseek-ai/dsh-tools'
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'

export const name = 'dsh-nanxi-browser'
export const inject = ['tools']

const PORT = 9334
const PROFILE = join(homedir(), '.dsh', 'nanxi-browser-profile')

/** 依次找本机可用的 Chromium 内核浏览器。 */
const CHROME_CANDIDATES = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  join(process.env.LOCALAPPDATA || '', 'Google', 'Chrome', 'Application', 'chrome.exe'),
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
]

function findBrowser() {
  for (const p of CHROME_CANDIDATES) if (p && existsSync(p)) return p
  return null
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/**
 * 一个常驻的 headless 浏览器 + 一条 CDP 连接（懒启动，全局单例）。
 *
 * 与 Python 版同构：一次只服务一个页面，所以调用方串行使用即可。
 */
class Browser {
  constructor() {
    this.proc = null
    this.ws = null
    this.seq = 0
    this.pending = new Map()
    this.frame = null // 最新一帧（JPEG Buffer）
    this.frameSeq = 0
    this.casting = false // 是否已经在推帧
    this.cursor = null // 最近一次操作的归一化落点
    this.url = ''
    this.title = ''
  }

  get running() {
    return this.proc !== null && this.proc.exitCode === null
  }

  /** 确保浏览器与 CDP 连接可用（懒启动）。 */
  async ensure() {
    if (this.running && this.ws && this.ws.readyState === 1) return
    await this.close()
    const exe = findBrowser()
    if (!exe) throw new Error('本机没找到 Chrome 或 Edge')
    mkdirSync(PROFILE, { recursive: true })
    this.proc = spawn(
      exe,
      [
        '--headless=new',
        `--remote-debugging-port=${PORT}`,
        `--user-data-dir=${PROFILE}`,
        '--window-size=1280,900',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-gpu',
        'about:blank',
      ],
      { stdio: 'ignore', detached: false },
    )
    let wsUrl = null
    for (let i = 0; i < 60; i++) {
      if (this.proc.exitCode !== null) {
        throw new Error(`浏览器起来就退了（exit=${this.proc.exitCode}）`)
      }
      try {
        const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()
        const page = list.find((t) => t.type === 'page')
        if (page?.webSocketDebuggerUrl) {
          wsUrl = page.webSocketDebuggerUrl
          break
        }
      } catch {
        /* CDP 还没起来 */
      }
      await sleep(500)
    }
    if (!wsUrl) throw new Error('等不到 CDP 调试目标（30 秒超时）')
    await this.connect(wsUrl)
  }

  connect(wsUrl) {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(wsUrl)
      ws.addEventListener('open', () => {
        this.ws = ws
        resolve()
      })
      ws.addEventListener('error', (e) => reject(new Error(`CDP 连接失败：${e.message || e}`)))
      ws.addEventListener('message', (ev) => this.onMessage(ev.data))
      ws.addEventListener('close', () => {
        this.ws = null
      })
    })
  }

  /** CDP 的消息分流：响应按 id 派回；**事件里只捞 screencast 的帧**。 */
  onMessage(raw) {
    let data
    try {
      data = JSON.parse(typeof raw === 'string' ? raw : raw.toString())
    } catch {
      return
    }
    if (data.method === 'Page.screencastFrame') {
      const p = data.params || {}
      if (p.data) {
        this.frame = Buffer.from(p.data, 'base64')
        this.frameSeq += 1
      }
      // ⚠️ 必须 ack，否则浏览器不再推下一帧。
      if (p.sessionId !== undefined) {
        this.send({ method: 'Page.screencastFrameAck', params: { sessionId: p.sessionId } })
      }
      return
    }
    const fut = this.pending.get(data.id)
    if (fut) {
      this.pending.delete(data.id)
      fut(data)
    }
  }

  /** 只发不等（给 ack 用）。 */
  send(msg) {
    if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(msg))
  }

  /** 发一条 CDP 命令并等响应。 */
  call(method, params = {}, timeoutMs = 30000) {
    if (!this.ws || this.ws.readyState !== 1) throw new Error('浏览器连接不在')
    const id = ++this.seq
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`CDP ${method} 超时`))
      }, timeoutMs)
      this.pending.set(id, (res) => {
        clearTimeout(timer)
        resolve(res)
      })
      this.send({ id, method, params })
    })
  }

  /** 在页面里跑一段 JS 并取回值。 */
  async js(expression, timeoutMs = 30000) {
    const res = await this.call(
      'Runtime.evaluate',
      { expression, returnByValue: true, awaitPromise: true },
      timeoutMs,
    )
    if (res.error) throw new Error(res.error.message || 'JS 出错')
    return res.result?.result?.value
  }

  /** 开一个页面，等首屏，返回标题与正文。 */
  async goto(url) {
    if (!/^[a-z]+:\/\//i.test(url)) url = 'https://' + url
    await this.ensure()
    const res = await this.call('Page.navigate', { url }, 45000)
    if (res.error) throw new Error(`导航失败：${res.error.message}`)
    await sleep(1500)
    this.url = url
    this.title = String((await this.js('document.title')) || '')
    const text = String((await this.js('document.body ? document.body.innerText : ""')) || '')
    return { url, title: this.title, text }
  }

  /** 点一个元素：先当 CSS 选择器，找不到再按可见文字。 */
  async click(target) {
    await this.ensure()
    const t = JSON.stringify(target)
    const got = await this.js(`(() => {
      const t = ${t}; let el = null;
      try { el = document.querySelector(t) } catch (e) {}
      if (!el) {
        for (const n of document.querySelectorAll('a,button,input,[role=button],[onclick],summary')) {
          const s = ((n.innerText || n.value || n.getAttribute('aria-label') || '') + '').trim();
          if (s && s.includes(t)) { el = n; break }
        }
      }
      if (!el) return 'not-found';
      el.scrollIntoView({ block: 'center' }); el.click();
      const r = el.getBoundingClientRect();
      return JSON.stringify({
        tag: el.tagName,
        text: ((el.innerText || el.value || '') + '').trim().slice(0, 40),
        x: (r.left + r.width / 2) / Math.max(1, window.innerWidth),
        y: (r.top + r.height / 2) / Math.max(1, window.innerHeight),
      });
    })()`)
    await sleep(1200)
    if (got === 'not-found') return { ok: false, note: `页面上没找到「${target}」` }
    try {
      const info = JSON.parse(got)
      this.cursor = { x: info.x, y: info.y }
      return { ok: true, note: `点了 ${info.tag}:${info.text}` }
    } catch {
      return { ok: true, note: `点了 ${got}` }
    }
  }

  /** 往输入框填字。 */
  async type(target, value) {
    await this.ensure()
    const t = JSON.stringify(target)
    const v = JSON.stringify(value)
    const got = await this.js(`(() => {
      const t = ${t}, v = ${v}; let el = null;
      try { el = document.querySelector(t) } catch (e) {}
      if (!el) {
        for (const n of document.querySelectorAll('input,textarea,[contenteditable=true]')) {
          const s = ((n.placeholder || n.name || n.id || n.getAttribute('aria-label') || '') + '');
          if (s && s.includes(t)) { el = n; break }
        }
      }
      if (!el) return 'not-found';
      el.scrollIntoView({ block: 'center' }); el.focus();
      if ('value' in el) el.value = v; else el.textContent = v;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      const r = el.getBoundingClientRect();
      return JSON.stringify({
        tag: el.tagName,
        x: (r.left + r.width / 2) / Math.max(1, window.innerWidth),
        y: (r.top + r.height / 2) / Math.max(1, window.innerHeight),
      });
    })()`)
    if (got === 'not-found') return { ok: false, note: `页面上没找到输入框「${target}」` }
    try {
      const info = JSON.parse(got)
      this.cursor = { x: info.x, y: info.y }
    } catch {
      /* 坐标拿不到就算了，不影响填写 */
    }
    return { ok: true, note: `已往 ${target} 填了 ${value.length} 个字` }
  }

  /** 截图存盘（PNG）。 */
  async screenshot(path) {
    await this.ensure()
    const res = await this.call('Page.captureScreenshot', { format: 'png' }, 45000)
    const b64 = res.result?.data
    if (!b64) throw new Error('截图失败：没拿到数据')
    const buf = Buffer.from(b64, 'base64')
    writeFileSync(path, buf)
    return buf.length
  }

  /** 开始推帧（`Page.startScreencast`）。 */
  async watchOn(quality = 70) {
    await this.ensure()
    await this.call('Page.startScreencast', {
      format: 'jpeg',
      quality,
      maxWidth: 1280,
      maxHeight: 900,
      everyNthFrame: 1,
    })
    this.casting = true
  }

  async close() {
    if (this.ws) {
      try {
        this.ws.close()
      } catch {
        /* 已经断了 */
      }
      this.ws = null
    }
    this.pending.clear()
    if (this.proc) {
      try {
        this.proc.kill()
      } catch {
        /* 可能已经退了 */
      }
      this.proc = null
    }
    this.frame = null
  }
}

/** 全局单例：一个插件进程管一个浏览器。 */
const browser = new Browser()

const text = (s) => [{ type: 'text', text: s }]

/** 面板订阅的 SSE 端点（client.js 会连它）。 */
const STREAM_ROUTE = '/api/nanxi-browser/stream'
/** 面板读状态的小接口。 */
const STATE_ROUTE = '/api/nanxi-browser/state'

/**
 * 安全地注册一个副作用：`ctx.effect` 是 cordis 的 API，老版本宿主可能没有。
 *
 * 为什么不直接调：**`apply` 里抛一个错，整个插件就变成 "failed to import"**
 * （DSH 只记一行 `entry.fiber === undefined`，真错被吞掉）—— 面板/帧流都是"锦上添花"，
 * 绝不能因为它们把工具本身一起带死。
 *
 * @param {any} ctx 插件上下文
 * @param {Function} fn 副作用函数（返回值当 dispose）
 * @param {string} label 给宿主看的人话标签
 * @param {{warn?: Function}} log 日志
 */
function safeEffect(ctx, fn, label, log) {
  try {
    if (typeof ctx.effect === 'function') {
      ctx.effect(fn, label)
      return
    }
    fn() // 没有 effect 就直接跑一次（放弃了卸载时的清理，但功能在）
  } catch (e) {
    log.warn?.(`[nanxi-browser] 注册「${label}」失败（不影响工具）：${e?.message ?? e}`)
  }
}

/**
 * 把帧流挂到 DSH 的 Web 服务上，供面板用 SSE 订阅。
 *
 * 做法照抄上游 `dsh-ego-browser`（这是它跑通的形态）：
 * 服务端从 `ctx.get("webServer")` 拿，再 `register({kind, path, handler})`；
 * **返回值是 dispose**，所以要放进 `ctx.effect` 里随插件卸载。
 *
 * ⚠️ 两个必须照抄的点：
 *   1. **自定义路由要自己鉴权** —— 上游用 `/(?:^|;\s*)dsh-auth-[^=]+=/` 判 cookie，
 *      没有这个 cookie 一律 401；少了这一步等于把画面裸露给局域网。
 *   2. `kind: "exact"` 才是精确路径匹配。
 *
 * 一切失败都只是"没有面板"，**绝不影响工具本身**。
 *
 * @param {any} ctx 插件上下文
 * @param {{info?: Function, warn?: Function}} log 日志
 */
function mountStream(ctx, log) {
  let server = null
  try {
    server = ctx.get?.('webServer')
  } catch {
    /* 老版本宿主没有这个服务 */
  }
  if (!server || typeof server.register !== 'function') {
    log.warn?.('[nanxi-browser] 宿主没有 webServer 服务，面板不可用（工具照常）')
    return
  }

  /** 只信带 dsh-auth cookie 的请求（照抄上游的判据）。 */
  const trusted = (req) => /(?:^|;\s*)dsh-auth-[^=]+=/.test(String(req.headers?.cookie ?? ''))
  const guard = (handler) => (req, res) => {
    if (!trusted(req)) {
      res.statusCode = 401
      res.setHeader('Content-Type', 'application/json; charset=utf-8')
      res.end('{"ok":false,"error":"unauthorized"}')
      return
    }
    return handler(req, res)
  }

  safeEffect(
    ctx,
    () =>
      server.register({
        kind: 'exact',
        path: STATE_ROUTE,
        handler: guard((_req, res) => {
          res.statusCode = 200
          res.setHeader('Content-Type', 'application/json; charset=utf-8')
          res.setHeader('Cache-Control', 'no-store')
          res.end(
            JSON.stringify({
              running: browser.running,
              url: browser.url,
              title: browser.title,
              seq: browser.frameSeq,
              hasFrame: browser.frame !== null,
              cursor: browser.cursor,
            }),
          )
        }),
      }),
    'nanxi-browser: state route',
    log,
  )

  safeEffect(
    ctx,
    () =>
      server.register({
        kind: 'exact',
        path: STREAM_ROUTE,
        handler: guard((_req, res) => {
          res.statusCode = 200
          res.setHeader('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
          res.setHeader('Cache-Control', 'no-store')
          res.setHeader('Connection', 'close')
          let last = -1
          let stopped = false
          res.on?.('close', () => {
            stopped = true
          })
          const timer = setInterval(() => {
            if (stopped) {
              clearInterval(timer)
              return
            }
            const f = browser.frame
            if (!f || browser.frameSeq === last) return
            last = browser.frameSeq
            // MJPEG：浏览器原生支持 multipart/x-mixed-replace，<img src> 就能当视频流用。
            res.write(`--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${f.length}\r\n\r\n`)
            res.write(f)
            res.write('\r\n')
          }, 120)
          res.on?.('close', () => clearInterval(timer))
        }),
      }),
    'nanxi-browser: stream route',
    log,
  )

  log.info?.(`[nanxi-browser] 面板端点已挂：${STREAM_ROUTE}（帧流）/ ${STATE_ROUTE}（状态）`)
}

export function apply(ctx) {
  const log = ctx.logger ?? console
  log.info?.(
    `[nanxi-browser] 已加载：CDP 调试端口 ${PORT}，profile ${PROFILE}，` +
      `浏览器 ${findBrowser() ?? '（没找到 Chrome/Edge）'}`,
  )

  ctx.tools.register(
    defineTool({
      name: 'nanxi_browser_open',
      description:
        '用南汐自己的浏览器打开一个网页，并把页面上的文字读回来。' +
        '需要操作没有命令行接口的东西（Web 后台、在线看板）时用它。',
      parameters: {
        url: { type: 'string', description: '要打开的网址，不写 https:// 也行', required: true },
      },
      output: {
        schema: {
          type: 'object',
          properties: {
            title: { type: 'string', required: true },
            text: { type: 'string', required: true },
          },
          additionalProperties: false,
        },
        render: (_args, v) => text(`标题：${v.title}\n\n${v.text.slice(0, 4000)}`),
      },
      async execute(args) {
        const got = await browser.goto(args.url)
        return { title: got.title, text: got.text.slice(0, 4000) }
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'nanxi_browser_click',
      description:
        '在南汐自己的浏览器里点一个元素 —— target 既可以是 CSS 选择器，也可以是元素上的可见文字。',
      parameters: {
        target: { type: 'string', description: 'CSS 选择器，或元素上那行可见文字', required: true },
      },
      output: {
        schema: {
          type: 'object',
          properties: {
            ok: { type: 'boolean', required: true },
            note: { type: 'string', required: true },
          },
          additionalProperties: false,
        },
        render: (_args, v) => text(v.note),
      },
      async execute(args) {
        return browser.click(args.target)
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'nanxi_browser_type',
      description: '往南汐自己的浏览器里的输入框填字（搜索框、登录框、表单）。',
      parameters: {
        target: { type: 'string', description: '输入框的 CSS 选择器 / placeholder / name', required: true },
        text: { type: 'string', description: '要填进去的内容', required: true },
      },
      output: {
        schema: {
          type: 'object',
          properties: {
            ok: { type: 'boolean', required: true },
            note: { type: 'string', required: true },
          },
          additionalProperties: false,
        },
        render: (_args, v) => text(v.note),
      },
      async execute(args) {
        return browser.type(args.target, args.text)
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'nanxi_browser_see',
      description:
        '给南汐当前打开的那个网页截一张图，存到磁盘并返回路径（调用方可以把图发出去）。',
      parameters: {
        // ⚠️ 可选参数就**不要**写 required（没有 required: false 这种写法 —— 规范里
        //    required 只作为每个属性上的 `required: true` 出现）。
        path: { type: 'string', description: '可选的保存路径；不写就存到临时目录' },
      },
      output: {
        schema: {
          type: 'object',
          properties: {
            path: { type: 'string', required: true },
            bytes: { type: 'number', required: true },
          },
          additionalProperties: false,
        },
        render: (_args, v) => text(`截图已存：${v.path}（${v.bytes} 字节）`),
      },
      async execute(args) {
        const out = args.path || join(tmpdir(), `nanxi-browser-${Date.now()}.png`)
        const bytes = await browser.screenshot(out)
        return { path: out, bytes }
      },
    }),
  )

  log.info?.(
    '[nanxi-browser] 注册了 4 个工具：nanxi_browser_open / _click / _type / _see',
  )

  // 把画面/状态端点挂到 DSH 的 Web 服务上，供界面里的面板订阅（照抄 ego-browser 的形态）。
  mountStream(ctx, log)

  // 浏览器一被创建就开始推帧，面板打开就能看到画面（而不是等下一次操作）。
  safeEffect(
    ctx,
    () => {
      const tick = setInterval(() => {
        if (browser.running && !browser.casting && browser.ws) {
          browser.watchOn().catch(() => {})
        }
      }, 2000)
      return () => clearInterval(tick)
    },
    'nanxi-browser: keep screencast on',
    log,
  )
}
