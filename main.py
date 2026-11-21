#!/usr/bin/env python3
"""DUNARA — a travel poster for a place that isn't there.

A lighthouse stands in the middle of a sand sea, and its beam is the
only light for a night's walk in any direction. This program draws
the whole poster from code — banded dusk sky, stars, a crescent
moon, layered dunes, the lighthouse and its beam, a camel caravan
crossing the foreground — and writes it to /output/entry.png.

Pure Python 3 standard library. No assets, no network, and fully
deterministic: the same bytes come out on every run.
"""

import math
import os
import struct
import zlib

# Final poster size; everything is drawn at SS times this and then
# box-downscaled, which anti-aliases the flat poster shapes.
W, H = 832, 1024
SS = 2
DW, DH = W * SS, H * SS


def write_png(path, w, h, rgb):
    """Write an RGB bytearray (w*h*3) as a PNG file, stdlib only."""
    stride = w * 3
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter type 0 (none) for every row
        raw += rgb[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        out += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return out

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)


class Canvas:
    """An RGB framebuffer with just enough drawing for a poster."""

    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.px = bytearray(w * h * 3)

    def set(self, x, y, colour, alpha=1.0):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            if alpha >= 1.0:
                self.px[i:i + 3] = bytes(colour)
            else:
                a = alpha
                self.px[i] = int(self.px[i] * (1 - a) + colour[0] * a)
                self.px[i + 1] = int(self.px[i + 1] * (1 - a) + colour[1] * a)
                self.px[i + 2] = int(self.px[i + 2] * (1 - a) + colour[2] * a)

    def fill_rect(self, x0, y0, x1, y1, colour, alpha=1.0):
        x0, x1 = max(0, int(x0)), min(self.w, int(x1))
        y0, y1 = max(0, int(y0)), min(self.h, int(y1))
        if x0 >= x1 or y0 >= y1:
            return
        row = bytes(colour) * (x1 - x0)
        if alpha >= 1.0:
            for y in range(y0, y1):
                i = (y * self.w + x0) * 3
                self.px[i:i + len(row)] = row
        else:
            for y in range(y0, y1):
                for x in range(x0, x1):
                    self.set(x, y, colour, alpha)

    def fill_poly(self, pts, colour, alpha=1.0):
        """Scanline even-odd fill of one or more closed contours.

        pts is a list of (x, y) vertices of a single contour; holes
        are drawn by filling the outer and inner contours in one
        call each with the background showing through — for this
        poster the parity trick is enough: pass all contours of a
        shape as one list of lists via fill_shape instead.
        """
        self.fill_shape([pts], colour, alpha)

    def fill_shape(self, contours, colour, alpha=1.0):
        edges = []
        for pts in contours:
            n = len(pts)
            for i in range(n):
                x0, y0 = pts[i]
                x1, y1 = pts[(i + 1) % n]
                if y0 != y1:
                    edges.append((x0, y0, x1, y1))
        if not edges:
            return
        ymin = int(min(min(e[1], e[3]) for e in edges))
        ymax = int(max(max(e[1], e[3]) for e in edges))
        ymin, ymax = max(0, ymin), min(self.h - 1, ymax)
        for y in range(ymin, ymax + 1):
            yc = y + 0.5
            xs = []
            for x0, y0, x1, y1 in edges:
                if (y0 <= yc < y1) or (y1 <= yc < y0):
                    xs.append(x0 + (yc - y0) * (x1 - x0) / (y1 - y0))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                xa, xb = int(xs[i]), int(xs[i + 1])
                self.fill_rect(xa, y, xb + 1, y + 1, colour, alpha)

    def disc(self, cx, cy, r, colour, alpha=1.0):
        r = int(r)
        for dy in range(-r, r + 1):
            dx = int(math.sqrt(max(0, r * r - dy * dy)))
            self.fill_rect(cx - dx, cy + dy, cx + dx + 1, cy + dy + 1,
                           colour, alpha)

    def thick_line(self, x0, y0, x1, y1, width, colour, alpha=1.0):
        """A line with round caps: a quad plus a disc at each end."""
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length == 0:
            self.disc(int(x0), int(y0), width / 2, colour, alpha)
            return
        nx, ny = -dy / length * width / 2, dx / length * width / 2
        quad = [(x0 + nx, y0 + ny), (x1 + nx, y1 + ny),
                (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)]
        self.fill_poly(quad, colour, alpha)
        self.disc(int(x0), int(y0), width / 2, colour, alpha)
        self.disc(int(x1), int(y1), width / 2, colour, alpha)

    def polyline(self, pts, width, colour, alpha=1.0):
        for i in range(len(pts) - 1):
            self.thick_line(pts[i][0], pts[i][1], pts[i + 1][0],
                            pts[i + 1][1], width, colour, alpha)


