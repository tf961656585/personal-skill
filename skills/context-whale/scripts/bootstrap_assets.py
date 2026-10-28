#!/usr/bin/env python3
"""Regenerate context-whale whale-girl assets with iart.

Default is a dry check. `--run` submits the generations and rebuilds:
  hero-bento.jpg, avatar.png, icon-*.png
Requires IARTStudio to be running and the `鲸鱼娘专用` project to exist.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
ASSETS = os.path.join(SKILL_DIR, "assets")
MANIFEST = os.path.join(ASSETS, "manifest.json")
MODEL = "gpt-image-2.5-flare"
GROUP = "上下文鲸鱼娘·拆分素材"
REF_BENTO = "1b4965bb11438748"
REF_CHIBI = "07476e7ddda2a556"

CHAR = ("chibi deep-sea whale-girl maid, super-deformed proportions (about 2.5 heads tall), "
        "large head and small body, long wavy blue hair with cyan-to-navy gradient, one curled ahoge, "
        "whale fin ears, star-shaped hair clips, big glossy blue eyes, small :3 mouth, navy maid dress "
        "with white puffed sleeves, white frilled apron with a blue whale embroidery, white frilled "
        "headdress with blue ribbon")

HERO_PROMPT = (
    "A warm hand-painted gouache illustration for the hero of a cozy dashboard. A wooden Japanese "
    "bento box seen from a slight top-down angle on a cream paper desk, five compartments filled with "
    "symbolic objects: rolled paper scrolls and tiny brass wrenches, fluffy translucent clouds, rolled "
    "blueprint cards, a stack of tiny books, and one glowing pearl. " + CHAR + " peeks over the top edge "
    "of the bento with a curious smile, only head and hands visible. Soft watercolor washes, delicate "
    "ink outlines, warm cream paper, navy/coral/mint/butter palette, cozy Japanese picture-book, "
    "generous empty space, no text, no letters, no numbers, no UI, no watermark."
)

SHEET_PROMPT = (
    "A clean 3x2 grid of five watercolor icons on a plain warm cream paper background, each icon "
    "centered in its own square cell, one cell left empty, no grid lines, no text, no labels. Icons: "
    "top-left a rolled paper scroll with a tiny brass wrench; top-middle a fluffy translucent cloud; "
    "top-right a rolled blueprint card tied with twine; bottom-left a small stack of three books; "
    "bottom-middle a single glowing pearl on a tiny cushion; bottom-right empty. Style: soft watercolor "
    "and gouache, delicate brown ink outlines, consistent scale, warm cream/navy/coral/mint/butter "
    "palette, generous padding inside each cell, no shadows, no watermark."
)


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def iart_json(args):
    proc = run(["iart"] + args)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "iart failed").strip()[:500])
    try:
        return json.loads(proc.stdout)
    except Exception:
        raise RuntimeError("iart returned non-JSON: " + (proc.stdout or "")[:300])


def find_project():
    data = iart_json(["project", "list", "--json"])
    for p in data.get("projects", []):
        if p.get("name") == "鲸鱼娘专用":
            return p
    for p in data.get("projects", []):
        if "鲸鱼娘" in (p.get("name") or ""):
            return p
    raise RuntimeError("找不到 `鲸鱼娘专用` 项目。先用 iart project list 确认。")


def asset_state():
    required = ["hero-bento.jpg", "avatar.png", "icon-tools.png", "icon-reason.png",
                "icon-defs.png", "icon-skills.png", "icon-pearl.png"]
    return {name: os.path.exists(os.path.join(ASSETS, name)) for name in required}


def generate(project, prompt, refs, size):
    cmd = ["iart", "generate", "--project", project, "--prompt", prompt, "--model", MODEL]
    for ref in refs:
        cmd += ["--ref", ref]
    cmd += ["--arg", "size=" + size, "--arg", "quality=high", "--arg", "format=png",
            "--group", GROUP, "--wait", "--json"]
    data = iart_json(cmd)
    for tr in data.get("task_results", []):
        if tr.get("task", {}).get("status") == "succeeded":
            assets = tr.get("assets") or []
            if assets:
                return assets[0].get("local_file_path"), assets[0].get("asset", {}).get("assetId")
    raise RuntimeError("iart generation did not return a succeeded asset: " +
                       json.dumps(data, ensure_ascii=False)[:500])


def key_out(img, lo=10, hi=34):
    img = img.convert("RGBA")
    px = img.load()
    w, h = img.size
    samples = []
    for x in range(w):
        for y in (0, h - 1):
            samples.append(px[x, y][:3])
    for y in range(h):
        for x in (0, w - 1):
            samples.append(px[x, y][:3])
    samples.sort()
    bg = samples[len(samples) // 2]
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            d = ((r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2) ** 0.5
            if d <= lo:
                al = 0
            elif d >= hi:
                al = 255
            else:
                al = int((d - lo) / (hi - lo) * 255)
            px[x, y] = (r, g, b, min(a, al))
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    w, h = img.size
    s = max(w, h)
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    canvas.paste(img, ((s - w) // 2, (s - h) // 2), img)
    return canvas


def rebuild_assets(hero_path, sheet_path, manifest):
    # hero jpg
    hero = Image.open(hero_path).convert("RGB")
    hero.thumbnail((1400, 1400))
    hero.save(os.path.join(ASSETS, "hero-bento.jpg"), quality=90, optimize=True)
    # avatar crop from the same hero (keeps pose/expression identical)
    full = Image.open(hero_path).convert("RGB")
    av = full.crop((590, 0, 1160, 570))
    av.thumbnail((256, 256))
    av.save(os.path.join(ASSETS, "avatar.png"), optimize=True)
    # icon sheet crops
    sh = Image.open(sheet_path).convert("RGB")
    W, H = sh.size
    cw, ch = W // 3, H // 2
    cells = [
        ("icon-tools.png", 0, 0), ("icon-reason.png", 1, 0), ("icon-defs.png", 2, 0),
        ("icon-skills.png", 0, 1), ("icon-pearl.png", 1, 1),
    ]
    for name, cx, cy in cells:
        cell = sh.crop((cx * cw, cy * ch, (cx + 1) * cw, (cy + 1) * ch))
        key_out(cell).save(os.path.join(ASSETS, name), optimize=True)
    manifest["assets"]["hero"]["file"] = "hero-bento.jpg"
    manifest["assets"]["avatar"]["source"] = "crop of hero-bento"
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="actually submit iart generation")
    parser.add_argument("--project", default=None, help="project path or name")
    args = parser.parse_args()

    state = asset_state()
    missing = [k for k, v in state.items() if not v]
    print("assets:", "ok" if not missing else "missing " + ", ".join(missing))
    if not args.run:
        if missing:
            print("\n要重新生成，运行：")
            print("  python3 %s --run" % os.path.abspath(__file__))
        else:
            print("素材齐全。需要重画时加 --run（会覆盖现有 assets/）。")
        return 0

    if not shutil.which("iart"):
        print("iart 命令不存在。请先在 IARTStudio 里注册命令行工具。", file=sys.stderr)
        return 1
    try:
        project = args.project or find_project().get("path")
        print("project:", project)
        if not project:
            raise RuntimeError("project path is empty")
        hero_path, hero_id = generate(project, HERO_PROMPT, [REF_BENTO, REF_CHIBI], "1536x1024")
        print("hero:", hero_path, hero_id)
        sheet_path, sheet_id = generate(project, SHEET_PROMPT, [REF_BENTO], "1536x1024")
        print("icon sheet:", sheet_path, sheet_id)
        manifest = json.load(open(MANIFEST, encoding="utf-8"))
        manifest["assets"]["hero"]["asset_id"] = hero_id
        manifest["assets"]["icon_sheet"]["asset_id"] = sheet_id
        rebuild_assets(hero_path, sheet_path, manifest)
        print("rebuilt assets in", ASSETS)
        return 0
    except Exception as e:
        print("bootstrap failed:", e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
