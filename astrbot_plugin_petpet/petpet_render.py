# -*- coding: utf-8 -*-
"""petpet 摸头杀渲染器 —— 用 Pillow 复刻 toolwa.com/petpet（B1gM8c/Petpet 网页版）算法。

网页版 `main.js` 里的关键常量（本文件逐项对应）：

    MAX_FRAME = 4                 # 一共 5 帧（0..4）
    OUT_SIZE  = 112               # 输出画布固定 112x112
    squish = 1.25, scale = 0.875  # 挤压程度 / 尺寸
    delay  = 60                   # 帧间隔（毫秒）
    spriteX = 14, spriteY = 20, spriteWidth = 112
    frameOffsets = [(0,0,0,0), (-4,12,4,-12), (-12,18,12,-18), (-8,12,4,-12), (-4,0,0,0)]

渲染逻辑（与网页版一致）：
  1. 被摸的图（sprite）按 sprite_w 等比缩放，再按 squish/scale 逐帧做位移与挤压；
  2. 手（hand）来自一张横向精灵图，每帧 OUT_SIZE 宽，叠在最后；
  3. 输出 112x112、5 帧的透明 GIF。

与网页版的差别只有一处（`auto_fit`）：网页版固定按宽度缩放到 112，横图会被压成一条，
这里让横图改为按高度撑满画布并水平居中；方图和竖图保持网页版原逻辑（竖图正好框住头顶）。

素材：`assets/hand.png`（560x112，5 帧手，来自网页版 img/sprite.png）。
本模块只依赖 Pillow，不依赖 AstrBot —— 方便单独命令行调试。
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path
from typing import Iterable, Sequence, Union

from PIL import Image

# ---------------------------------------------------------------- 常量（对齐网页版）

OUT_SIZE = 112
FRAME_COUNT = 5
FRAME_OFFSETS: Sequence[tuple[int, int, int, int]] = (
    (0, 0, 0, 0),
    (-4, 12, 4, -12),
    (-12, 18, 12, -18),
    (-8, 12, 4, -12),
    (-4, 0, 0, 0),
)

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
HAND_PATH = ASSETS_DIR / "hand.png"

DEFAULTS = {
    "squish": 1.25,
    "scale": 0.875,
    "sprite_x": 14,
    "sprite_y": 20,
    "sprite_w": 112,
    "flip": False,
    "delay": 60,
    "auto_fit": True,
}

ImageLike = Union[str, Path, bytes, bytearray, Image.Image]


def _js_trunc(value: float) -> int:
    """对应 JS 的 `~~x`：向零截断。"""
    return int(value)


def _open(source: ImageLike) -> Image.Image:
    """把 path / bytes / Image 统一转成 RGBA Image。"""
    if isinstance(source, Image.Image):
        return source.convert("RGBA")
    if isinstance(source, (bytes, bytearray)):
        return Image.open(io.BytesIO(source)).convert("RGBA")
    return Image.open(source).convert("RGBA")


def load_hand(path: Path | None = None) -> Image.Image:
    """载入手部精灵图（560x112，5 帧横排）。"""
    hand = _open(path or HAND_PATH)
    expected = OUT_SIZE * FRAME_COUNT
    if hand.width < expected:
        raise ValueError(f"手部精灵图宽度应为 {expected}px，实际 {hand.width}px：{path or HAND_PATH}")
    return hand


def render_frames(
    source: ImageLike,
    *,
    squish: float = DEFAULTS["squish"],
    scale: float = DEFAULTS["scale"],
    sprite_x: float = DEFAULTS["sprite_x"],
    sprite_y: float = DEFAULTS["sprite_y"],
    sprite_w: float = DEFAULTS["sprite_w"],
    flip: bool = DEFAULTS["flip"],
    auto_fit: bool = DEFAULTS["auto_fit"],
    hand: Image.Image | None = None,
) -> list[Image.Image]:
    """渲染出 5 帧 RGBA 图（112x112）。

    Args:
        source: 被摸的图，可为文件路径、bytes 或 PIL Image。
        squish: 挤压程度，网页版默认 1.25。
        scale: 整体尺寸系数，网页版默认 0.875。
        sprite_x: 被摸的图左上角横向基准位置。
        sprite_y: 被摸的图左上角纵向基准位置。
        sprite_w: 被摸的图缩放后的宽度基准。
        flip: 是否水平翻转。
        auto_fit: 横图是否按高度撑满画布并居中（避免被压成一条）。
        hand: 手部精灵图，None 时读 assets/hand.png。

    Returns:
        5 张 112x112 的 RGBA 图，按帧顺序排列。
    """
    face_src = _open(source)
    hand_img = hand if hand is not None else load_hand()

    # 自动适配（仅横图）：按高度撑满画布，多出来的宽度左右均分，
    # 这样脸仍在画布中央，而不是只露出左半边。
    x_shift = 0.0
    if auto_fit and face_src.width > face_src.height:
        ratio = face_src.width / face_src.height
        x_shift = (sprite_w - sprite_w * ratio) * scale / 2
        sprite_w = sprite_w * ratio

    # 网页版：spriteHeight = spriteWidth * (naturalHeight / naturalWidth)
    sprite_h = sprite_w * (face_src.height / face_src.width)

    frames: list[Image.Image] = []
    for index, (ox, oy, ow, oh) in enumerate(FRAME_OFFSETS):
        dx = _js_trunc(sprite_x + x_shift + ox * (squish * 0.4))
        dy = _js_trunc(sprite_y + oy * (squish * 0.9))
        dw = _js_trunc((sprite_w + ow * squish) * scale)
        dh = _js_trunc((sprite_h + oh * squish) * scale)

        canvas = Image.new("RGBA", (OUT_SIZE, OUT_SIZE), (0, 0, 0, 0))

        # 1) 被摸的图
        face = face_src.resize((max(1, abs(dw)), max(1, abs(dh))), Image.Resampling.LANCZOS)
        if flip:
            face = face.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        canvas.paste(face, (dx, dy))  # paste 自带越界裁剪

        # 2) 手（叠在最上层）
        hand_frame = hand_img.crop((index * OUT_SIZE, 0, (index + 1) * OUT_SIZE, OUT_SIZE))
        hand_dy = max(0, _js_trunc(dy * 0.75 - max(0, sprite_y) - 0.5))
        if hand_dy < OUT_SIZE:
            patch = hand_frame.crop((0, 0, OUT_SIZE, OUT_SIZE - hand_dy))
            canvas.alpha_composite(patch, (0, hand_dy))

        frames.append(canvas)
    return frames


def _to_palette(frame: Image.Image) -> Image.Image:
    """RGBA -> P，并把透明像素固定到索引 255（透明色），避免 GIF 出现黑边/白边。"""
    alpha = frame.getchannel("A")
    paletted = frame.convert("RGB").convert("P", palette=Image.Palette.ADAPTIVE, colors=255)
    transparent_mask = alpha.point(lambda a: 255 if a < 128 else 0)
    paletted.paste(255, transparent_mask)
    return paletted


def make_gif(
    source: ImageLike,
    out_path: str | Path,
    *,
    delay: int = DEFAULTS["delay"],
    loop: int = 0,
    **kwargs,
) -> Path:
    """生成摸头 GIF 并写入 out_path，返回该路径。

    Args:
        source: 被摸的图。
        out_path: 输出 GIF 路径。
        delay: 帧间隔（毫秒）。
        loop: 循环次数，0 表示无限循环。
        **kwargs: 其余参数透传给 render_frames。

    Returns:
        实际写入的 GIF 路径。
    """
    frames = render_frames(source, **kwargs)
    paletted: Iterable[Image.Image] = [_to_palette(f) for f in frames]

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    first, *rest = list(paletted)
    first.save(
        out,
        save_all=True,
        append_images=rest,
        duration=delay,
        loop=loop,
        transparency=255,
        disposal=2,
        optimize=False,
    )
    return out


def make_preview_png(source: ImageLike, out_path: str | Path, frame: int = 0, **kwargs) -> Path:
    """导出某一帧的 PNG（方便肉眼检查效果）。"""
    frames = render_frames(source, **kwargs)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[frame % len(frames)].save(out)
    return out


# ---------------------------------------------------------------- 命令行调试入口

def _main() -> None:
    parser = argparse.ArgumentParser(description="petpet 摸头杀渲染器")
    parser.add_argument("source", help="被摸的图片路径")
    parser.add_argument("output", help="输出 GIF 路径")
    parser.add_argument("--squish", type=float, default=DEFAULTS["squish"], help="挤压程度（默认 1.25）")
    parser.add_argument("--scale", type=float, default=DEFAULTS["scale"], help="尺寸（默认 0.875）")
    parser.add_argument("--sprite-x", type=float, default=DEFAULTS["sprite_x"])
    parser.add_argument("--sprite-y", type=float, default=DEFAULTS["sprite_y"])
    parser.add_argument("--sprite-w", type=float, default=DEFAULTS["sprite_w"])
    parser.add_argument("--delay", type=int, default=DEFAULTS["delay"], help="帧间隔毫秒（默认 60）")
    parser.add_argument("--flip", action="store_true", help="水平翻转")
    parser.add_argument("--no-auto-fit", action="store_true", help="关闭横图自动适配（回到网页版原逻辑）")
    parser.add_argument("--preview", metavar="PNG", help="额外导出第 0 帧 PNG")
    args = parser.parse_args()

    opts = dict(
        squish=args.squish,
        scale=args.scale,
        sprite_x=args.sprite_x,
        sprite_y=args.sprite_y,
        sprite_w=args.sprite_w,
        flip=args.flip,
        auto_fit=not args.no_auto_fit,
    )
    out = make_gif(args.source, args.output, delay=args.delay, **opts)
    size_kb = out.stat().st_size / 1024
    print(f"OK {out}  ({size_kb:.1f} KB)")
    if args.preview:
        print(f"OK {make_preview_png(args.source, args.preview, **opts)}")


if __name__ == "__main__":
    _main()
