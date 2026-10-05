# 复盘：把南汐的浏览器做成正规 DSH 插件（B 计划）—— 2026-10-04/05

> **一句话结论**：插件 `dsh-nanxi-browser` **通过**了 DSH 的全部 bundle 加载检查（stderr 干净、
> 无 `skipping profile bundle`），**但仍未生效**（工具不在、自定义路由 404）。
> 在"加载层之后"这一段，我**没有观测手段**，因此按主人决定**收手**。
> 本文把六轮尝试、每轮的推断与证伪、以及**已确证的硬事实**完整留档，供下次接着查。

---

## 一、目标与本轮背景

主人原话（大意）：**「我觉得甚至我们是不是可以直接二次开发个 harness 了」** →
澄清后选定 **B 计划：不做新 harness，而是把南汐的浏览器能力做成 DSH 的"正规插件"**
（而不是我现在那种改 `node_modules` 的补丁 —— 那些升级就丢）。

**B 计划的分层**：

| 层 | 内容 | 状态 |
|---|---|---|
| **B1** | 插件骨架 + 4 个工具（`nanxi_browser_open/_click/_type/_see`） | ✅ 代码验证通过、已装进 profile |
| **B2** | `lib/client.js` + 在 DSH 界面里看画面的面板 | ✅ 代码写完（MJPEG + 浮动按钮） |
| **B3** | 把那 4 个 node_modules 补丁改写成插件 | ⬜ 未开始（且**性质不同**，见文末） |
| **—** | **能不能被 DSH 真正加载** | ❌ **卡在这里** |

**要交付的形态**（照抄上游 `dsh-ego-browser` / `dsh-share`）：

```
dsh-plugin-nanxi-browser/
├── package.json          ← bundle manifest（dsh.bundle.patch）+ exports["./client"]
├── cordis.patch.yml      ← - insert: [{id, name}]
└── lib/
    ├── index.js          ← host facet：CDP 客户端 + 4 个工具 + MJPEG/state 两个端点
    └── client.js         ← client facet：右下角浮动按钮，点了就是实时画面 + 鼠标红点
```

---

## 二、六轮尝试（每轮：推断 → 做法 → 结果 → 为什么错）

### 第 1 轮：`failed to import`

- **现象**：日志 `nanxi-browser (dsh-nanxi-browser): failed to import`，端点 401。
- **推断**：解析不到 `@deepseek-ai/dsh-tools`（插件是 `link:` 装的，住在 `<PROJECT_ROOT>\`）。
- **做法**：在插件目录建 `node_modules/@deepseek-ai/{dsh-tools,dsh-llm,cordis}` 的 **junction**
  指向 DSH 那份。
- **结果**：**ERR_MODULE_NOT_FOUND 修好了**（从插件目录能 import 了），但**仍然不加载**。
- **对错**：**推断正确、修法有效，但不是根因。**

**副产品（真的有用）**：查到了那句报错的出处 —— `@deepseek-ai/dsh-app-boot/lib/index.js` 约 3910 行：

```js
const fiber = entry.fiber;
if (fiber === void 0) {
  failures.push({ entry, outcome: { kind: "failed", error: "failed to import" } });
}
```

⇒ **"failed to import" 只是 `entry.fiber === undefined`，真错被吞掉了** —— 所以这个词几乎不含信息量。

---

### 第 2 轮：patch 的 `id` 与 `export const name` 不一致

- **推断**：技能文档写着 `export const name` **must match the patch file's `id`**。
  我写的是 `id: nanxi-browser` 而代码里 `export const name = 'dsh-nanxi-browser'`。
- **做法**：把 `id` 改成 `dsh-nanxi-browser`。
- **结果**：**无效**。
- **对错**：**推断错**。对照三个上游插件后才看清真正的规矩是
  **包名 = patch 的 `id` = patch 的 `name` = `export const name`，四者必须同一字符串**：

  | 插件 | package.json name | patch id / name | 代码里的 name |
  |---|---|---|---|
  | `dsh-share` | dsh-share | dsh-share / dsh-share | "dsh-share" |
  | `dsh-astrbot-relay` | dsh-astrbot-relay | dsh-astrbot-relay / 同名 | 同名 |

  ⇒ 我这一版**四者其实已经一致了**，所以改不改都一样。

---

### 第 3 轮：不在 `dsh.profile.bundles` 白名单里

- **推断**：DSH 只加载 `profile/package.json` 的 `dsh.profile.bundles` 里列出的插件，
  而 `dsh plugin add` 只写了 `dependencies`。
- **做法**：准备手动 append。
- **结果**：**`dsh plugin add` 早就加过了**（21 项，含目标）。**推断错，且无需改动。**
- **对错**：错。**但这一轮搞清了一件事**：`dsh plugin` **不是 DSH 的子命令** ——
  `dsh plugin --help` 打印的是 **pnpm 的帮助**，它是 `pnpm` 的透传别名。

```json
// profile/package.json（片段）
"dsh": { "profile": { "bundles": [ "@deepseek-ai/dsh-base", "dsh-astrbot-relay",
                                  "dsh-ego-browser", "dsh-nanxi-browser", … ] } }
