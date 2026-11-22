# Cheats

The settings menu's Cheats tab switches a set of code patches while the game runs. This page says where those patches
come from, how a row changes one, and what a site cannot do.

## Why the codes are not loaded at run time

The game is a static recompilation: its ARM64 code is lifted to C and compiled to x86-64 at install time, so the
addresses and instruction words a cheat table holds are gone by the time the game runs. A table's code
(`040E0000 <offset> <instruction word>`) has nothing to write into.

The same effect comes from the build instead. `recomp/patches-upd.txt` names the instruction to replace, and the
generator writes both paths into the C it emits: the replacement instructions while the set is on, the original ones
while it is off. A site is therefore decided per call, not once at start, and a row can flip it while the game runs.

## Where the codes come from

The codes are taken from the 2.2.0 cheat table of Sodamyte and Eiffel2018 for Ryujinx (build id `82D187FE9EF9BE92`,
the same `main` this tree lifts). No code is copied: each site re-derives the table's hook as a build-time patch, and
where the table's injection branches on a flag, the host function here makes the same test.

## The patch set

A set is one switch, one row of the page, and one `xc3.ini` key:

```
set money XC3_CHEAT_MONEY 0
site money main a86f60 b938c668 d503201f
site money main 2fa728 2a0103f5 2a1f03f5
```

`set <name> <cfg key> <default>` names the set and the setting the menu writes. `site <set> <module> <offset>
<original word> <replacement words…>` names one instruction. The original word is checked against the game's code
when the generator runs: a mismatch stops the build, which is what keeps a site from silently patching something else
after a game update.

The replacement is a sequence of instructions, and may also carry two markers:

- `@page:xN` puts the patch page's address in `xN` for the instructions after it, so a replacement can read or write
  the page's words (`RT_PATCH_PAGE`, one 4 KiB page the runtime commits at `runtime/patches.c`).
- `@call:fXX` calls the host function registered at that page offset (`rt_register_host`), for the cases an
  instruction sequence cannot express: a conditional the page's rows choose, a value the runtime has to look up, an
  effect that depends on input.

`runtime/patches.c` reads every set's cfg row once a frame (`rt_patch_sync`, called from the menu's layout) and sets
the switch the sites read. A row therefore needs no restart, and `xc3.ini` keeps the choice between runs: the menu
writes it like any other setting, and the environment (`XC3_CHEAT_MAP=1`, say) overrides it.

## The page

The Cheats tab has one row per set, in five groups: Movement, Battle, Progress, Items, World. A toggle is on while its
`xc3.ini` key is not 0; a rate row (`speed_x`, `cheat_dmg_x`, `cheat_exp_x`, …) multiplies what its cheat does. The
first row of the page, *Turn every cheat off*, sets every switch back to 0 and the damage share back to 100 %, leaving
the rates as they are.

