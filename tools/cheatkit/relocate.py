#!/usr/bin/env python3
"""Re-find the sites of recomp/patches-upd.txt after a game update.

A site names a module offset and the instruction word the build expects there. A game update relayouts main, so every
offset moves and the build stops at the first site whose word no longer matches. Finding them by hand is the part of
keeping a patch set that costs an evening; this does it by the code around each site.

For one site it reads a window of instructions from the build the offsets belong to. Every word that encodes a
PC-relative address (a branch, a literal load, adr/adrp) is compared with only its displacement ignored: that
displacement is the one thing a relayout changes, and its opcode is still worth matching. The window is then searched
for in the new build; a single hit is the site's new offset.

    # what the current build looks like, kept for the next update
    python tools/cheatkit/relocate.py --dump build/extracted/upd/exefs/main --write-image old/main.img

    # after a game update
    python tools/cheatkit/relocate.py --from old/main.img --to <new exefs>/main \
        --patches recomp/patches-upd.txt --report

    # write the moved offsets back (a .bak-<date> copy is kept)
    python tools/cheatkit/relocate.py --from old/main.img --to <new exefs>/main \
        --patches recomp/patches-upd.txt --write recomp/patches-upd-new.txt

A site that no longer resolves is reported and left alone: no offset is guessed. A host function reads fields of a game
object by offset (+0x14, +0x1e, ...), and those are not checked here, so a rebuilt set still wants a play test.
"""
import argparse
import random
import re
import struct
import sys
import time
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE_RE = re.compile(r'^(site\s+\S+\s+\S+\s+)([0-9a-fA-F]+)(\s+.*)$')
# The instructions whose low bits are a PC-relative displacement, and the bits to ignore: a relayout rewrites exactly
# these, so a window that matched them literally would never be found again.
PC_RELOC = (
    (0x7C000000, 0x14000000, 0x03FFFFFF),   # b, bl
    (0xFF000010, 0x54000000, 0x00FFFFE0),   # b.cond
    (0x7E000000, 0x34000000, 0x00FFFFE0),   # cbz, cbnz
    (0x7E000000, 0x36000000, 0x0007FFE0),   # tbz, tbnz
    (0x9F000000, 0x10000000, 0x60FFFFE0),   # adr
    (0x9F000000, 0x90000000, 0x60FFFFE0),   # adrp
    (0x3B000000, 0x18000000, 0x00FFFFE0),   # ldr, ldrsw, prfm (literal)
)
# Window halves tried in order: grow while the window is not unique, then shrink when nothing matched at all (a site
# whose neighbours changed often still resolves on a shorter window).
GROW = (8, 12, 16, 24, 32, 48)
SHRINK = (4, 2, 1, 0)


def imm_mask(w):
    for mask, value, ignore in PC_RELOC:
        if (w & mask) == value:
            return ignore
    return 0


