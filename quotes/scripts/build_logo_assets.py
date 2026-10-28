"""把用户提供的 COMAU logo 转为可用于深色界面的透明蒙版资源。"""
from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path(
    r"c:\Users\sunly\AppData\Roaming\Trae CN\User\workspaceStorage"
    r"\e7a1bd388620a899930780b2e24e55e8\paste-files"
    r"\1a27a4e8-9fe0-47ad-8924-1784cdd154f5_image.png"
)
OUT = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "assets"
OUT.mkdir(parents=True, exist_ok=True)


def to_mask(img: Image.Image) -> Image.Image:
    """用蓝通道与红通道之差作为蒙版：白底、灰阶水印都会被剔除。"""
    arr = np.array(img.convert("RGB")).astype(np.float32)
    diff = arr[:, :, 2] - arr[:, :, 0]
    alpha = np.clip((diff - 12) * 5.0, 0, 255)
    rgba = np.zeros((*alpha.shape, 4), dtype=np.uint8)
    rgba[:, :, :3] = 255
    rgba[:, :, 3] = alpha.astype(np.uint8)
    return Image.fromarray(rgba)


def main() -> None:
    img = Image.open(SRC)
    # 去掉原图四周的灰色边框
    pad = 4
    img = img.crop((pad, pad, img.width - pad, img.height - pad))
    mask = to_mask(img)

    bbox = mask.split()[3].point(lambda v: 255 if v > 40 else 0).getbbox()
    mask = mask.crop(bbox)
    w, h = mask.size

    # 竖向拆成 C 标与 COMAU 字标：在空白行带中选择最宽的一段作为分界
    rows = np.array(mask.split()[3]).mean(axis=1)
    blank = rows < 2
    bands, start = [], None
    for i, is_blank in enumerate(blank):
        if is_blank and start is None:
            start = i
        elif not is_blank and start is not None:
            bands.append((start, i))
            start = None
    if start is not None:
        bands.append((start, len(blank)))
    middle = [b for b in bands if h * 0.45 < (b[0] + b[1]) / 2 < h * 0.9]
    split = (max(middle, key=lambda b: b[1] - b[0])[0] + max(middle, key=lambda b: b[1] - b[0])[1]) // 2 if middle else int(h * 0.7)
    mark = mask.crop((0, 0, w, split))
    word = mask.crop((0, split, w, h))

    mark = mark.crop(mark.split()[3].point(lambda v: 255 if v > 40 else 0).getbbox())
    word = word.crop(word.split()[3].point(lambda v: 255 if v > 40 else 0).getbbox())

    mark.save(OUT / "logo-mark.png")
    word.save(OUT / "logo-word.png")

    icon = mark.copy()
    icon.thumbnail((128, 128), Image.LANCZOS)
    canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    canvas.alpha_composite(icon, ((128 - icon.width) // 2, (128 - icon.height) // 2))
    canvas.save(OUT / "favicon.png")

    print("mark", mark.size, "word", word.size)


if __name__ == "__main__":
    main()
