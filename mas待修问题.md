# mas 待修问题清单

> 由 `@南汐 /mas <问题>` 的答疑自动收录；`/mas问题` 查看，`/mas草稿 N` 拟 issue 草稿，`/mas提issue N` 提交（仅主人）。
> **状态可以直接手改**：`待修` / `已修` / `忽略` / `已提issue`。

## #1 [高·确定] MAS 的 MAA 专项未暴露 `UseExpiringMedicine`（无限吃 48 小时内过期的理智药），普通理智作战把该项写死关闭，用户在 MAA 本体里的设置会被覆盖
- 位置：app/utils/constants.py:247
- 状态：已提issue
- 首次：2026-09-19 08:35
- 最近：2026-09-19 08:45
- 出现：2 次
- 建议：在 MAA 用户页补一个「无限吃临期理智药」开关，并接进生成的那两份作战任务配置
- 证据：`constants.py:247` 的 `MAA_REMAIN_FIGHT_BASE` 把它写死 False，用户配置里没有对应字段，还有测试钉着这个行为
- 来源：北晨（<OWNER_QQ>）｜automas 拉起的 maa 没有无限制吃n小时内过期的理智药这个配置
- issue：https://github.com/AUTO-MAS-Project/AUTO-MAS/issues/873

## #2 [中·疑似] MAA 理智作战的 `UseExpireMedicineForActivity`（活动关临期药）与 `IsDrGrandet`（博朗台模式）同样看不出有入口
- 位置：res/docs/MAA配置文件信息.md
- 状态：已提issue
- 首次：2026-09-19 08:45
- 最近：2026-09-19 08:45
- 出现：1 次
- 建议：跟 #1 一起补入口；没逐个核界面前先在 issue 里写「看不出有入口」而不是「没有」
- 证据：MAA 的理智作战段共 19 个字段，MAS 侧能对上的只有任务开关、吃理智药数量、活动关理智药数量几项
- 来源：北晨（<OWNER_QQ>）｜直接提pr？或者是再看看有没有别的在maa里有但mas里没有的
- issue：https://github.com/AUTO-MAS-Project/AUTO-MAS/issues/873

## #3 [高·确定] 剿灭作战与普通理智作战对临期药开关行为不一致（一处打开、一处关闭），用户会当成「时灵时不灵」
- 位置：app/utils/constants.py:206,247
- 状态：已提issue
- 首次：2026-09-19 08:45
- 最近：2026-09-19 08:45
- 出现：1 次
- 建议：两处统一（或都暴露成开关）
- 证据：`constants.py:206` 的剿灭那份是打开的，`:247` 的普通作战是关闭的
- 来源：北晨（<OWNER_QQ>）｜顺带在 issue 里提了个不一致
- issue：https://github.com/AUTO-MAS-Project/AUTO-MAS/issues/873

## #4 [高·确定] 鸣潮主菜单新增「协议更新」按钮后，OK-WW 专项按写死的 1080p 坐标定位「账号」按钮失效，账号菜单打不开
- 位置：app/task/Okww/tools/account_switch.py:57
- 状态：已提issue
- 首次：2026-09-19 09:01
- 最近：2026-09-19 09:01
- 出现：1 次
- 建议：把「账号」也改成 OCR 找文字（同文件里识别「确认登出」已经是这个做法），或把 y 值做成可配置
- 证据：注释里列了 1080p 下右侧竖排按钮的 y 值（退出193 公告317 工具450 账号576 设置709），多一个按钮整列就挪位
- 来源：北晨（<OWNER_QQ>）｜用户说"鸣潮出了一个协议更新的按钮导致切换账号失效"
- issue：https://github.com/AUTO-MAS-Project/AUTO-MAS/issues/874
