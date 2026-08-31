# -*- coding: utf-8 -*-
import random
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont, ImageFilter

BASE = '/Users/congjiang/With/20260831/wlbv'
orig = Image.open(f'{BASE}/assets/original.png').convert('RGB')
W, H = orig.size
arr = np.array(orig)

# ---------- color sampling ----------
def darkest(region):
    x0, y0, x1, y1 = region
    r = arr[y0:y1, x0:x1].reshape(-1, 3).astype(int)
    idx = r.sum(axis=1).argmin()
    return tuple(r[idx])

def median_color(region, exclude_pink=False):
    x0, y0, x1, y1 = region
    r = arr[y0:y1, x0:x1].reshape(-1, 3).astype(int)
    if exclude_pink:
        mask = (r[:, 0] - r[:, 1]) < 40
        r = r[mask]
    return tuple(np.median(r, axis=0).astype(int))

BROWN = darkest((335, 1145, 500, 1180))
PINK = None
reg = arr[2060:2105, 455:545].reshape(-1, 3).astype(int)
PINK = tuple(reg[(reg[:, 0] - reg[:, 1]).argmax()])
OLIVE = darkest((215, 1460, 560, 1495))
WELCOME = darkest((100, 1535, 740, 1580))
CREAM = median_color((250, 1115, 590, 1135))
LOCBG = median_color((600, 1400, 720, 1440))
CAPSULE = median_color((445, 2055, 553, 2108), exclude_pink=True)
STUB = median_color((720, 2300, 790, 2350))
print('brown', BROWN, 'pink', PINK, 'olive', OLIVE, 'welcome', WELCOME)
print('cream', CREAM, 'locbg', LOCBG, 'capsule', CAPSULE, 'stub', STUB)

# ---------- inpaint old couple + welcome text ----------
mask = np.zeros((H, W), np.uint8)
mask[508:1012, 232:630] = 255      # old couple
mask[1525:1648, 55:800] = 255      # welcome text lines
inpainted = cv2.inpaint(arr[:, :, ::-1], mask, 5, cv2.INPAINT_TELEA)
img = Image.fromarray(inpainted[:, :, ::-1])

# ---------- cut out new couple (color-distance keying) ----------
cp = cv2.imread(f'{BASE}/assets/couple-noglasses.png').astype(np.float32)
h2, w2 = cp.shape[:2]
border = np.concatenate([cp[:, :6].reshape(-1, 3), cp[:, -6:].reshape(-1, 3)])
row_bg = np.zeros((h2, 3), np.float32)
for y in range(h2):
    row_bg[y] = np.median(np.concatenate([cp[y, :6], cp[y, -6:]]), axis=0)
dist = np.linalg.norm(cp - row_bg[:, None, :], axis=2)
fg = (dist > 32).astype(np.uint8) * 255
fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
n, labels, stats, _ = cv2.connectedComponentsWithStats(fg)
if n > 1:
    largest = 1 + stats[1:, cv2.CC_STAT_AREA].argmax()
    fg = (labels == largest).astype(np.uint8) * 255
inv = cv2.bitwise_not(fg)
ffm = np.zeros((h2 + 2, w2 + 2), np.uint8)
cv2.floodFill(inv, ffm, (0, 0), 0)
fg = cv2.bitwise_or(fg, inv)
fg = cv2.erode(fg, np.ones((3, 3), np.uint8))
fg = cv2.GaussianBlur(fg, (5, 5), 0)
couple = Image.open(f'{BASE}/assets/couple-noglasses.png').convert('RGBA')
alpha = Image.fromarray(fg)
couple.putalpha(alpha)
bbox = alpha.getbbox()
couple = couple.crop(bbox)
scale = 505.0 / couple.height
couple = couple.resize((int(couple.width * scale), 505), Image.LANCZOS)
cx, baseline = 424, 1004
img.paste(couple, (cx - couple.width // 2, baseline - couple.height), couple)

# ---------- fonts ----------
HIRA = '/System/Library/Fonts/Hiragino Sans GB.ttc'
def cf(size, bold=True):
    try:
        return ImageFont.truetype(HIRA, size, index=1 if bold else 0)
    except Exception:
        return ImageFont.truetype(HIRA, size)
NUMF = '/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf'

def draw_spaced(d, center, text, font, fill, spacing=0, colors=None):
    widths = [d.textlength(ch, font=font) for ch in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x = center[0] - total / 2
    asc, desc = font.getmetrics()
    y = center[1] - (asc + desc) / 2
    for i, ch in enumerate(text):
        c = colors.get(i, fill) if colors else fill
        d.text((x, y), ch, font=font, fill=c)
        x += widths[i] + spacing

def draw_left(d, pos, text, font, fill, spacing=0):
    x = pos[0]
    asc, desc = font.getmetrics()
    y = pos[1] - (asc + desc) / 2
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + spacing

d = ImageDraw.Draw(img)
brown = tuple(BROWN); pink = tuple(PINK); olive = tuple(OLIVE); welc = tuple(WELCOME)

# time card: title -> 吃席时间
d.rounded_rectangle([300, 1128, 545, 1194], 8, fill=tuple(CREAM))
draw_spaced(d, (421, 1161), '吃席时间', cf(34), brown, spacing=10)
# time card: sub line -> 星期二 · 下午 3:00
d.rounded_rectangle([235, 1256, 605, 1318], 8, fill=tuple(CREAM))
sub = '星期二 · 下午 3:00'
draw_spaced(d, (421, 1286), sub, cf(30), brown, spacing=2,
            colors={4: pink})

# location card
d.rounded_rectangle([205, 1398, 730, 1502], 8, fill=tuple(LOCBG))
draw_left(d, (215, 1424), '恒葱直撞岛 · 王者峡谷花园前', cf(31), brown, spacing=1)
draw_left(d, (215, 1477), '贵州省安顺市平坝区 · 颐家园小区', cf(24), olive, spacing=1)

# welcome text (3 lines)
lines = ['哎呀！今天是个好日子，欢迎我亲爱的朋友们',
         '不远千里来参加我的婚礼宴席，',
         '希望大家都能吃好喝好玩好～']
for i, ln in enumerate(lines):
    draw_spaced(d, (421, 1550 + i * 46), ln, cf(27), welc, spacing=2)

img.save(f'{BASE}/assets/base.png')
print('base saved')

# ---------- 16 fixed lucky numbers ----------
codes = [1807, 1901, 1903, 2001, 2011, 2104, 2112, 2202,
         2303, 2312, 2405, 2412, 2504, 2510, 2606, 2610]
import os
outdir = f'{BASE}/邀请函成品'
os.makedirs(outdir, exist_ok=True)
capf = ImageFont.truetype(NUMF, 40)
stubf = ImageFont.truetype(NUMF, 58)
for i, code in enumerate(codes, 1):
    t = img.copy()
    dd = ImageDraw.Draw(t)
    num = f'{code:04d}'
    dd.rectangle([388, 2054, 560, 2110], fill=tuple(CAPSULE))
    nof = ImageFont.truetype(NUMF, 32)
    dd.text((395, 2082 - 21), 'NO.', font=nof, fill=(150, 138, 112))
    draw_left(dd, (455, 2082), num, capf, pink, spacing=4)
    dd.rectangle([528, 2293, 722, 2364], fill=tuple(STUB))
    draw_spaced(dd, (623, 2328), num, stubf, pink, spacing=8)
    t.save(f'{outdir}/婚礼邀请函_{i:02d}_NO{num}.png')
print('codes:', [f'{c:04d}' for c in codes])
print('done')
