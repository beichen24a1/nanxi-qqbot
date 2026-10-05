r"""让星驿【别覆盖用户自己起的会话名字】，改成「原标题 + _南汐」。

背景（为什么需要这个补丁）
--------------------------
星驿（dsh-astrbot-relay）每投递一条 IM 消息，就会把承接这条消息的 DSH 会话标题
改写成模板渲染值：

    lib/index.js:  sessionTitleTemplate = '星驿 · {platform}/{messageType}/{sessionId}'
    lib/index.js:  writeSessionTitle() → applySessionTitle() → titles.rename(session, title)

这在"星驿自己新建的会话"上没问题（本来就没名字，写个来源更好认）；但南汐会
**接手主人早就起过名字的老会话**，于是主人的名字被直接盖掉：

    2026-10-04 实测：`skill`（<WORKSPACE_MAS>）→ 变成「星驿 · onebot-qq/GroupMessage/<群号>」，
    主人在 GUI 里找不到 skill，以为自己把它归档了。

而且这一步是**钉死**的：`lib/session-title.js` 的注释说 `source.kind === 'user'` 的标题会
supersede 自动生成，写进去就不再变。

补丁做什么
----------
改两处（都在 node_modules 里的**上游产物**上，升级 dsh-astrbot-relay 后会丢，要重跑）：

1. `lib/session-title.js` 的 `applySessionTitle()` 增加 `suffix` 参数与"保留原名"分支：
   - 当前标题为空、或已经等于模板渲染值（= 星驿自己写的）⇒ 照旧写模板；
   - 是**用户起的名字** ⇒ 保留原文，只在后面缀 `suffix`（默认 `_南汐`）；
   - 已经缀过 `suffix` ⇒ 什么都不做（幂等，也省掉一条无意义的 title 事件）；
   - `suffix` 配成空串 ⇒ 这类会话**完全不碰**。
   另外给后缀留出字节预算（`TITLE_MAX_BYTES` = 80，与 dsh 侧上限一致），
   避免长原名把 `_南汐` 挤掉。
2. `lib/index.js` 增加配置项 `sessionTitleSuffix`（默认 `'_南汐'`）并把它传给
   `applySessionTitle()`。

用法（幂等，可反复执行）
------------------------
    C:\\Python310\\python.exe D:\\dsh\\QQbot\\patch_relay_session_title.py
    C:\\Python310\\python.exe D:\\dsh\\QQbot\\patch_relay_session_title.py --dry-run
    C:\\Python310\\python.exe D:\\dsh\\QQbot\\patch_relay_session_title.py --revert
    C:\\Python310\\python.exe D:\\dsh\\QQbot\\patch_relay_session_title.py --path <relay 目录>

改完**必须重启对应的 DSH 实例**（nanxi 用 `启动\\start-nanxi-dsh.bat`）才生效：
插件的 lib/*.js 是进程启动时 import 并常驻内存的，改文件不会热加载。

⚠️ 它只改"以后怎么写标题"，**不会**把已经被改掉的名字变回来 ——
那些会话的原名只可能在各自的 `storages/session_projcache/sessions/<id>.json`
（字段 `record.rows.title.val`）里留个旧值，需要单独用 `session/rename` 修。
"""

import sys
from pathlib import Path

MARK = "nanxi-patch:keep-user-title"

# 星驿的两个安装点：nanxi（南汐用的那个）与主实例的 web profile。
DEFAULT_PATHS = [
    Path(r"D:\dsh\nanxi-dsh\profiles\nanxi\node_modules\dsh-astrbot-relay"),
    Path(r"C:\Users\Administrator\.dsh\profiles\web\node_modules\dsh-astrbot-relay"),
]

# ---------------------------------------------------------------- 替换定义 ---

TITLE_JS = "session-title.js"
INDEX_JS = "index.js"

# --- session-title.js ---

E1_OLD = "export function applySessionTitle({ titles, session, template, conversation } = {}) {"
E1_NEW = (
    "export function applySessionTitle("
    "{ titles, session, template, conversation, suffix = '' } = {}) {"
)

E2_OLD = """  const title = renderSessionTitle(template, conversation)
  if (title.trim() === '') {
    return { ok: false, reason: TITLE_RESULT.EMPTY_TITLE, rendered: title }
  }

  if (titles === undefined || titles === null || typeof titles.rename !== 'function') {
    return { ok: false, reason: TITLE_RESULT.SERVICE_MISSING, rendered: title }
  }

  try {"""

