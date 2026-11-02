"""把头像转成 neofetch 风格的 ASCII 字符画（预览用，最终结果拷进 update_profile.py）。

用法: python3 ascii_avatar.py <图片> [列数] [字符集名]
渲染比例: SVG 里 font-size 13 / 行距 15，字符单元宽高比约 0.513，
所以 rows = cols * 0.513 时视觉上才是正圆。
"""
import sys
from PIL import Image, ImageEnhance, ImageOps

SETS = {
    "ref": " .:-=+*#%@",          # Dietrich 那套，亮=密
    "ink": "@%#*+=-:. ",          # 反转：暗=浓墨，像铅笔素描
    "soft": " .'`^\",:;Il!i",
    "block": " ░▒▓█",
}


def render(path, cols=52, charset="ref", contrast=1.0, gamma=1.0, crop=None, floor=0.0):
    img = Image.open(path).convert("L")
    if crop:
        img = img.crop(crop)
    img = ImageOps.fit(img, (cols, round(cols * 0.513)), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(contrast)

    chars = SETS[charset]
    n = len(chars) - 1
    px = img.load()
    w, h = img.size
    lines = []
    for y in range(h):
        row = []
        for x in range(w):
            v = (px[x, y] / 255) ** gamma
            if floor:  # 把亮背景压平，避免大面积空白
                v = max(0.0, (v - floor) / (1 - floor))
            row.append(chars[min(n, int(v * n + 0.5))])
        lines.append("".join(row).rstrip())
    return "\n".join(lines)


if __name__ == "__main__":
    p = sys.argv[1]
    c = int(sys.argv[2]) if len(sys.argv) > 2 else 52
    s = sys.argv[3] if len(sys.argv) > 3 else "ref"
    print(render(p, c, s))
