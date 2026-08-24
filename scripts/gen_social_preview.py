#!/usr/bin/env python3
"""生成 GitHub Social Preview 1280x640：深蓝底 + 世界地图点阵 + 标题 + 截图"""
import math, random, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1280, 640
BG_TOP, BG_BOT = (10, 18, 38), (16, 32, 64)
BLUE = (59, 130, 246)
CYAN = (34, 211, 238)
WHITE = (240, 246, 252)
GREY = (148, 163, 184)

def font(size, bold=False):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else ""),
              "/usr/share/fonts/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else "")]:
        try: return ImageFont.truetype(p, size)
        except OSError: continue
    return ImageFont.load_default()

# ---- 背景：垂直渐变 + 网格 ----
img = Image.new("RGB", (W, H))
d = ImageDraw.Draw(img)
for y in range(H):
    t = y / H
    d.line([(0, y), (W, y)], fill=tuple(int(a+(b-a)*t) for a, b in zip(BG_TOP, BG_BOT)))
GRID = (32, 48, 82)   # 比背景略亮的网格色（RGB 无 alpha，直接混色）
for x in range(0, W, 64):
    d.line([(x, 0), (x, H)], fill=GRID, width=1)
for y in range(0, H, 64):
    d.line([(0, y), (W, y)], fill=GRID, width=1)

# ---- 世界地图点阵（等距圆柱投影，压在左下装饰区，避开文字）----
sys.path.insert(0, ".")
from src.mapdata import COUNTRY_COORDS
random.seed(42)
MX0, MY0, MW, MH = 56, 380, 560, 220   # 地图区域
dots = []
for code, info in COUNTRY_COORDS.items():
    lat, lng = info["lat"], info["lng"]
    x = int((lng + 180) / 360 * MW) + MX0
    y = int((85 - lat) / 170 * MH) + MY0
    dots.append((x, y))
    for _ in range(6):   # 少量撒点模拟点阵大陆
        dots.append((x + random.randint(-10, 10), y + random.randint(-6, 6)))
for (x, y) in dots:
    if MX0-8 <= x <= MX0+MW+8 and MY0-8 <= y <= MY0+MH+8:
        d.ellipse([x-1, y-1, x+2, y+2], fill=(62, 96, 170))
# 少量发光枢纽 + 淡连线
hubs = [dots[i] for i in (2, 9, 18, 27, 36, 45, 54, 63) if i < len(dots)]
for i in range(0, len(hubs)-1, 2):
    x1, y1, x2, y2 = *hubs[i], *hubs[i+1]
    if abs(x1-x2) < 300:
        d.line([(x1, y1), (x2, y2)], fill=(48, 84, 150), width=1)
for (x, y) in hubs:
    glow = Image.new("RGBA", (28, 28), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([6, 6, 22, 22], fill=CYAN + (170,))
    glow = glow.filter(ImageFilter.GaussianBlur(3))
    img.paste(glow, (x-14, y-14), glow)

# ---- 左侧文案 ----
# Logo 波浪
lx, ly = 64, 88
d.rounded_rectangle([lx, ly, lx+72, ly+72], radius=18, fill=BLUE)
wd = ImageDraw.Draw(img)
for k, off in enumerate((-10, 0, 10)):
    wd.arc([lx+14, ly+22+off, lx+58, ly+52+off], start=200, end=340, fill=WHITE, width=5)
d.text((lx+92, ly+2), "Sanl", font=font(72, True), fill=WHITE)
d.text((lx+94, ly+84), "Free Proxy Node Aggregator", font=font(26), fill=CYAN)
d.text((lx+2, ly+150),
       "Aggregate  ·  Real Speed Test  ·  Subscribe",
       font=font(22), fill=GREY)
d.text((lx+2, ly+184),
       "Clash / V2Ray / Sing-box  |  mihomo kernel  |  MIT",
       font=font(22), fill=GREY)

# 特性小徽章
badges = ["15+ sources", "12 protocols", "0-100 score", "PWA app"]
bx = lx
for b in badges:
    f = font(18)
    w = d.textlength(b, font=f)
    d.rounded_rectangle([bx, ly+236, bx+w+24, ly+268], radius=14, outline=BLUE, width=2)
    d.text((bx+12, ly+242), b, font=f, fill=WHITE)
    bx += w + 36

# ---- 右侧截图卡片（带圆角+描边）----
shot = Image.open("docs/screenshots/dashboard.png").convert("RGB")
sw, sh = 560, 350
shot = shot.resize((sw, sh), Image.LANCZOS)
mask = Image.new("L", (sw, sh), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, sw, sh], radius=16, fill=255)
px, py = 668, 170
img.paste(shot, (px, py), mask)
d.rounded_rectangle([px, py, px+sw, py+sh], radius=16, outline=(90, 140, 220), width=3)
# 卡片投影
shadow = Image.new("RGBA", (sw+40, sh+40), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle([20, 20, sw+20, sh+20], radius=16, fill=(0, 0, 0, 110))
shadow = shadow.filter(ImageFilter.GaussianBlur(10))
img.paste(shadow, (px-20+6, py-20+10), shadow)
# 重画描边（投影覆盖后）
d.rounded_rectangle([px, py, px+sw, py+sh], radius=16, outline=(90, 140, 220), width=3)

img.save(".github/social-preview.png", optimize=True)
print("saved .github/social-preview.png", img.size)