def downscale(cv, factor):
    """Box-average a Canvas by an integer factor."""
    w, h = cv.w // factor, cv.h // factor
    out = Canvas(w, h)
    sw, src = cv.w, cv.px
    n = factor * factor
    for y in range(h):
        for x in range(w):
            r = g = b = 0
            for dy in range(factor):
                base = ((y * factor + dy) * sw + x * factor) * 3
                for dx in range(factor):
                    i = base + dx * 3
                    r += src[i]
                    g += src[i + 1]
                    b += src[i + 2]
            j = (y * w + x) * 3
            out.px[j] = r // n
            out.px[j + 1] = g // n
            out.px[j + 2] = b // n
    return out


class Lcg:
    """A tiny deterministic pseudo-random generator (seeded)."""

    def __init__(self, seed):
        self.state = seed & 0x7FFFFFFF

    def next(self, lo, hi):
        self.state = (self.state * 1103515245 + 12345) & 0x7FFFFFFF
        return lo + (self.state / 0x7FFFFFFF) * (hi - lo)


# --- The poster's lettering -------------------------------------------------
# Capitals drawn as thick strokes on a 5-wide, 10-tall grid, in the
# hand-lettered manner of the old lithograph posters. Only the five
# letters of DUNARA are needed.

def _arc(cx, cy, r, a0, a1, steps=14):
    pts = []
    for i in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


GLYPHS = {
    "A": [[(0, 10), (2.5, 0), (5, 10)], [(1.3, 6), (3.7, 6)]],
    "D": [[(0, 0), (0, 10)],
          _arc(0, 5, 5, -90, 90)],
    "U": [[(0, 0), (0, 7.5)],
          _arc(2.5, 7.5, 2.5, 180, 0),
          [(5, 7.5), (5, 0)]],
    "N": [[(0, 10), (0, 0)], [(0.4, 0.8), (4.6, 9.2)],
          [(5, 10), (5, 0)]],
    "R": [[(0, 0), (0, 10)],
          _arc(0, 2.9, 2.9, -90, 90),
          [(2.0, 5.2), (5, 10)]],
}


def draw_name(cv, text, cx, top, unit, stroke, colour):
    """Draw text centred at cx, its cap-top at `top` (draw coords)."""
    advance = 5 + 1.7
    total = (len(text) * advance - 1.7) * unit
    x = cx - total / 2
    for ch in text:
        for stroke_pts in GLYPHS[ch]:
            pts = [(x + gx * unit, top + gy * unit)
                   for gx, gy in stroke_pts]
            cv.polyline(pts, stroke, colour)
        x += advance * unit


# --- The scene ---------------------------------------------------------------

CREAM = (246, 234, 205)
INK = (22, 15, 34)


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


SKY_STOPS = [(0.00, (16, 22, 54)), (0.42, (33, 49, 97)),
             (0.62, (84, 60, 106)), (0.78, (158, 84, 90)),
             (0.90, (236, 146, 82)), (1.00, (250, 198, 112))]


def sky(cv):
    """Banded dusk gradient — flat steps, like a lithograph."""
    bands = 30
    for i in range(bands):
        t = i / bands
        for j in range(len(SKY_STOPS) - 1):
            t0, c0 = SKY_STOPS[j]
            t1, c1 = SKY_STOPS[j + 1]
            if t0 <= t <= t1:
                colour = _lerp(c0, c1, (t - t0) / (t1 - t0))
                break
        else:
            colour = SKY_STOPS[-1][1]
        y0 = int(t * cv.h * 0.63)
        y1 = int((i + 1) / bands * cv.h * 0.63)
        cv.fill_rect(0, y0, cv.w, y1 + 2, colour)
    cv.fill_rect(0, int(cv.h * 0.63), cv.w, cv.h, SKY_STOPS[-1][1])


