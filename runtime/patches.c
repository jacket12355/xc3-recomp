// Code patch sets (recomp/patches.py, gen.py --patches). The generator lifts both the original and the replacement
// instructions of every patched site, and rt_patch_on[set] picks one when the site runs, so a set is switched at start
// without touching code, and also while the game runs (rt_patch_switch: the frame-limit setting of the menu). The sets,
// their environment switches and defaults, and the patch page come from the generated patches.h; without it (C
// generated without --patches) there are no sets and every site runs the original.
//
// The patch page is the first 4 KiB page after main's image, inside the module window memory.c reserved: replacement
// code reaches it with one adrp, as MacNativeGames' data page after main (games/totk/runtime/game_patches.c). Its
// layout belongs to the sets that use it (frame_rate.c: +0 the 30 Hz ratio, +4 the frame step in seconds, +8 the
// step in 60 Hz ticks).
// Probe modes never call rt_patches_init: every set stays off.
#include "cfg.h"
#include "platform/platform.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "host.h"
#include "input.h"

#if __has_include("patches.h")
#include "patches.h"
#endif
#ifndef RT_PATCH_COUNT
#define RT_PATCH_COUNT 0
#endif

uint8_t rt_patch_on[RT_PATCH_COUNT > 0 ? RT_PATCH_COUNT : 1];   // read by the generated C at every patched site

#if RT_PATCH_COUNT
static const struct { const char *name, *env; int on; } sets[] = {
#define X(i, n, e, d) {#n, e, d},
    RT_PATCH_SETS(X)
#undef X
};
static void *page;
#endif

// ---- cheats (patches-upd.txt: the speed and moonjump sets). Each site calls one of these host functions in place of
// the instruction it replaced, and each does what that instruction did with the cheat's change on top. The buttons are
// the pad's, the keyboard included (input.h: Y = bit 3, B = bit 1), sampled at most once every 2 ms so a site that runs
// for many objects costs one poll.
#if RT_PATCH_COUNT
#define HOST_SPEED (RT_PATCH_PAGE + 0xf30)
#define HOST_MOON (RT_PATCH_PAGE + 0xf40)
// the ported cheat table (below): one host function per site that needs more than a constant
#define HOST_ARTS_GAUGE (RT_PATCH_PAGE + 0xf50)
#define HOST_NO_COOLDOWN (RT_PATCH_PAGE + 0xf60)
#define HOST_MEAL (RT_PATCH_PAGE + 0xf70)
#define HOST_PICKUP (RT_PATCH_PAGE + 0xf80)
#define HOST_XP (RT_PATCH_PAGE + 0xf90)
#define HOST_CLASS_RANK (RT_PATCH_PAGE + 0xfa0)
#define HOST_CLASS_ICON (RT_PATCH_PAGE + 0xfb0)
#define HOST_SLOT (RT_PATCH_PAGE + 0xfc0)
#define HOST_DMG (RT_PATCH_PAGE + 0xfd0)
// 0xfe0 and 0xff0 belong to ov_zstd.c (HOST_USING_DDICT, HOST_MULTIFRAME), so this one sits in the free slot
// after the two words the damage host keeps at 0xe00.
#define HOST_COINS (RT_PATCH_PAGE + 0xe10)

static float speed_x = 3.0f;   // XC3_SPEED_X: the multiplier while Y is held
// The rates of the ported cheat table's rows that have one. sets_from_cfg refreshes them when a setting changed, so a
// site reads a plain global: no cfg parse on the path a frame runs many times.
static float exp_x = 2.0f, class_rank_x = 2.0f, class_icon_x = 2.0f;
static float pickup_x = 3.0f, meal_x = 3.0f, dmg_x = 2.0f, dmg_taken = 100.0f;
static int on_soulhack, on_dmg;   // the rows the always-on soul hack and damage sites serve
static unsigned cfg_seen;      // the cfg_version the sets were last taken from

