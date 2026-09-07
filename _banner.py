"""Generate 3D banner as plain text + color map (avoid markup backslash bug).
Run: uv run python _banner.py"""
import pyfiglet

def banner_lines(text, font, shadow, main):
    art = pyfiglet.figlet_format(text, font=font)
    lines = [l.rstrip() for l in art.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    w = max(len(l) for l in lines)
    lines = [l.ljust(w) for l in lines]
    h = len(lines)
    # build rows: shadow offset down-right + main on top, gradient colors
    rows = []
    for i in range(h):
        shadow_line = lines[i - 1] if i >= 1 else " " * w
        sc = shadow[min(i - 1, len(shadow) - 1)] if i >= 1 else "black"
        mc = main[min(i, len(main) - 1)]
        main_line = lines[i]
        # produce list of (char, color)
        cells = []
        for c in range(w + 1):
            mchar = main_line[c] if c < w and main_line[c] != " " else None
            schar = shadow_line[c - 1] if 1 <= c <= w and shadow_line[c - 1] != " " else None
            if mchar is not None:
                cells.append((mchar, mc))
            elif schar is not None:
                cells.append((schar, sc))
            else:
                cells.append((" ", "black"))
        rows.append(cells)
    return rows

if __name__ == "__main__":
    sh = ["grey11", "grey15", "grey19", "grey23", "grey27", "grey30"]
    mn = ["bright_cyan", "cyan", "deep_sky_blue3", "dodger_blue3", "steel_blue3", "grey50"]
    for name, text, font in [("JULKAR", "Julkar.eth", "big"), ("BY", "By", "small")]:
        rows = banner_lines(text, font, sh, mn)
        print(f"# {name}")
        for row in rows:
            # emit as python literal list of (char,color) tuples
            print(repr(row))
        print()