def stars(cv):
    rng = Lcg(20261121)
    for _ in range(260):
        x = rng.next(0, cv.w)
        y = rng.next(0, cv.h * 0.44)
        fade = 1 - y / (cv.h * 0.52)
        r = rng.next(1.2, 3.4)
        cv.disc(int(x), int(y), r, (250, 244, 224), 0.25 + 0.7 * fade)


def crescent(cv, cx, cy, r):
    pts = []
    for i in range(41):  # outer arc, the long way round the left
        a = math.radians(55 + 250 * i / 40)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    for i in range(41):  # inner arc back, centre pushed right
        a = math.radians(305 - 250 * i / 40)
        pts.append((cx + r * 0.42 + r * 0.82 * math.cos(a),
                    cy + r * 0.82 * math.sin(a)))
    cv.fill_poly(pts, (243, 231, 196))


def ridge(cv, base_y, amp, colour, seed):
    """A rolling silhouette: sine-bumped top edge, filled below."""
    pts = []
    rng = Lcg(seed)
    bumps = [(rng.next(0.5, 1.6), rng.next(0, 6.28)) for _ in range(3)]
    for x in range(0, cv.w + 33, 32):
        t = x / cv.w
        y = base_y + sum(a * math.sin(t * 6.28 * (k + 1) + p)
                         for k, (a, p) in enumerate(bumps)) * amp
        pts.append((x, y))
    pts += [(cv.w, cv.h), (0, cv.h)]
    cv.fill_poly(pts, colour)


def lighthouse(cv, cx):
    """The landmark: a banded tower on a dune knoll, lamp lit."""
    top = int(cv.h * 0.470)      # lamp floor
    base = int(cv.h * 0.718)     # where the tower meets the knoll
    hw_base, hw_top = 62, 42     # half-widths, draw pixels

    def hw(y):
        return hw_base + (hw_top - hw_base) * (y - base) / (top - base)

    # The beam first, so the tower stands in front of its own light.
    lamp_y = top - 26
    beam = [(cx + 10, lamp_y - 14), (cv.w, lamp_y - 210),
            (cv.w, lamp_y + 130), (cx + 10, lamp_y + 14)]
    cv.fill_poly(beam, (255, 214, 130), 0.24)
    core = [(cx + 10, lamp_y - 6), (cv.w, lamp_y - 120),
            (cv.w, lamp_y + 60), (cx + 10, lamp_y + 6)]
    cv.fill_poly(core, (255, 220, 145), 0.30)
    # A pool of lamplight lying flat on the dune below.
    pool = [(cx + 10 + 200 * math.cos(a), base + 34 + 36 * math.sin(a))
            for a in [2 * math.pi * i / 36 for i in range(37)]]
    cv.fill_poly(pool, (255, 205, 120), 0.10)
    # The knoll the tower stands on.
    knoll = [(cx - 210, base + 64)]
    for i in range(21):
        a = math.pi * i / 20
        knoll.append((cx - 210 * math.cos(a), base + 64 - 74 * math.sin(a)))
    knoll.append((cx + 210, base + 64))
    cv.fill_poly(knoll, (96, 44, 28))

    # Tower in stacked bands, cream and rust.
    bands = [(0.00, 0.30, (240, 226, 192)), (0.30, 0.44, (178, 58, 38)),
             (0.44, 0.72, (240, 226, 192)), (0.72, 0.86, (178, 58, 38)),
             (0.86, 1.00, (240, 226, 192))]
    for f0, f1, colour in bands:
        y0 = base + (top - base) * f0
        y1 = base + (top - base) * f1
        quad = [(cx - hw(y0), y0), (cx + hw(y0), y0),
                (cx + hw(y1), y1), (cx - hw(y1), y1)]
        cv.fill_poly(quad, colour)
    # Gallery, lamp room and cap.
    cv.fill_rect(cx - 52, top - 8, cx + 52, top + 4, (38, 28, 44))
    cv.fill_rect(cx - 34, top - 58, cx + 34, top - 8, (255, 196, 92))
    cv.fill_rect(cx - 4, top - 58, cx + 4, top - 8, (38, 28, 44))
    cv.disc(cx, lamp_y, 17, (255, 226, 140))
    cv.disc(cx, lamp_y, 34, (255, 214, 130), 0.45)
    roof = [(cx - 46, top - 58), (cx + 46, top - 58), (cx, top - 108)]
    cv.fill_poly(roof, (120, 40, 34))
    cv.disc(cx, top - 112, 7, (38, 28, 44))


