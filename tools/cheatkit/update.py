#!/usr/bin/env python3
"""Build xc3.exe with the cheat sets, moving them first if the game was updated.

One command for the whole loop:

    python tools/cheatkit/update.py --exefs "D:/games/Xenoblade Chronicles 3/exefs"

It hashes the ExeFS, notices when it is not the build the sites were last moved to, re-finds the sites with
relocate.py, generates the C, compiles, links and runs the self test. With --install it also replaces xc3.exe in the
game directory, keeping the previous one as xc3.exe.bak-<date>.

Two things it does not do, both on purpose:
- it does not pass --runtime-lib to build_game.py. That flag links a prebuilt runtime instead of this tree's, which
  drops every runtime change (the Cheats tab included) and is how a build once came out with no menu page at all.
- it does not claim the build is correct. A relocated site is the same instruction in a new place, but a host function
  reads fields of a game object by offset (a damage flag at +0x1e, a type at +0x5a); those move for reasons a code
  search cannot see. Play a fight, a shop and a rest spot before trusting an update.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / 'build' / 'cheatkit'            # the images the sites were last moved to, and the state that says which
EXEFS_FILES = ('main', 'main.npdm', 'rtld', 'sdk', 'subsdk0')
TOOLCHAIN = Path(os.environ.get('XC3_TOOLCHAIN', r'D:/games/_xc3-setup-0.2.18/XC3-Setup/llvm'))
DEPS = Path(os.environ.get('XC3_DEPS', r'D:/games/_xc3-setup-0.2.18/XC3-Setup/runtime/deps'))
NINJA = Path(os.environ.get('XC3_NINJA', r'D:/games/_xc3-setup-0.2.18/XC3-Setup/bin/ninja.exe'))
PYTHON = sys.executable


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def exefs_hashes(exefs):
    return {name: sha256(exefs / name) for name in EXEFS_FILES if (exefs / name).is_file()}


def state_path():
    return KIT / 'state.json'


def load_state():
    p = state_path()
    if p.is_file():
        return json.loads(p.read_text(encoding='utf-8'))
    return None


def save_state(hashes, image):
    KIT.mkdir(parents=True, exist_ok=True)
    write_text(state_path(), json.dumps({'exefs_sha256': hashes, 'image': str(image),
                                         'moved': time.strftime('%Y-%m-%d %H:%M')}, indent=2))


def write_text(path, text):
    """Windows refuses to replace a file a scanner has open for a moment; a retry is cheaper than a mystery."""
    for i in range(40):
        try:
            Path(path).write_text(text, encoding='utf-8')
            return
        except PermissionError:
            if i == 39:
                raise
            time.sleep(0.25)


def expected_json(hashes, out, old_expected):
    """The ExeFS hashes the build checks, with the RomFS block carried over from the previous expected file. A RomFS
    hash cannot be recomputed in a minute (15 GB), and the build only warns on it."""
    romfs, title = {'size': 0, 'sha256': '0' * 64}, ''
    if old_expected.is_file():
        old = json.loads(old_expected.read_text(encoding='utf-8'))
        romfs, title = old.get('romfs', romfs), old.get('title_id', '')
    out.parent.mkdir(parents=True, exist_ok=True)
    write_text(out, json.dumps({'exefs_sha256': hashes, 'romfs': romfs, 'title_id': title}, indent=2))
    return out

def run(cmd, **kw):
    print('>', ' '.join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], **kw)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--exefs', type=Path, default=Path(r'D:/games/Xenoblade Chronicles 3/exefs'))
    ap.add_argument('--romfs', type=Path, default=Path(r'D:/games/Xenoblade Chronicles 3/romfs'))
    ap.add_argument('--patches', type=Path, default=ROOT / 'recomp' / 'patches-upd.txt')
    ap.add_argument('--version', default='upd')
    ap.add_argument('--gen', type=Path, default=ROOT / 'generated' / 'upd')
    ap.add_argument('--out', type=Path, default=ROOT / 'build' / 'upd')
    ap.add_argument('--expected', type=Path, default=KIT / 'expected.json')
    ap.add_argument('--adopt', action='store_true',
                    help='the first run: take the current ExeFS as the build the sites belong to, move nothing')
    ap.add_argument('--install', action='store_true', help='copy xc3.exe into the game directory, keeping the old one')
    ap.add_argument('--boot', action='store_true', help='with --install: start the game after the build')
    args = ap.parse_args()

    t0 = time.time()
    hashes = exefs_hashes(args.exefs)
    if 'main' not in hashes:
        sys.exit(f'{args.exefs}: no main')
    tag = hashes['main'][:12]
    image = KIT / f'main-{tag}.img'
    state = load_state()
    KIT.mkdir(parents=True, exist_ok=True)

    if state is None:
        if not args.adopt:
            sys.exit(f'{state_path()} is missing: run once with --adopt to take this ExeFS as the build the sites '
                     f'belong to')
        run([PYTHON, Path(__file__).with_name('relocate.py'), '--dump', args.exefs / 'main',
             '--write-image', image])
        save_state(hashes, image)
        print(f'adopted {tag}; the sites belong to this build now')
    elif state['exefs_sha256'].get('main') != hashes['main']:
        print(f'main changed: {state["exefs_sha256"].get("main", "?")[:12]} -> {tag}: moving the sites')
        if not image.is_file():
            run([PYTHON, Path(__file__).with_name('relocate.py'), '--dump', args.exefs / 'main',
                 '--write-image', image])
        backup = args.patches.with_suffix(f'.txt.bak-{Path(state["image"]).stem}')
        shutil.copy2(args.patches, backup)
        r = run([PYTHON, Path(__file__).with_name('relocate.py'),
                 '--from', state['image'], '--to', args.exefs / 'main',
                 '--patches', backup, '--write', args.patches])
        if r.returncode:
            shutil.copy2(backup, args.patches)
            sys.exit(f'relocation did not resolve every site; {args.patches} left as it was, {backup} kept')
        save_state(hashes, image)
        print(f'sites moved to {tag}; previous patches kept as {backup.name}')
    else:
        print(f'main {tag}: the sites belong to this build, nothing to move')

    expected = expected_json(hashes, args.expected, ROOT / 'tools' / 'data' / 'expected-xc3-2.2.1.json')
    print(f'expected hashes: {expected}')

    r = run([PYTHON, ROOT / 'recomp' / 'gen.py', '--exefs', args.exefs, '--out', args.gen,
             '--patches', args.patches])
    if r.returncode:
        sys.exit('gen.py failed: the patches file does not fit this build')
    r = run([PYTHON, ROOT / 'tools' / 'build_game.py', '--version', args.version,
             '--expected', expected, '--exefs', args.exefs, '--romfs', args.romfs,
             '--gen', args.gen, '--out', args.out,
             '--toolchain', TOOLCHAIN, '--deps', DEPS, '--ninja', NINJA])
    if r.returncode:
        sys.exit('build_game.py failed')

    exe = args.out / ('xc3.exe' if os.name == 'nt' else 'xc3')
    # The build links SDL3 and Opus as DLLs and expects them beside xc3.exe; the game directory is the copy that is
    # known to match this executable, and a missing one makes --selftest exit 127 with no message at all.
    if os.name == 'nt':
        for name in ('SDL3.dll', 'libopus-0.dll', 'libiconv-2.dll', 'libc++.dll', 'libunwind.dll',
                     'libwinpthread-1.dll'):
            src = args.exefs.parent / name
            if src.is_file():
                shutil.copy2(src, exe.parent / name)
    st = subprocess.run([str(exe), '--selftest'], cwd=str(exe.parent), capture_output=True, text=True, timeout=900)
    text = (st.stdout or '') + (st.stderr or '')
    ok = st.returncode == 0 and 'selftest: passed' in text
    print(f'selftest: {"passed" if ok else "FAILED"} (exit {st.returncode})')
    if not ok:
        print('\n'.join(text.strip().splitlines()[-8:]))
        sys.exit('selftest did not pass')

    if args.install:
        game = args.exefs.parent
        target = game / ('xc3.exe' if os.name == 'nt' else 'xc3')
        if target.is_file():
            keep = target.with_suffix(target.suffix + time.strftime('.bak-%Y%m%d-%H%M'))
            shutil.copy2(target, keep)
            print(f'kept {keep.name}')
        shutil.copy2(exe, target)
        print(f'installed {target} ({sha256(target)[:16]})')
        if args.boot:
            subprocess.Popen([str(target)], cwd=str(game))

    print(f'done in {time.time() - t0:.0f} s')
    return 0


if __name__ == '__main__':
    sys.exit(main())
