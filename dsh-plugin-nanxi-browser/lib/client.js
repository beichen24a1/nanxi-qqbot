/**
 * dsh-nanxi-browser 的前端：在界面右下角挂一个浮动按钮，点开就是**她浏览器的实时画面**。
 *
 * ## 形态从哪抄的
 *
 * 抄上游 `dsh-ego-browser/lib/client.js` 的骨架：client facet 与 host facet 同构 ——
 * `name` / `inject` / `apply(ctx)`，用 `ctx.effect(fn, label)` 注册副作用（**返回 dispose**），
 * 面板本体就是**直接操作 DOM**（它也没用 DSH 的 UI 框架）。
 *
 * 与它不同的是**画面怎么来**：它自己起 SSE 转发帧；这里直接用 **MJPEG**
 * （`multipart/x-mixed-replace`）—— 浏览器对 `<img src>` 原生支持流式替换，
 * 所以一个 `<img>` 就是一个"视频"窗，不用写一帧一帧的 JS。
 *
 * ⚠️ 端点要带 cookie（host 侧自己校验 `dsh-auth-*`），`<img>` 同源请求会自动带上，
 * 所以这里什么都不用做。
 */

const name = 'dsh-nanxi-browser'

/** 面板的 DOM id（幂等用：重复加载不会插两个）。 */
const FAB_ID = 'nanxi-browser-fab'
const PANEL_ID = 'nanxi-browser-panel'

const CSS = `
#${FAB_ID}{
  position:fixed;right:18px;bottom:18px;z-index:2147483000;
  width:44px;height:44px;border-radius:50%;border:1px solid rgba(255,255,255,.18);
  background:#1b1b1f;color:#8fd3ff;font-size:20px;line-height:1;cursor:pointer;
  box-shadow:0 4px 16px rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;
}
#${FAB_ID}:hover{background:#242429}
#${PANEL_ID}{
  position:fixed;right:18px;bottom:72px;z-index:2147483000;width:min(720px,46vw);
  background:#141417;border:1px solid #333;border-radius:10px;overflow:hidden;
  box-shadow:0 12px 40px rgba(0,0,0,.55);display:none;font:12px/1.5 system-ui,sans-serif;color:#ddd;
}
#${PANEL_ID}.open{display:block}
#${PANEL_ID} .bar{display:flex;gap:10px;align-items:center;padding:7px 10px;background:#1b1b1f;border-bottom:1px solid #333}
#${PANEL_ID} .bar b{color:#8fd3ff;font-weight:600}
#${PANEL_ID} .bar .k{color:#888}
#${PANEL_ID} .bar .sp{flex:1}
#${PANEL_ID} .bar button{background:transparent;border:1px solid #3a3a40;color:#ccc;border-radius:5px;padding:2px 8px;cursor:pointer;font-size:11px}
#${PANEL_ID} .wrap{position:relative;line-height:0}
#${PANEL_ID} img{width:100%;display:block;background:#0b0b0d;min-height:120px}
#${PANEL_ID} .dot{position:absolute;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;
  background:rgba(255,60,60,.9);box-shadow:0 0 10px 3px rgba(255,60,60,.5);pointer-events:none;display:none}
#${PANEL_ID} .off{padding:22px;color:#888;text-align:center}
`

/**
 * 插件的前端入口（DSH 通过 package.json 的 exports["./client"] 找到这里）。
 *
 * @param {any} ctx 前端插件上下文；只用 `ctx.effect`（注册副作用并拿到 dispose）。
 */
function apply(ctx) {
  if (typeof document === 'undefined') return

  ctx.effect(
    () => {
      if (document.getElementById(FAB_ID)) return undefined // 幂等

      const style = document.createElement('style')
      style.dataset.plugin = 'nanxi-browser'
      style.textContent = CSS
      document.head.appendChild(style)

      const fab = document.createElement('button')
      fab.id = FAB_ID
      fab.title = '南汐的浏览器'
      fab.textContent = '🐾'

      const panel = document.createElement('div')
      panel.id = PANEL_ID
      panel.innerHTML = `
        <div class="bar">
          <b>南汐的浏览器</b>
          <span><span class="k">页面:</span> <span data-f="title">—</span></span>
          <span><span class="k">帧:</span> <span data-f="seq">0</span></span>
          <span class="sp"></span>
          <button data-f="close">收起</button>
        </div>
        <div class="wrap">
          <img alt="南汐的浏览器画面">
          <div class="dot"></div>
        </div>
        <div class="off">她还没开浏览器。她一用，这里就有画面了。</div>`

      document.body.appendChild(fab)
      document.body.appendChild(panel)

      const img = panel.querySelector('img')
      const dot = panel.querySelector('.dot')
      const off = panel.querySelector('.off')
      const elTitle = panel.querySelector('[data-f="title"]')
      const elSeq = panel.querySelector('[data-f="seq"]')
      let streaming = false

      /** 打开/关闭面板；打开时才开始拉流（省资源）。 */
      const setOpen = (open) => {
        panel.classList.toggle('open', open)
        if (open) {
          if (!streaming) {
            streaming = true
            img.src = `/api/nanxi-browser/stream?t=${Date.now()}`
          }
        } else if (streaming) {
          streaming = false
          img.removeAttribute('src') // 断开 MJPEG 连接
        }
      }
      fab.addEventListener('click', () => setOpen(!panel.classList.contains('open')))
      panel.querySelector('[data-f="close"]').addEventListener('click', () => setOpen(false))

      // 状态轮询：标题 / 帧号 / "她刚点在哪"的红点。
      const timer = setInterval(async () => {
        if (!panel.classList.contains('open')) return
        try {
          const s = await (await fetch('/api/nanxi-browser/state', { cache: 'no-store' })).json()
          elTitle.textContent = s.title || s.url || '—'
          elSeq.textContent = s.seq
          off.style.display = s.hasFrame ? 'none' : 'block'
          if (s.cursor && s.hasFrame) {
            const r = img.getBoundingClientRect()
            dot.style.left = s.cursor.x * r.width + 'px'
            dot.style.top = s.cursor.y * r.height + 'px'
            dot.style.display = 'block'
          } else {
            dot.style.display = 'none'
          }
        } catch {
          /* 面板打不开就算了 */
        }
      }, 700)

      return () => {
        clearInterval(timer)
        fab.remove()
        panel.remove()
        style.remove()
      }
    },
    'nanxi-browser: watch panel',
  )
}

export { apply, name }