// A Cheats row (and XC3_MENU_TEST_SET) changes a set's setting through cfg_set. Taking every set that has a cfg row from
// there means a new cheat needs only its cfg row and its row on the page, with no rt_patch_switch call to remember. One
// atomic load per poll; the loop runs only when a setting changed.
static void sets_from_cfg(void) {
    unsigned v = cfg_version();
    if (v == cfg_seen) return;
    cfg_seen = v;
    for (int i = 0; i < RT_PATCH_COUNT; i++)
        if (cfg_meta(sets[i].env)) rt_patch_on[i] = (uint8_t)cfg_bool(sets[i].env);
    speed_x = (float)cfg_double("XC3_SPEED_X");
    exp_x = (float)cfg_double("XC3_CHEAT_EXP_X");
    class_rank_x = (float)cfg_double("XC3_CHEAT_CLASS_RANK_X");
    class_icon_x = (float)cfg_double("XC3_CHEAT_CLASS_ICON_X");
    pickup_x = (float)cfg_double("XC3_CHEAT_PICKUP_X");
    meal_x = (float)cfg_double("XC3_CHEAT_MEAL_X");
    dmg_x = (float)cfg_double("XC3_CHEAT_DMG_X");
    dmg_taken = (float)cfg_double("XC3_CHEAT_DMG_TAKEN");
    int sh = rt_patch_set("soulhack"), dm = rt_patch_set("dmgdeal");
    on_soulhack = sh >= 0 ? rt_patch_on[sh] : 0;
    on_dmg = dm >= 0 ? rt_patch_on[dm] : 0;
}

static uint64_t pad_buttons(void) {
    static uint64_t at, buttons;
    uint64_t now = kern_now_ns();
    if (now - at >= 2000000ull) {
        int32_t lx = 0, ly = 0, rx = 0, ry = 0;
        at = now;
        input_poll(&buttons, &lx, &ly, &rx, &ry);
        sets_from_cfg();
    }
    return buttons;
}

// main+0xb44dac was fmul s1, s1, s8: the speed the move computes times its own factor. Y held multiplies by speed_x.
static void host_speed(Cpu *c) {
    float s1, s8;
    memcpy(&s1, &c->v[1], sizeof s1);
    memcpy(&s8, &c->v[8], sizeof s8);
    s1 = s1 * s8 * ((pad_buttons() & 8u) ? speed_x : 1.0f);
    memcpy(&c->v[1], &s1, sizeof s1);
}

// main+0xb47d8c was st1 {v0.s}[2], [x8], inside the fall of a character: the site serves every character, so it looks
// the one the player controls up as the cheat does (the object at [x19+0x10] -> [x0+0x10], whose low 12 bits are 0xda8)
// and, while B is held and the fall's speed at [sp+0x34] is downward, makes it upward instead.
static void host_moon(Cpu *c) {
    if (pad_buttons() & 2u) {
        uint64_t a = *(const uint64_t *)(uintptr_t)(c->x[19] + 0x10);
        if (a) {
            uint64_t b = *(const uint64_t *)(uintptr_t)(a + 0x10);
            if (b && (*(const uint64_t *)(uintptr_t)b & 0xfffull) == 0xda8) {
                float *speed = (float *)(uintptr_t)(c->sp + 0x34);
                if (*speed < 0.0f) *speed = 0.4f;
            }
        }
    }
    *(uint32_t *)(uintptr_t)c->x[8] = (uint32_t)(c->v[0] >> 64);
}

// ---- The ported cheat table's sites that need more than a constant. Each does what the instruction it replaced did,
// with the cheat on top: a rate from a Cheats row, or a value the cheat fixes.
static float vs_get(const Cpu *c, int i) { float f; memcpy(&f, &c->v[i], sizeof f); return f; }
static void vs_set(Cpu *c, int i, float f) { memcpy(&c->v[i], &f, sizeof f); }

// the float at addr times k, in place
static void mul_at(uint64_t addr, float k) {
    float f;
    memcpy(&f, (const void *)(uintptr_t)addr, sizeof f);
    f *= k;
    memcpy((void *)(uintptr_t)addr, &f, sizeof f);
}

// [12] main+0x237e18 was ldr s0, [x23, #0x10], the arts gauge. The loads after it copy that value into the widget at
// x25, which is what the bar draws, so setting only s0 lights the bar and nothing else: a Talent Art reads the gauge
// from the object itself and still finds it empty. The original cheat's injection did the same two steps
// (fmov s0, #1.0; str s0, [x23, #0x10]), so this writes the source as well.
static void host_arts_gauge(Cpu *c) {
    vs_set(c, 0, 1.0f);
    if (c->x[23] > 0x10000) *(float *)(uintptr_t)(c->x[23] + 0x10) = 1.0f;
}