| Row | `xc3.ini` key | What it does |
| --- | --- | --- |
| Hold Y: faster movement | `speed_mult`, `speed_x` | While Y is held, the character moves `speed_x` times as fast. |
| Hold B: moon jump | `moon_jump` | While B is held, a fall turns upward instead of landing. |
| Damage multiplier | `cheat_dmg`, `cheat_dmg_x` | Damage the party's attacks deal is made `cheat_dmg_x` times. |
| Damage taken | `cheat_dmg_taken` | Share of the damage the party takes, in percent: 100 % is as the game ships, 25 % takes a quarter. |
| Fall damage 1 | `cheat_fall_dmg` | Fall damage is 1. |
| Chain attack gauge full | `cheat_chain` | The chain attack gauge is drawn and read as full. |
| Arts gauge full | `cheat_arts_gauge` | Every art's gauge, the Talent Art's and the three party arts', reads full, and the art itself is set to it, so it can be used and not only drawn as ready. |
| No art cooldown | `cheat_no_cooldown` | A used art's gauge is left as it was, so the art is ready again at once. |
| XP | `cheat_exp`, `cheat_exp_x` | The XP an award gives is made `cheat_exp_x` times. |
| SP | `cheat_sp` | The SP a gain gives is 5 times. A skill learned still costs what it says: the row scales a gain, not a spend. |
| Affinity | `cheat_affinity` | The affinity points a task gives are 5 times. |
| Class rank | `cheat_class_rank`, `cheat_class_rank_x` | The class rank a gain gives is made `cheat_class_rank_x` times. |
| Class icon | `cheat_class_icon`, `cheat_class_icon_x` | The class icon's fill is made `cheat_class_icon_x` times. |
| Class ascension | `cheat_class_asc` | The class rank cap is 20 whether the ascension has been done or not. |
| Unlock every class | `cheat_class_unlock` | A class icon the party is filling fills in one go at the next battle, so every class the party has met unlocks. The fill loop walks the character's own class list, so a class of a hero the party has not met is not on it and stays locked. |
| Soul Hack | `cheat_soulhack` | Every Soul Hack art and skill slot reads as complete. |
| Class icon fix | `cheat_fix_class` | The loops that fill class icon slots walk past a filled slot instead of ending on it (the cheat file labels this a fix, not a cheat). |
| Ignore level difference | `cheat_ignore_lv` | The XP path compares the party's level with itself, so a low party fights high enemies at full XP. |
| Money | `cheat_money` | The purse keeps its value when something is bought; every deduction path spends nothing. |
| Nopon coins 999 | `cheat_coins` | A Nopon coin counts 999 wherever it is read, and a purchase never lowers the purse. |
| Item gain | `cheat_items` | The items, coins, ether or money a source gives are 5 times. |
| Meal timer | `cheat_meal`, `cheat_meal_x` | A meal's timer runs `cheat_meal_x` times as long, from the next meal on: the time of the meal being eaten is written when it is taken. |
| Pickup distance | `cheat_pickup`, `cheat_pickup_x` | Items are picked up from `cheat_pickup_x` times the distance. |
| Quests need no items | `cheat_quests` | No quest asks for its items: the item test is dropped and the count it returns is 99. |
| Any level at a rest spot | `cheat_any_lv` | The rest spot's level change is allowed at any level, up to 99. |
| Whole map open | `cheat_map` | A region's map-open test reads as known. |
| Unique monsters alive | `cheat_unique_mon` | A unique monster's alive flag reads as 1, so a defeated one comes back. |
| Every art and skill | `cheat_arts` | The walks of the arts and skills a character has reach every entry, not only the learned ones. |

The damage rows share one site: `main+0x1d9638` and `main+0x1d963c` serve the damage the party deals and the damage it
takes, and the host decides which of the two a call is from the same two flags the cheat file tests.

## Adding a cheat

1. Find the instruction and check it against the game's code (`main` at the update's `exefs`), the way a cheat table's
   offsets are found.
2. Write the `set` and the `site` lines in `recomp/patches-upd.txt`, above the section of the group it belongs to,
   with a comment saying what the original instruction computed and where the numbers come from.
3. Add the set's row to `runtime/cfg.c` (`{key, default, values, live}`) so the menu can write it and the environment
   can override it.
4. Add the row's label and description to `runtime/ui_text.h` and `runtime/ui_text.c`, and the row itself to
   `tab_cheats` in `runtime/ui/menu.cpp`.
5. Build and run `xc3.exe --selftest`, then check the effect in game with the row on and off.

A cheat whose switch is a rate only needs the slider and the `cfg_double` read in `runtime/patches.c`; a cheat that
needs a decision the instructions cannot make gets a host function and a `@call`.

## Limits of a site

- **A branch cannot be the replaced instruction.** `site` refuses a `b`, `b.cond`, `cbz` or `cbnz`. Two ways around it:
  patch the compare before the branch so the condition never holds (`cmp w9, w8` becomes `cmp w9, w9`), or change a
  value the branch already tests so the path it takes is the wanted one (`mov w1, #0` in place of a `ret`, where the
  instructions after it test the argument).
- **A multi-word replacement runs in place of the original and the code continues with the instructions after it.** It
  does not overwrite them, and the off path restores only the first word. A replacement therefore has to leave the
  registers the following instructions read as the original left them.
- **Both paths have to affect the flags the same way.** The generator checks this: a replacement cannot use `cmp` or
  `subs` where the original did not.
- **A host sees only the registers the lifted C keeps in `Cpu`.** Many are C locals (a site's `else` branch shows
  which: `c->x[N]` is a register, a plain `xN` is a local). A value in a local can be handed to a host by writing it
  into the patch page first (`str wN, [x10, #0xe04]` after `@page:x10`), and a value a host computes can come back the
  same way.

## What is not ported

Four rows of the community cheat file for 2.2.0 (Sodamyte and Eiffel2018) are not in this change: Ouroboros heat, quest
locking, Art of Flow and Colony Iota. None of them has a row in the menu, so nothing here is offered that does not
work; the addresses in that file are for this `main` (build id `82D187FE9EF9BE92`), so porting them is the same work as
the rows above.