class Image:
    """A flat image of one module: file offsets are the offsets a site names."""

    def __init__(self, data):
        self.raw = bytes(data)
        self.words = array('I')
        self.words.frombytes(self.raw[:len(self.raw) & ~3])
        if sys.byteorder == 'big':
            self.words.byteswap()
        self._by_word = {}

    def __len__(self):
        return len(self.words)

    def anchor_hits(self, value, mask):
        """Every word index whose instruction matches value on the bits mask leaves alone."""
        if mask == 0:
            key = (value, 0)
            if key not in self._by_word:
                needle = struct.pack('<I', value)
                start, hits = 0, []
                while len(hits) < (1 << 20):
                    i = self.raw.find(needle, start)
                    if i < 0:
                        break
                    if i % 4 == 0:
                        hits.append(i // 4)
                        start = i + 4
                    else:
                        start = i + 1
                self._by_word[key] = hits
            return self._by_word[key]
        key = (value & ~mask, mask)
        if key not in self._by_word:
            keep = ~mask & 0xFFFFFFFF
            want = value & keep
            self._by_word[key] = [i for i, w in enumerate(self.words) if (w & keep) == want]
        return self._by_word[key]


def load(path):
    raw = Path(path).read_bytes()
    if raw[:4] == b'NSO0':
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from recomp.nso import Nso
        return Image(Nso(str(path)).image)
    return Image(raw)


def read_text(path):
    """No newline translation: the file is rewritten as it was, so a CRLF patches file does not turn into a diff of
    every line."""
    with open(path, 'r', encoding='utf-8', newline='') as f:
        return f.read()


def write_text(path, text):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(text)


def read_sites(path):
    """(line number, set name, module, offset, original words) for every site line."""
    sites = []
    for n, line in enumerate(read_text(path).splitlines(), 1):
        m = SITE_RE.match(line)
        if not m:
            continue
        set_name, module, offset = line.split()[1:4]
        words = [int(w, 16) for w in line.split()[4:] if not w.startswith('#') and not w.startswith('@')]
        sites.append((n, set_name, module, int(offset, 16), words))
    return sites


def pattern(text, centre, half):
    """[(word delta, value, mask)] around centre, branch displacements masked."""
    pat = []
    for d in range(-half, half + 1):
        i = centre + d
        if 0 <= i < len(text):
            w = text.words[i]
            pat.append((d, w, imm_mask(w)))
    return pat


def hit_at(fresh, centre, pat):
    n = len(fresh)
    for d, value, mask in pat:
        i = centre + d
        if not 0 <= i < n:
            return False
        if (fresh.words[i] ^ value) & ~mask & 0xFFFFFFFF:
            return False
    return True


def locate(old, fresh, offset, words):
    """('OK' | 'MOVED' | 'WEAK' | 'AMBIGUOUS' | 'GONE', new offset, window, note)."""
    centre = offset // 4
    if centre >= len(old):
        return 'GONE', None, 0, 'not in the old image'
    anchor, anchor_mask = words[0], imm_mask(words[0])
    if (old.words[centre] ^ anchor) & ~anchor_mask & 0xFFFFFFFF:
        return 'GONE', None, 0, 'the old image does not hold this word'
    candidates = fresh.anchor_hits(anchor, anchor_mask)
    if not candidates:
        return 'GONE', None, 0, 'the instruction is gone'

    def try_half(half):
        pat = pattern(old, centre, half)
        hits = [c for c in candidates if hit_at(fresh, c, pat)]
        return pat, hits

    for half in GROW:
        pat, hits = try_half(half)
        if len(hits) == 1:
            return ('OK' if hits[0] == centre else 'MOVED'), hits[0] * 4, half, '1 hit'
        if not hits:
            break
    best = None
    for half in SHRINK:
        pat, hits = try_half(half)
        if len(hits) == 1:
            best = (hits[0] * 4, half)
            break
    if best:
        return ('WEAK' if best[1] < 4 else 'MOVED'), best[0], best[1], f'{best[1] * 2 + 1} words only'
    pat, hits = try_half(GROW[0])
    if len(hits) > 1:
        return 'AMBIGUOUS', None, GROW[0], f'{len(hits)} hits: ' + ', '.join(f'main+0x{h * 4:x}' for h in hits[:4])
    return 'GONE', None, GROW[0], 'no hit'


def run(old_path, new_path, patches, write, allow_weak, quiet=False):
    t0 = time.time()
    old, fresh = load(old_path), load(new_path)
    sites = read_sites(patches)
    lines = read_text(patches).split('\n')
    counts = {}
    rewrites = {}
    print(f'{patches}: {len(sites)} sites, old {len(old) * 4 / 1e6:.1f} MB, new {len(fresh) * 4 / 1e6:.1f} MB')
    for n, set_name, module, offset, words in sites:
        state, new_off, half, note = locate(old, fresh, offset, words)
        counts[state] = counts.get(state, 0) + 1
        target = new_off if new_off is not None else offset
        if state in ('GONE', 'AMBIGUOUS'):
            print(f'  {state:9s} {set_name:12s} main+0x{offset:x}  ({note})')
        elif target != offset:
            print(f'  {state:9s} {set_name:12s} main+0x{offset:x} -> main+0x{target:x}  ({note})')
        elif not quiet:
            print(f'  {state:9s} {set_name:12s} main+0x{offset:x}  ({note})')
        if state in ('OK', 'MOVED') or (state == 'WEAK' and allow_weak):
            if target != offset:
                m = SITE_RE.match(lines[n - 1])
                rewrites[n - 1] = m.group(1) + f'{target:x}' + m.group(3)
    if write:
        for i, text in rewrites.items():
            lines[i] = text
        out = Path(write)
        write_text(out, '\n'.join(lines))
        print(f'\nwrote {out}: {len(rewrites)} offsets updated')
    summary = ', '.join(f'{k} {v}' for k, v in sorted(counts.items()))
    print(f'{summary}  ({time.time() - t0:.1f} s)')
    return counts.get('GONE', 0) + counts.get('AMBIGUOUS', 0)


def dump_image(src, dst):
    img = load(src)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_bytes(img.raw)
    print(f'{dst}: {len(img) * 4 / 1e6:.1f} MB')


def selftest(old_path, patches):
    """Three checks on the scanner with one image: identity, a uniform shift, and a relayout of every branch."""
    old = load(old_path)
    sites = read_sites(patches)
    bad = 0

    moved = 0
    for n, set_name, module, offset, words in sites:
        state, new_off, half, note = locate(old, old, offset, words)
        if state != 'OK' or new_off != offset:
            print(f'  identity {set_name} main+0x{offset:x}: {state} {note}')
            bad += 1
        moved += 1
    print(f'identity: {moved} sites at their own offsets, {bad} wrong')

    shift = 0x1000
    shifted = Image(b'\0' * shift + old.raw)
    wrong = 0
    for n, set_name, module, offset, words in sites:
        state, new_off, half, note = locate(old, shifted, offset, words)
        if new_off != offset + shift or state not in ('MOVED', 'OK'):
            print(f'  shift {set_name} main+0x{offset:x}: {state} main+0x{(new_off or 0):x} {note}')
            wrong += 1
    print(f'shift +0x{shift:x}: {len(sites)} sites found {len(sites) - wrong} times at the shifted offset, {wrong} wrong')

    # A relayout changes every PC-relative displacement and nothing else: the masked window must still be unique.
    rng = random.Random(7)
    words = array('I', old.words)
    for i, w in enumerate(words):
        m = imm_mask(w)
        if m:
            words[i] = (w & ~m & 0xFFFFFFFF) | (rng.getrandbits(32) & m)
    relaid = Image(words.tobytes())
    wrong = 0
    for n, set_name, module, offset, input_words in sites:
        state, new_off, half, note = locate(old, relaid, offset, input_words)
        if state not in ('OK', 'MOVED') or new_off != offset:
            print(f'  relayout {set_name} main+0x{offset:x}: {state} main+0x{(new_off or 0):x} {note}')
            wrong += 1
    print(f'relayout (branches rewritten): {len(sites) - wrong}/{len(sites)} sites at the same offset')
    return bad + wrong


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--from', dest='old', help='the module the offsets in the patches file belong to (NSO or flat image)')
    ap.add_argument('--to', dest='new', help='the module of the new game build (NSO or flat image)')
    ap.add_argument('--patches', default=str(ROOT / 'recomp' / 'patches-upd.txt'))
    ap.add_argument('--report', action='store_true', help='only report (the default)')
    ap.add_argument('--write', help='write the patches file with the moved offsets')
    ap.add_argument('--allow-weak', action='store_true', help='also rewrite a site that only its own instruction found')
    ap.add_argument('--dump', help='write a flat image of this module (NSO in, .img out)')
    ap.add_argument('--write-image', help='with --dump: the file to write')
    ap.add_argument('--selftest', action='store_true', help='check the scanner on one image')
    args = ap.parse_args()
    if args.dump:
        if not args.write_image:
            ap.error('--dump needs --write-image')
        dump_image(args.dump, args.write_image)
        return 0
    if args.selftest:
        if not args.old:
            ap.error('--selftest needs --from')
        return 1 if selftest(args.old, args.patches) else 0
    if not args.old or not args.new:
        ap.error('give --from and --to (or --dump, or --selftest)')
    return 1 if run(args.old, args.new, args.patches, args.write, args.allow_weak) else 0


if __name__ == '__main__':
    sys.exit(main())