E2_NEW = """  const rendered = renderSessionTitle(template, conversation)
  if (rendered.trim() === '') {
    return { ok: false, reason: TITLE_RESULT.EMPTY_TITLE, rendered }
  }

  if (titles === undefined || titles === null || typeof titles.rename !== 'function') {
    return { ok: false, reason: TITLE_RESULT.SERVICE_MISSING, rendered }
  }

  // ---- nanxi-patch:keep-user-title ----
  // 上面 JSDoc 说的"钉死"针对的是**本插件自己写下的**标题（反向定位要的稳定性）。
  // 但"用户早就给这间会话起过名字"是另一回事：盖成 `星驿 · …` 会让人在会话列表里
  // 认不出自己的东西（2026-10-04 实测：主人的「skill」被盖掉后以为已归档）。
  // 定制口径：空标题 / 星驿自己写的 ⇒ 照旧写模板；用户起的名字 ⇒ 保留原文 + suffix；
  // 已缀过 suffix ⇒ 不写（幂等）；suffix 为空串 ⇒ 这类会话完全不碰。
  const title = targetTitle({ titles, session, rendered, suffix })
  if (title === null) {
    return {
      ok: true,
      reason: TITLE_RESULT.OK,
      title: currentTitle(titles, session),
      rendered: currentTitle(titles, session),
    }
  }

  try {"""

E3_OLD = """ * @param {string} [options.conversation] 来源 IM 对话的 UMO"""

E3_NEW = """ * @param {string} [options.conversation] 来源 IM 对话的 UMO
 * @param {string} [options.suffix] 定制：用户**自己起过名字**的会话不再被模板覆盖，
 *   而是写成「原标题 + suffix」；空串表示这类会话完全不动。"""

E4_OLD = """/** UTF-8 字节长度。仅用于日志提示「这个标题会被截」，不参与截断决策。 */"""

E4_NEW = """/**
 * 读这间会话**当前**的标题；读不到（服务缺席、会话还没 live、字段为空）一律当空串。
 * 刻意吞掉异常：读标题失败不该让一条 IM 消息投不出去。
 *
 * @param {{get?: Function, rename?: Function}} titles session-title 服务
 * @param {object} session 目标会话对象
 * @returns {string} 归一化后的标题，或空串
 */
function currentTitle(titles, session) {
  try {
    const snapshot = typeof titles?.get === 'function' ? titles.get(session) : null
    const text = snapshot === null || snapshot === undefined ? '' : snapshot.title
    return typeof text === 'string' ? text.trim() : ''
  } catch {
    return ''
  }
}

/**
 * 决定这一轮该写什么标题（nanxi-patch:keep-user-title 的决策点）。
 *
 * @param {object} options
 * @param {{get?: Function, rename?: Function}} options.titles session-title 服务
 * @param {object} options.session 目标会话对象
 * @param {string} options.rendered 模板渲染结果（星驿自己那套命名）
 * @param {string} options.suffix 用户名字后面要缀的标记（空串 = 完全不碰这类会话）
 * @returns {string|null} 要写的标题；`null` 表示**这一轮不写**
 */
function targetTitle({ titles, session, rendered, suffix }) {
  const current = currentTitle(titles, session)
  // 没有名字，或标题就是本插件写的：照旧写模板（幂等重写，无副作用）。
  if (current === '' || current === rendered) return rendered
  // 到这里说明是**用户自己起的名字**：绝不覆盖。
  if (suffix === '') return null
  if (current.endsWith(suffix)) return null
  return fitSuffix(current, suffix)
}

/**
 * 给后缀留够字节预算，避免长原名把 `_南汐` 挤到 80 字节上限之外被 dsh 侧截掉。
 * 按**字符**回退（不是字节），所以永远不会把一个多字节字符劈成两半。
 *
 * @param {string} current 原标题
 * @param {string} suffix 后缀
 * @returns {string} 截好的「原名 + 后缀」
 */
function fitSuffix(current, suffix) {
  const budget = TITLE_MAX_BYTES - Buffer.byteLength(suffix, 'utf8')
  let base = current
  while (base.length > 0 && Buffer.byteLength(base, 'utf8') > budget) {
    base = base.slice(0, -1)
  }
  return base + suffix
}

/** UTF-8 字节长度。仅用于日志提示「这个标题会被截」，不参与截断决策。 */"""

# --- index.js ---

E5_OLD = (
    "  sessionTitleTemplate: "
    "Schema.string().default('星驿 · {platform}/{messageType}/{sessionId}'),"
)