// [11] main+0x1947a8 was str s8, [x19, #0x10], the gauge a used art is given back. The cheat table's injection skips
// this store for the party's art objects (type 0xbc0, read the way its injection reads it), so an art that was full
// stays full instead of going back to empty; every other object gets the value the store would have written. The value
// is s8, which lives in Cpu with every other vector register.
static void host_no_cooldown(Cpu *c) {
    uint64_t obj = c->x[19];
    if (obj > 0x10000) {
        uint64_t vt = *(const uint64_t *)(uintptr_t)obj;
        if (vt > 0x10000) {
            uint64_t p = *(const uint64_t *)(uintptr_t)(vt - 0x28);
            if (p > 0x10000 && (*(const uint32_t *)(uintptr_t)p & 0xfffu) == 0xbc0) return;
        }
        *(uint32_t *)(uintptr_t)(obj + 0x10) = (uint32_t)c->v[8];
    }
}

// [20] main+0x30a7a8 was ucvtf s0, w8: a meal's effect timer times the rate.
static void host_meal(Cpu *c) { vs_set(c, 0, (float)(uint32_t)c->x[8] * meal_x); }

// [7] main+0xb22244 was ldr s8, [x21, #0xa70]: the distance items are picked up from, times the rate.
static void host_pickup(Cpu *c) { vs_set(c, 8, *(const float *)(uintptr_t)(c->x[21] + 0xa70) * pickup_x); }

// [3] main+0x1ed984 was add x28, x27, x8: the XP the game awards, at the address it makes, times the rate.
static void host_xp(Cpu *c) {
    c->x[28] = c->x[27] + c->x[8];
    mul_at(c->x[28], exp_x);
}

// [4] main+0x1ed988 was stur x9, [x29, #-0x34]; the class rank gain is the float at [x28+8].
static void host_class_rank(Cpu *c) {
    memcpy((void *)(uintptr_t)(c->x[29] - 0x34), &c->x[9], sizeof c->x[9]);
    mul_at(c->x[28] + 8, class_rank_x);
}

// [5] main+0x1ed998 was mov w19, wzr; a class icon's filling rate is the float at [x28+8] (the same rate the icon
// loop reads at main+0x1ee1e4). The cheat's injection reads it, multiplies and writes it back, so this does the same.
static void host_class_icon(Cpu *c) {
    c->x[19] = 0;
    mul_at(c->x[28] + 8, class_icon_x);
}

// [27] main+0x2d0c1c was ldr w0, [x8, x9]: the count of an item id in the inventory table at x8 + x9. The site belongs
// to the always-on set "slots" (the row is read here), so with the row off it loads exactly what the replaced
// instruction loaded, and with it on every id reads -1, the sentinel of an empty soul hack slot.
static void host_slot(Cpu *c) {
    if (on_soulhack) c->x[0] = 0xffffffffu;
    else c->x[0] = *(const uint32_t *)(uintptr_t)(c->x[8] + c->x[9]);
}

// [21b] main+0x2eb780 was ldurh w10, [x8, #-2]: the count of one entry while the 3200 byte item table is walked, which
// the next instruction adds to the total the purse shows. The walk reaches this load only for entries whose own id, the
// halfword at [x8-14], matched the id it wants; when that id is a Nopon coin's (the cheat table's two ids) the count
// reads 999 and the purse shows 999 however many are held. Any other entry loads its count as the replaced instruction
// did. The id comes from the entry itself because the id the walk compares against, w19, lives in a C variable at the
// site and a host cannot read it.
static void host_coins(Cpu *c) {
    uint32_t id = *(const uint16_t *)(uintptr_t)(c->x[8] - 14);
    if (id == 0x3eda || id == 0x3edb) c->x[10] = 999;
    else c->x[10] = *(const uint16_t *)(uintptr_t)(c->x[8] - 2);
}

// [2a-e] main+0x1d9638 was ldr w8, [x0, #0x14]: the value the virtual call returned, which the next instruction stores.
// The amount the caller goes on to apply sits in w20, which the lifter keeps in a C variable, so no host can set it:
// this loads what the original loaded and leaves a scale in the patch page, and the site at main+0x1d963c applies
// w20 = w20 * num / den with plain instructions. The cheat table patches those two instructions the same way: damage
// the party deals is multiplied there, damage the party takes is divided (by 2^n there, by the row's share here). The
// table's split is kept: the byte at [x0+0x1e] set with bit 0 of [x22+0x5a] clear is damage the party takes; the byte
// clear with the bit clear is damage the party deals; with the bit set neither applies.
static void host_dmg(Cpu *c) {
    // x0 is a C variable at the site, so the site stores it in the page; x22 stays in Cpu
    uint64_t obj = *(const uint64_t *)(uintptr_t)(RT_PATCH_PAGE + 0xe08);
    uint32_t *num = (uint32_t *)(uintptr_t)(RT_PATCH_PAGE + 0xe00);
    uint32_t *den = (uint32_t *)(uintptr_t)(RT_PATCH_PAGE + 0xe0c);
    *num = 1;
    *den = 1;
    c->x[8] = obj > 0x10000 ? *(const uint32_t *)(uintptr_t)(obj + 0x14) : 0;
    if (obj <= 0x10000 || c->x[22] <= 0x10000) return;
    uint8_t flag = *(const uint8_t *)(uintptr_t)(obj + 0x1e);
    uint32_t bits = *(const uint32_t *)(uintptr_t)(c->x[22] + 0x5a);
    if (bits & 1u) return;
    if (flag) {
        if (dmg_taken < 99.5f) {
            *num = (uint32_t)(dmg_taken + 0.5f);
            *den = 100;
        }
    } else if (on_dmg && dmg_x >= 1.0f) {
        *num = (uint32_t)(dmg_x + 0.5f);
    }
}

