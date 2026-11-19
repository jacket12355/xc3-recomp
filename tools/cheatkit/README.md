# cheatkit

Two scripts for living with the cheat sets in `recomp/patches-upd.txt` across game updates.

A site names a module offset and the instruction word expected there. A game update relayouts `main`, so every offset
moves and the build stops at the first site whose word no longer matches. `relocate.py` finds them again by the code
around each site; `update.py` runs the whole loop in one command.

## One time, before the game updates

The sites are found by comparing against the build they were written for, so that build has to be kept:

```sh
python tools/cheatkit/update.py --adopt
```

It dumps the ExeFS `main` of the game you have to `build/cheatkit/main-<sha>.img`, records its hashes in
`build/cheatkit/state.json`, then builds as usual. **Do this while the version you play is the version the patches
fit.** Run it again after any update you did not plan for, and the reference is the new build, which is the same as
having no reference at all.

`build/` is not in the repository, so a fresh clone needs `--adopt` on the version it is meant to build.

## After a game update

```sh
python tools/cheatkit/update.py --install
```

1. hashes the new ExeFS and compares with `state.json`;
2. moves every site with `relocate.py`, keeping the old `patches-upd.txt` as `.bak-main-<sha>`;
3. writes the expected hashes to `build/cheatkit/expected.json` (the RomFS hash is carried over from
   `tools/data/expected-xc3-2.2.1.json`: it cannot be recomputed in a minute and the build only warns on it);
4. runs `recomp/gen.py`, then `tools/build_game.py`, then `xc3.exe --selftest`;
5. with `--install`, replaces `xc3.exe` in the game directory, keeping the old one as `xc3.exe.bak-<date>`.

If any site does not resolve, the patches file is left untouched and the build stops: a site is never guessed. The
report says which ones and why (`GONE`, `AMBIGUOUS`, or `WEAK` for a site only its own instruction found).

## What the two scripts do not check

A relocated site is the same instruction in a new place. What a host function does with it is not checked: it reads
fields of a game object by offset — the damage flags at `+0x1e` and `+0x5a`, the class icon fill at `+8`, the arts
gauge at `+0x10` — and those move when a struct grows, for reasons a code search cannot see. A build that relocates
cleanly can still be wrong in game. After an update, play a fight (damage rate, damage taken), a shop (money, Nopon
coins), a rest spot (level change) and one art-heavy fight (arts gauge, cooldown) before trusting it.

## Checking the scanner itself

```sh
python tools/cheatkit/relocate.py --selftest --from build/cheatkit/main-<sha>.img
```

Three checks on one image: every site is found at its own offset; every site is found `+0x1000` away after the image
is shifted by that much; and every site is found at the same offset after every PC-relative displacement in the image
is randomised, which is what a relayout does to them. The last two are the cases a game update puts the scanner in.

## How a site is found

The window of instructions around it: 8 each way, grown to 48 while the match is not unique, then shrunk to 4, 2, 1
when nothing matched at all (a site whose neighbours changed often still resolves on its own instruction, and is
reported `WEAK`). Branch, literal-load and `adr`/`adrp` words are compared with the displacement bits masked, since
those bits are the one thing a relayout rewrites; the opcode still has to match.