E5_NEW = """  sessionTitleTemplate: Schema.string().default('星驿 · {platform}/{messageType}/{sessionId}'),
  /**
   * 定制（nanxi-patch:keep-user-title）：用户**自己起过名字**的老会话不再被模板覆盖，
   * 改为「原标题 + 本后缀」（默认 `_南汐`）。星驿新建的会话（本来没名字）仍走上面的模板。
   * 空串 = 这类会话完全不碰（连标题都不重写）。
   */
  sessionTitleSuffix: Schema.string().default('_南汐'),"""

E6_OLD = """        template: config.sessionTitleTemplate,
        conversation: bridge.conversation,
      })"""

E6_NEW = """        template: config.sessionTitleTemplate,
        conversation: bridge.conversation,
        suffix: config.sessionTitleSuffix,
      })"""

EDITS = {
    TITLE_JS: [
        ("签名加 suffix 参数", E1_OLD, E1_NEW),
        ("保留原名的决策分支", E2_OLD, E2_NEW),
        ("JSDoc 补 @param suffix", E3_OLD, E3_NEW),
        ("新增三个私有 helper", E4_OLD, E4_NEW),
    ],
    INDEX_JS: [
        ("新增配置项 sessionTitleSuffix", E5_OLD, E5_NEW),
        ("调用点传 suffix", E6_OLD, E6_NEW),
    ],
}


def patch_file(path: Path, edits, direction: str, dry_run: bool) -> int:
    """按给定的 (说明, old, new) 列表改一个文件。direction=apply 时 old→new，revert 反之。"""
    if not path.is_file():
        print(f"[FAIL] 找不到文件：{path}")
        return 1
    text = path.read_text(encoding="utf-8")

    if direction == "apply" and MARK in text:
        print(f"[OK] 已经打过补丁，跳过（幂等）：{path}")
        return 0

    plan = []
    for label, old, new in edits:
        src, dst = (old, new) if direction == "apply" else (new, old)
        n = text.count(src)
        if n == 0:
            print(f"[FAIL] {path.name}：找不到「{label}」的锚点。")
            print(f"       星驿可能已升级/改版，请人工确认。期望包含：{src[:90]}…")
            return 2
        if n > 1:
            print(f"[FAIL] {path.name}：锚点「{label}」出现 {n} 次，不敢改。")
            return 3
        plan.append((label, src, dst))

    for label, src, dst in plan:
        text = text.replace(src, dst, 1)

    if dry_run:
        print(f"[DRY-RUN] 会改 {path}（{len(plan)} 处，未写入）：")
        for label, _, _ in plan:
            print(f"     · {label}")
        return 0

    path.write_text(text, encoding="utf-8")
    print(f"[DONE] 已改 {path}（{len(plan)} 处）：")
    for label, _, _ in plan:
        print(f"     · {label}")
    return 0


def main() -> int:
    args = sys.argv[1:]
    revert = "--revert" in args
    dry_run = "--dry-run" in args
    use_all = "--all" in args
    path_arg = None
    for i, a in enumerate(args):
        if a == "--path":
            if i + 1 >= len(args):
                print("[FAIL] --path 后面要跟一个目录")
                return 2
            path_arg = args[i + 1]
        elif a not in ("--revert", "--dry-run", "--all", "--path") and (
            i == 0 or args[i - 1] != "--path"
        ):
            print(f"[FAIL] 未知参数：{a}（认 --revert / --dry-run / --all / --path <dir>）")
            return 2

    if path_arg is not None:
        roots = [Path(path_arg)]
    elif use_all:
        roots = DEFAULT_PATHS
    else:
        roots = [DEFAULT_PATHS[0]]

    direction = "revert" if revert else "apply"
    action = "还原成上游原版" if revert else "打上补丁"
    print(f"=== {action}（{'dry-run' if dry_run else '写入'}）===")

    rc = 0
    for root in roots:
        if not root.is_dir():
            print(f"[SKIP] 目录不存在：{root}")
            continue
        for fname, edits in EDITS.items():
            r = patch_file(root / "lib" / fname, edits, direction, dry_run)
            if r != 0:
                rc = r

    if rc == 0:
        if dry_run:
            print("\n（dry-run 结束，什么都没写）")
        else:
            print("\n提醒：必须重启对应 DSH 实例才生效 ——")
            print("      nanxi → 双击 启动\\start-nanxi-dsh.bat（先确认 3081 上的旧进程已退出）")
            print("      main  → 双击 启动\\一键启动.bat 之外的主 DSH 启动方式")
    return rc


if __name__ == "__main__":
    sys.exit(main())