__attribute__((constructor)) static void cheat_register(void) {
    rt_register_host(HOST_SPEED, host_speed);
    rt_register_host(HOST_MOON, host_moon);
    rt_register_host(HOST_ARTS_GAUGE, host_arts_gauge);
    rt_register_host(HOST_NO_COOLDOWN, host_no_cooldown);
    rt_register_host(HOST_MEAL, host_meal);
    rt_register_host(HOST_PICKUP, host_pickup);
    rt_register_host(HOST_XP, host_xp);
    rt_register_host(HOST_CLASS_RANK, host_class_rank);
    rt_register_host(HOST_CLASS_ICON, host_class_icon);
    rt_register_host(HOST_SLOT, host_slot);
    rt_register_host(HOST_DMG, host_dmg);
    rt_register_host(HOST_COINS, host_coins);
}
#endif

void rt_patches_init(void) {
#if RT_PATCH_COUNT
    if (!plat_mem_commit(RT_PATCH_PAGE, 0x1000))
        rt_fatal("patches: cannot commit the patch page at %#llx", RT_PATCH_PAGE);
    page = (void *)(uintptr_t)RT_PATCH_PAGE;
    char list[512];
    size_t n = 0;
    list[0] = 0;
    for (int i = 0; i < RT_PATCH_COUNT; i++) {
        const char *e = cfg_get(sets[i].env);
        // a set with a row in the settings table takes its default from there; the generated default serves the rest
        rt_patch_on[i] = (uint8_t)(cfg_meta(sets[i].env) ? cfg_bool(sets[i].env) : e && *e ? strcmp(e, "0") != 0 : sets[i].on);
        n += (size_t)snprintf(list + n, sizeof list - n, "%s%s %s", i ? ", " : "", sets[i].name,
                              rt_patch_on[i] ? "on" : "off");
        if (n >= sizeof list) n = sizeof list - 1;
    }
    speed_x = (float)cfg_double("XC3_SPEED_X");   // the cheat's multiplier; its row has the default
    *(uint32_t *)(uintptr_t)(RT_PATCH_PAGE + 0xe00) = 1;   // the damage site's rate, until a hit sets it
    rt_log("patches: %s (page %#llx)", list, RT_PATCH_PAGE);
#endif
}

int rt_patch_set(const char *name) {
#if RT_PATCH_COUNT
    for (int i = 0; i < RT_PATCH_COUNT; i++)
        if (!strcmp(sets[i].name, name)) return i;
#endif
    (void)name;
    return -1;
}

int rt_patch_enabled(int set) { return set >= 0 && set < RT_PATCH_COUNT && rt_patch_on[set]; }

void rt_patch_disable(int set) {
    if (set >= 0 && set < RT_PATCH_COUNT) rt_patch_on[set] = 0;
}

void rt_patch_switch(int set, int on) {
    if (set >= 0 && set < RT_PATCH_COUNT) __atomic_store_n(&rt_patch_on[set], (uint8_t)(on != 0), __ATOMIC_RELAXED);
}

// Every set that has a settings row takes that row's value. The Cheats page calls this once a frame, so a row changes
// its cheat at once, and none of the page's rows has to call rt_patch_switch itself: adding a cheat is its cfg row, its
// site and its row on the page. pad_buttons also calls it, which covers a setting changed without the menu (the
// XC3_MENU_TEST_SET probe), and costs one atomic load per poll.
void rt_patch_sync(void) {
#if RT_PATCH_COUNT
    sets_from_cfg();
#endif
}

void *rt_patch_page(void) {
#if RT_PATCH_COUNT
    return page;
#else
    return NULL;
#endif
}