```

---

### 第 4 轮：`link:` 软链不被接受

- **现象（对比）**：

  | 插件 | dependencies 里的值 | node_modules 里的形态 |
  |---|---|---|
  | dsh-ego-browser | `0.8.6` | 实体目录 |
  | dsh-astrbot-relay | `file:….tgz` | 实体 |
  | **dsh-nanxi-browser** | **`link:…`** | **SymbolicLink** |

- **推断**：只有我是软链、也只有我失败 ⇒ 强相关。
- **做法**：改成 `file:<PROJECT_ROOT>/dsh-plugin-nanxi-browser` + `pnpm install`。
- **结果**：node_modules 里**变成了实体目录**，**但插件仍不加载**。
- **对错**：**相关但非因果**。（`Packages: +1 -2` 那个 `-2` 是 pnpm 的内部计数，
  与备份 diff 核对过：依赖 18 → 19，**只多不少**，没弄坏任何东西。）

---

### 第 5 轮：`exports` 白名单缺 `./cordis.patch.yml`

- **推断**：`exports` 是白名单，没列出的子路径外部读不到；而 `dsh.bundle.patch` 指向它，
  DSH 要 import 那个文件 ⇒ 拿不到。
  **旁证**：`dsh-astrbot-relay` **专门** export 了 `"./cordis.patch.yml"` 和 `"./package.json"`。
- **做法**：补上这两个 export，并加 `dsh.client: { platform: "web" }`。
- **结果**：**无效**。
- **对错**：**推断错**。决定性反证：`node -e "require.resolve('dsh-ego-browser/cordis.patch.yml')"`
  **同样报 ERR_PACKAGE_PATH_NOT_EXPORTED**，而 ego-browser 是**能正常工作**的。
  ⇒ **DSH 不是用 `require.resolve` 去读 patch 的。**

（这两个 export 现在**仍留在文件里**，无害。）

---

### 第 6 轮（决定性的一轮）：抓 stderr —— 插件其实**通过了**所有检查

- **思路转变**：不再猜，去找**权威信号**。读 `dsh-app-boot/lib/index.js` 的
  `loadProfileDirectory()`（约行 920-958）：

```js
for (const packageName of bundles) try {
    const packageDir = resolveBundleDir(binName, packageName, installAnchor, dir);
    const bundleManifest = readProfileManifest(binName, packageDir);
    const bundle = bundleManifest.dsh?.bundle;
    if (bundle === void 0) throw new Error(`${binName}: profile bundle … declares no dsh.bundle …`);
    const issue = evaluatePluginCompatibility(bundleManifest, exemptions);
    if (issue !== void 0 && !issue.exempted) throw new Error(pluginCompatibilityWarning(issue));
    const patchPaths = bundlePatchPaths(packageDir, bundle);
    const patches = patchPaths.flatMap((p) => loadOverlayPatches(binName, p));
    layers.push({ packageName, packageDir, patchPaths, patches });
} catch (error) {
    skippedBundles.push({ packageName, reason: String(error) });   // ← 静默跳过
}
```

  而 `reportSkippedBundles()` 会把它打到 **stderr**：

```js
process.stderr.write(`${binName}: skipping profile bundle ${JSON.stringify(packageName)}`)
```

- **做法**：前台跑 dsh，**stdout / stderr 分开落盘**。
- **结果**：

```
stderr 全文：recall shell dialect probe: pwsh        ← 只有这一行
```

⇒ **没有 `skipping profile bundle "dsh-nanxi-browser"`** ⇒ **它通过了全部检查、进了 `layers`。**

- **对错**：**这一轮终于拿到了硬事实**（虽然还没解决问题）。
- **⚠️ 我在这里犯的操作错误**：为了抓 stderr，我用过
  `Get-Process node | Where StartTime -gt (now-10min) | Stop-Process` ——
  **这是危险动作**，差点伤到主 DSH 和 AstrBot。实测只杀掉了刚起的 nanxi（运气），
  **以后绝不这么干**。

---

## 三、已确证的硬事实（下次直接用，别再重新发现）

1. **判据**：判断"DSH 跳过了某个 bundle"**只能看 stderr** 上的
   `skipping profile bundle "<name>"`。**stdout 上没有**。
2. **别用日志判断插件加载**：nanxi 实例的 stdout 里**只有三个插件会说话**
   （`dsh-memory-evolve` / `dsh-cost-meter` / `dsh-approval-gate`），
   其他插件（`dsh-share`、`dsh-ego-browser`…）**完全静默**。
3. **`failed to import` = `entry.fiber === undefined`**，真错被吞，几乎不含信息量。
   但 `apply()` 里抛任何错也会落成同一个词 ⇒ **插件里"锦上添花"的部分要 try/catch**
   （我为此加了 `safeEffect()`）。
4. **`link:` 装的插件解析不到 `@deepseek-ai/*`**（该包只在 DSH 安装目录的 node_modules 里）。
   上游插件没事是因为它们**本身装在 profile 的 node_modules 里**。
   解法：插件目录建 junction，或在 profile 里用 `file:` 装。
5. **`dsh plugin` 是 pnpm 的透传别名**（`dsh plugin --help` 打印 pnpm 帮助）。
6. **`dsh --profile <name>` 必须在 `DSH_HOME=<该 HOME>` 下跑**，否则报 profile does not exist。
7. **`evaluatePluginCompatibility` 只查 `peerDependencies` 里 `@deepseek-ai/dsh*`
   是否满足运行时版本** —— 没有 `peerDependencies` 就必然通过。
8. **client facet 与 host facet 同构**：`name` + `apply(ctx)`；
   前端由 `package.json` 的 `exports["./client"]` 指路；面板**直接操作 DOM**
   （ego-browser 也没用 DSH 的 UI 框架）；注册副作用用 `ctx.effect(fn, label)`。
9. **host 自定义路由**：`ctx.get("webServer").register({ kind: "exact", path, handler })`，
   **必须自己校验 `dsh-auth-*` cookie**（否则等于裸奔）。
10. **画面不用逐帧推送**：MJPEG（`multipart/x-mixed-replace`）+ 一个 `<img>` 就够，
    浏览器原生支持流式替换。
11. **CDP 的 screencast 帧是【事件】不是响应**，且**每帧必须回 `Page.screencastFrameAck`**，
    不回就不再推下一帧。
12. **headless 的帧里没有光标** —— 上游那个"鼠标"是前端按坐标自己画的。

### 三条 PowerShell / 编码的坑（都实际卡过我）

13. **`.ps1` 必须带 UTF-8 BOM**。无 BOM + 中文注释 ⇒ `powershell.exe`(5.1) 按 ANSI 解码 ⇒
    中文里的全角标点被当字符串边界 ⇒ 报 `字符串缺少终止符: '。` 这种位置错乱的语法错。
    ⚠️ **而 `Parser::ParseFile`（.NET，按 UTF-8）会说"语法 OK"** —— **别只信它，要真跑**。
14. **PowerShell 会缓冲原生命令的输出** ⇒ `& cmd | ForEach-Object { … }` 里写文件，
    **服务活着的时候文件一直是 0 字节**（它不退出 ⇒ 永远看不到日志）。
    正解：让 cmd 自己重定向 `cmd /c "… > log 2>&1"`，每行实时落盘。
    另一个变体：先 `New-Object StreamWriter` 占住日志文件，会与"别人也写这个文件"互锁
    （症状 `正由另一进程使用` + `找不到属性 AutoFlush`）。
15. **`Start-Process cmd /c bat -RedirectStandardOutput <log>` 会抢掉 ps1 内部同名日志文件**
    （ps1 自己也用同一时间戳命名）⇒ DSH 起来了但一个字的日志都没有。
    **自己重启 nanxi 的正确姿势**：`启动\stop-nanxi-dsh.bat` → 等端口真的释放 →
    `启动\start-nanxi-dsh.bat`（**不要**加外层重定向）。

---

## 四、卡点：到底还差什么

**已知**：插件**通过了** `loadProfileDirectory` 的全部检查、**进了 `layers`**。

**未知**：从 `layers` 到"工具真的被注册 / 路由真的挂上"之间**还发生了什么**。
这一层我**没有观测手段**：

- 日志看不到（`apply` 里的 `log.info` 没出现 ⇒ 要么 `apply` 没被调用，要么它的 logger 不落盘）；
- stderr 干净（没有失败记录）；
- 端点 404（路由没挂上）；
- 工具状态无法直接查询（`interconnect` 需要 nanxi 上有活着的会话，而重启后 agent 尚未被唤醒）。

### 下次从哪继续（具体入口）

1. **先解决观测**：让"运行中能看到日志"这件事**独立验证通过**
   （用干净的 `stop` → 确认端口释放 → `start`，看日志文件在 DSH 跑着的时候就 > 0 字节）。
   现在是第 4 版（cmd 内重定向 + BOM），**尚未在干净重启下验证过**。
2. **然后读 `layers` 之后的下游**：继续在 `dsh-app-boot/lib/index.js` 里跟
   `layers` / `patchPaths` / `patches` 的去向 —— 看它是怎么把 patch 变成
   loader entry 的（`- insert: [{id, name}]` 的 `name` 最终怎么被 `import`）。
   重点找：**它 `import` 的到底是包名、还是某个导出的路径**。
3. **一次只改一个变量**，每步都用**权威信号**（stderr / 工具清单 / 带 cookie 的路由状态码）
   判定，不要靠"读日志猜"。

### 一个仍未排除的可能

第一次失败时（第 1 轮之前）日志里出现的是 `failed to import`，而**修好依赖之后它就消失了**。
如果后来某次改动让它变成"静默跳过"，stderr 应该会说话 —— **而 stderr 是干净的**。
所以更可能是 **`apply` 被调用了但没起作用**（例如 `ctx.tools.register` 抛错被我自己吞了）。
⇒ **值得回头看**：`safeEffect` 会不会把工具注册的失败也吞掉了？（它只包住了路由与推帧，
`ctx.tools.register` 是裸调的 —— 但它抛错也该落成 `failed to import`…）

---

## 五、B3 为什么"不是再写一个插件"

那 4 个补丁（`patch_relay_steer.py` / `patch_relay_approval_bridge.py` /
`patch_relay_rpc_methods.py` / `patch_relay_session_title.py`）改的是
**星驿（`dsh-astrbot-relay`）自己的源码** —— 那是**别人写的插件内部**，
没法用"外挂一个插件"去替换它的行为。干净的路只有两条：

- **给上游提 PR**（`steer` 是 DSH 本来就有的能力 `agent.steer`，星驿只用了 `followup`；
  审批的 session 兜底、会话标题保留，对上游也都成立）；
- **自己维护 fork**（长期要跟上游同步，成本不小）。

---

## 六、当前状态与回滚

**服务（都正常）**：

```
3080  主 DSH        LISTENING
3081  nanxi         LISTENING     星驿 /health: ok:true / conversations:6
6185  AstrBot       LISTENING
3002  OneBot 反向WS  LISTENING
```

**已落地的相关提交（新→旧）**：

| commit | 内容 |
|---|---|
| `9d167d9` | 启动日志改成 cmd 内重定向（**待干净重启验证**） |
| `90d832b` | 日志"拿不到独占句柄也能落盘"（后被上一条取代） |
| `9f48072` | patch 的 id 改为与包名/export name 一致 |
| `a3d132d` | junction 修 `ERR_MODULE_NOT_FOUND` |
| `e2c509d` | B2：client facet + 界面面板 |
| `7f87ab7` | B1：插件骨架 + 4 个工具 |
| `53be3b8` | AstrBot 侧浏览器看板（`127.0.0.1:6199`，**已验证可用**） |
| `361a433` | `web_dsh`：她能登进 DSH 控制台 |

**备份**（全在 `_backup\20261004\`）：
`nanxi-package.json.bak-before-nanxi-browser` / `…bak-before-bundle` / `…bak-before-file-dep`。

**回滚插件影响**（若想彻底摘掉）：

```powershell
# 1) 从 profile 的 bundles 里删掉 "dsh-nanxi-browser"
# 2) 删掉 dependencies 里那一行，然后：
cd <NANXI_DSH_HOME>\profiles\nanxi
pnpm install
# 3) 重启：启动\stop-nanxi-dsh.bat → 启动\start-nanxi-dsh.bat
```

⚠️ **现状是"留着也无害"**：它已经装好、在 bundles 里、stderr 干净，
既不影响启动也不影响其他插件（实测 nanxi 正常、星驿 ok）。**所以可以就这么搁着**。

---

## 七、这次最该记住的三条

1. **别只信"看起来对"的检查** —— `Parser::ParseFile` 说语法 OK，实际跑起来报错。
   **能真跑就真跑。**
2. **每一个判断都要能指向一个权威信号**（stderr / 官方 UI / 状态码）。
   我前五轮全是在"读日志 + 推断"，所以连着错了五次，还让主人重启了五次。
3. **观测手段没建立之前不要改代码** —— 这次真正的转折点是"抓 stderr"，
   而它本该是第一件事。