def camel(cv, x, ground, s, colour):
    """One camel in silhouette; s = draw pixels per unit box."""
    def P(pts):
        return [(x + px * s, ground - (70 - py) * s) for px, py in pts]
    shapes = [
        [(17, 36), (23, 36), (23, 70), (17, 70)],          # legs
        [(29, 36), (35, 36), (35, 70), (29, 70)],
        [(61, 36), (67, 36), (67, 70), (61, 70)],
        [(73, 36), (79, 36), (79, 70), (73, 70)],
        [(12, 24), (26, 13), (38, 5), (52, 3), (63, 9),   # body + hump
         (76, 15), (87, 25), (85, 34), (70, 40), (28, 40),
         (14, 34)],
        [(76, 27), (85, 9), (93, 3), (99, 5), (95, 12),   # neck + head
         (91, 13), (88, 22), (84, 31)],
        [(12, 26), (6, 34), (8, 38), (14, 32)],           # tail
    ]
    for shape in shapes:
        cv.fill_poly(P(shape), colour)
    # A pack roll on the back.
    cv.fill_poly(P([(40, 2), (58, 0), (60, 8), (42, 10)]), colour)


def caravan(cv):
    ground = int(cv.h * 0.862)
    colour = (24, 13, 20)
    camel(cv, int(cv.w * 0.16), ground, 1.55, colour)
    camel(cv, int(cv.w * 0.335), ground + 10, 1.30, colour)
    camel(cv, int(cv.w * 0.475), ground + 18, 1.08, colour)
    # The walker ahead of the train, with a staff.
    wx, wy = int(cv.w * 0.115), ground + 2
    cv.disc(wx, wy - 96, 10, colour)
    cv.thick_line(wx, wy - 86, wx - 4, wy - 44, 13, colour)
    cv.thick_line(wx - 4, wy - 44, wx - 18, wy, 10, colour)
    cv.thick_line(wx - 4, wy - 44, wx + 14, wy - 2, 10, colour)
    cv.thick_line(wx + 16, wy - 92, wx + 22, wy - 6, 6, colour)


def build_poster():
    cv = Canvas(DW, DH)
    sky(cv)
    stars(cv)
    crescent(cv, int(DW * 0.90), int(DH * 0.085), 40)
    # Horizon glow strip, then ridge and dune layers.
    cv.fill_rect(0, int(DH * 0.585), DW, int(DH * 0.625),
                 (250, 196, 110), 0.35)
    ridge(cv, DH * 0.600, 7, (74, 44, 66), 7)
    ridge(cv, DH * 0.655, 12, (146, 74, 44), 21)
    ridge(cv, DH * 0.700, 12, (104, 47, 29), 33)
    lighthouse(cv, int(DW * 0.40))
    ridge(cv, DH * 0.800, 10, (122, 52, 30), 48)
    ridge(cv, DH * 0.872, 8, (74, 30, 20), 59)
    caravan(cv)
    # The name, with a print shadow, then the poster's frame.
    unit = 25
    draw_name(cv, "DUNARA", DW / 2 + 5, 92 + 7, unit, 38, (20, 16, 40))
    draw_name(cv, "DUNARA", DW / 2, 92, unit, 38, CREAM)
    cv.fill_rect(24, 24, DW - 24, 30, CREAM)
    cv.fill_rect(24, DH - 30, DW - 24, DH - 24, CREAM)
    cv.fill_rect(24, 24, 30, DH - 24, CREAM)
    cv.fill_rect(DW - 30, 24, DW - 24, DH - 24, CREAM)
    cv.fill_rect(46, 46, DW - 46, 49, CREAM)
    cv.fill_rect(46, DH - 49, DW - 46, DH - 46, CREAM)
    cv.fill_rect(46, 46, 49, DH - 46, CREAM)
    cv.fill_rect(DW - 49, 46, DW - 46, DH - 46, CREAM)
    return downscale(cv, SS)


def main():
    poster = build_poster()
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    write_png(os.path.join(out_dir, "entry.png"),
              poster.w, poster.h, poster.px)


if __name__ == "__main__":
    main()
