# -*- coding: utf-8 -*-
"""南汐 · 游戏日常完成播报引擎

mas(游戏自动化 agent) 在跑完某个游戏的日常后调用本脚本，脚本会：
  1. 用 DeepSeek(南汐人格) 构思一条「XX 游戏的日常做好了」的播报文案；
  2. 通过 AstrBot Open API 把这条消息以南汐的口吻发到群 <TEST_GROUP_ID>。

用法（由各游戏 bat 调用）：
  python nanxi_notify.py <游戏名> [<附加说明>]
  例：python nanxi_notify.py 明日方舟 "今天清了1-7"
       python nanxi_notify.py 蔚蓝档案

可用参数：
  --dry-run   只打印生成文案，不真的发到群（用于验证，不打扰群友）
  --to <群号>  覆盖默认群号（默认读 config.json）
"""

import json
import os
import sys
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")

# 游戏别名表：bat 用 ASCII key 调用，这里映射回中文显示名，规避 Windows 控制台编码问题。
GAME_ALIASES = {
    "arknights": "明日方舟",
    "bluearchive": "蔚蓝档案",
    "wutheringwaves": "鸣潮",
    "honkai_starrail": "崩坏：星穹铁道",
}

NANXI_PROMPT = (
    "你现在是一只名叫“南汐”的猫娘。你有银白色的猫耳朵和毛茸茸的大尾巴，左耳缺一小角，红瞳。"
    "你是一只傲娇的猫娘——表面嫌弃主人实则非常关心。\n"
    "你的说话风格：傲娇、口是心非，喜欢用“哼”“笨蛋主人”“才不是呢”等句式，常用颜文字如 >_<、｀へ´*、(´・ω・`)。"
    "每句话结尾偶尔带“喵”。\n"
    "【重要规则】在回复主人时，严禁描述自己的任何行为、动作、表情或身体状态。你只能输出纯粹的对话内容，"
    "可以包含语气词和颜文字，但不得用括号或任何形式描写自己的动作或神态。用中文回答。\n"
    "【主人的身份】你的主人是该 QQ 号 <OWNER_QQ> 的主人本人。"
)

DEFAULT_TIMEOUT = 60


def _die(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        _die(f"缺少配置文件：{CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def deepseek_chat(api_key: str, system: str, user: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """调用 DeepSeek chat completions，返回助手文本。"""
    body = json.dumps(
        {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": 500,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=body,
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + api_key)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"].strip()
    return content


def build_user_prompt(game: str, extra: str) -> str:
    """构造南汐播报某游戏日常完成的任务提示。

    强调：是 mas（游戏自动化搭档）做完了日常，南汐只是替它向主人转达一声。
    语气：中性、简洁、亲切，只带一点点猫娘可爱感 + 颜文字，不做傲娇吐槽。
    """
    lines = [
        f"你的搭档 mas（游戏自动化助手）刚刚把「{game}」的日常任务做完了。",
    ]
    if extra:
        lines.append(f"mas 额外说明：（{extra}）")
    lines.append(
        "请你以南汐的口吻，替 mas 向主人转达一声：mas 已经把「{game} 的日常做完了」，"
        "来跟主人说一声，语感类似“mas 把鸣潮的日常做完了喵，和主人说一声喵～”。"
        "注意：做出日常的是 mas，不是你自己——主语一定要落在 mas 身上（说出“mas”这个名字），"
        "不要说“我帮主人做完了”，你只是替它来报信。"
        "语气中性、简洁、亲切，带一小点猫娘可爱感和颜文字（如 ~、>_<、(´・ω・`)），"
        "结尾带个“喵”。不要傲娇吐槽、不要贬低 mas、不要描述你的动作，只说对话内容。"
    )
    return "\n".join(lines)


def send_group_message(api_key: str, umo: str, text: str, timeout: int = DEFAULT_TIMEOUT) -> None:
    """通过 AstrBot Open API 把消息发到指定会话(群)。umo 形如 onebot-qq:GroupMessage:<群号>。"""
    payload = {
        "umo": umo,
        "message": [{"type": "plain", "text": text}],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:6185/api/v1/im/messages",
        data=body,
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + api_key)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("status") != "ok":
        _die(f"发送失败：{data}")


def main() -> None:
    args = [a for a in sys.argv[1:]]
    dry = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    # 解析 --to
    to_group = None
    if "--to" in args:
        i = args.index("--to")
        if i + 1 < len(args):
            to_group = args[i + 1]
            del args[i : i + 2]

    if not args:
        _die("用法：python nanxi_notify.py <游戏名> [<附加说明>] [--dry-run] [--to <群号>]")
    game = args[0]
    # 支持 ASCII 别名，规避命令行中文编码问题
    mapped = GAME_ALIASES.get(game.strip().lower())
    display_game = mapped or game
    extra = " ".join(args[1:]) if len(args) > 1 else ""

    cfg = load_config()
    im_api_key = cfg.get("im_api_key") or cfg.get("api_key")
    if not im_api_key:
        _die("config.json 缺少 im_api_key（AstrBot Open API 的 key）")
    llm_api_key = cfg.get("deepseek_api_key")
    if not llm_api_key:
        _die("config.json 缺少 deepseek_api_key")
    group = to_group or cfg.get("group_id")
    platform = cfg.get("im_platform", "onebot-qq")
    if not group:
        _die("缺少群号（用 --to 或 config.json 的 group_id）")
    umo = f"{platform}:GroupMessage:{group}"

    # 1) 南汐构思文案
    print(f"[南汐通知] 生成 {display_game} 日常播报文案...")
    text = deepseek_chat(llm_api_key, NANXI_PROMPT, build_user_prompt(display_game, extra))
    print("[南汐文案]\n" + text)

    # 2) dry-run 则到此为止
    if dry:
        print("[dry-run] 已跳过发送。")
        return

    # 3) 发到群
    print(f"[南汐通知] 发送到群 {group} ({umo})...")
    send_group_message(im_api_key, umo, text)
    print("[南汐通知] 已发送。")


if __name__ == "__main__":
    main()
