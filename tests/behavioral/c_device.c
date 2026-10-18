/* c_device.c — the C-side engine for the behavioral roundtrip.
 *
 * It links against the GENERATED c-header (the artifact under test):
 * register storage is an instance of the block struct, register words
 * and field accessors use the header's members, resets come from its
 * RESET_* macros, and DMA field storage uses the packed buffer
 * structs. What it adds is the contract's access-kind semantics — a
 * faithful port of tools/sim/reference_model.py's observable
 * behavior. The wiring header (emitted from the same IR by
 * tests/behavioral/c_behavior.py) adds, as _Static_assert lines, one
 * per register and one per DMA field, pinning the header's member
 * offsets (`offsetof`) to the contract's offsets.
 *
 * It is NOT the generated-RTL story: the SystemVerilog module remains
 * the only generated device model. This engine is a test fixture, so
 * the roundtrip's claim is exactly this: generated-header encoding +
 * contract semantics behave identically to the reference model, op by
 * op, on the shared corpus (tests/behavioral/scenarios.json).
 *
 * stdin: one op per line (tools/sim/op_runner.py grammar).
 * stdout: one trace line per op — "OK", "OK 0x<8-hex>", "OK 0|1"
 * (interrupt queries) or "ERR <code>".
 *
 * Word width is 32 (the MVP bus width): a wiring for a narrower bus
 * refuses at compile time instead of silently widening.
 *
 * Known asymmetry ported as-is from the model (the roundtrip's point
 * is to keep the two engines equal, not to "fix" either): model W0S
 * is implemented as `state & ~value` — the same fold as W1C — so a
 * CPU write of 0 under W0S leaves state unchanged. reference_model.py
 * owns that; the engine mirrors it exactly.
 */

#include <stdio.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>

#include WIRING

_Static_assert(BUS_WIDTH == 32,
               "c_device engine supports the 32-bit bus width only; "
               "extend the engine for 8/16-bus contracts rather than "
               "silently widening");

/* --- finders over the wiring's IR tables ----------------------------- */

static volatile uint32_t *reg_word(int r) { return REG_WORD_TABLE[r]; }

static int reg_find(const char *name) {
    int i;
    for (i = 0; i < N_REGS; i++)
        if (strcmp(REG_NAMES[i], name) == 0) return i;
    return -1;
}

static int field_find(int r, const char *name) {
    const FDesc *fs = FIELD_TABLES[r];
    int i;
    for (i = 0; i < FIELD_COUNTS[r]; i++)
        if (strcmp(fs[i].name, name) == 0) return i;
    return -1;
}

static int dma_find(const char *name) {
    int i;
    for (i = 0; i < N_DMA; i++)
        if (strcmp(DMA_NAMES[i], name) == 0) return i;
    return -1;
}

static int dma_field_find(int b, const char *fname) {
    const DmaFDesc *fs = DMA_FIELD_DESCS[b];
    int i;
    for (i = 0; i < DMA_FIELD_COUNTS[b]; i++)
        if (strcmp(fs[i].name, fname) == 0) return i;
    return -1;
}

static int intr_find(const char *name) {
    int i;
    for (i = 0; i < N_INTS; i++)
        if (strcmp(INTR_NAMES[i], name) == 0) return i;
    return -1;
}

static uint32_t fmask(int lsb, int msb) {
    return (uint32_t)(((1u << (msb - lsb + 1)) - 1u) << lsb);
}

/* --- trace emission ---------------------------------------------------- */

static void trace_ok(void) { printf("OK\n"); }

static void trace_val(uint32_t v) { printf("OK 0x%08x\n", (unsigned)v); }

static void trace_bool(int b) { printf("OK %u\n", (unsigned)(b ? 1 : 0)); }

static void trace_err(const char *err) { printf("ERR %s\n", err); }

static void trace_done(const char *err, int has_value, uint32_t v) {
    if (err) { trace_err(err); return; }
    if (has_value) trace_val(v);
    else trace_ok();
}

/* --- contract semantics, ported from reference_model.py -------------- */

static void eng_reset(void) {
    int i;
    dma_zero();
    for (i = 0; i < N_REGS; i++)
        *reg_word(i) = reg_reset(i) & 0xFFFFFFFFu;
}

static uint32_t eng_read_reg(int r, const char **err) {
    uint32_t v;
    int k = REG_KIND[r];
    if (k == K_WO) { *err = "runtime-access-kind-violation"; return 0; }
    v = *reg_word(r);
    if (k == K_RC)
        *reg_word(r) = 0;   /* RC reads then clears (single-step model) */
    return v;
}

static void eng_write_reg(int r, uint32_t value, const char **err) {
    volatile uint32_t *w = reg_word(r);
    int k = REG_KIND[r];
    value &= 0xFFFFFFFFu;
    if (k == K_RO) { *err = "runtime-access-kind-violation"; return; }
    if (k == K_WO) { *w = value; return; }               /* full replacement */
    if (k == K_RW || k == K_RC) { *w = value; return; }
    if (k == K_W1C) { *w = (uint32_t)(*w & ~value); return; }
    if (k == K_W0C) { *w = (uint32_t)(*w & value); return; }
    if (k == K_W1S) { *w = (uint32_t)(*w | value); return; }
    if (k == K_W0S) { *w = (uint32_t)(*w & ~value); return; }
    *err = "runtime-access-kind-unknown";
}

/* Field encode: overflow + enum membership — model._encode_field. */
static int eng_encode_check(int r, int f, uint32_t v, uint32_t *encoded_out,
                            const char **err) {
    unsigned width = (unsigned)(FIELD_TABLES[r][f].msb -
                                FIELD_TABLES[r][f].lsb + 1);
    unsigned n, i;
    const uint32_t *enumv;
    if (v >= (1u << width)) { *err = "runtime-field-value-overflow"; return 0; }
    n = (unsigned)FIELD_TABLES[r][f].enum_n;
    if (n > 0) {
        enumv = FIELD_TABLES[r][f].enumv;
        for (i = 0; i < n; i++)
            if (enumv[i] == v) break;
        if (i == n) { *err = "runtime-field-enum-violation"; return 0; }
    }
    *encoded_out = v << FIELD_TABLES[r][f].lsb;
    return 1;
}

static void eng_write_field_word(int r, int f, uint32_t v, const char **err) {
    /* The word-fold path: W1C/W0C/W1S/W0S fold the encoded field bits
       into the whole word (model.write_field's family branch); RW/RC
       replace the field's bits; WO replaces the field over current 0
       (model: "reading" a WO register is undefined; treat as 0). */
    volatile uint32_t *w = reg_word(r);
    int k = REG_KIND[r];
    uint32_t encoded;
    if (!eng_encode_check(r, f, v, &encoded, err)) return;
    if (k == K_W1C) { *w &= ~encoded; return; }
    if (k == K_W0C) { *w &= encoded; return; }
    if (k == K_W1S) { *w |= encoded; return; }
    if (k == K_W0S) { *w &= ~encoded; return; }
    if (k == K_WO) { *w = encoded; return; }   /* ((0 & ~mask) | encoded) */
    *w = (uint32_t)((*w & ~fmask(FIELD_TABLES[r][f].lsb,
                                 FIELD_TABLES[r][f].msb)) | encoded);
}

/* The accessor path for the plain kinds: the RMW runs through the
   header's bitfield member — the layout under test. */
static void eng_write_field(int r, int f, uint32_t v, const char **err) {
    int k = REG_KIND[r];
    uint32_t encoded = 0;
    if (k == K_RO) { *err = "runtime-access-kind-violation"; return; }
    if (k == K_W1C || k == K_W0C || k == K_W1S || k == K_W0S) {
        eng_write_field_word(r, f, v, err);
        return;
    }
    if (!eng_encode_check(r, f, v, &encoded, err)) return;
    if (k == K_WO) {
        *reg_word(r) = encoded;   /* model: current read as 0 */
        return;
    }
    bf_write(r, f, v);
}

static uint32_t eng_read_field(int r, int f, const char **err) {
    /* model.read_field = read() (with its RC side effects) + decode,
       applied to the value read BEFORE the clear — so the decode
       formula runs on the captured word, not on post-clear storage. */
    uint32_t word = eng_read_reg(r, err);
    if (*err) return 0;
    return (word & fmask(FIELD_TABLES[r][f].lsb,
                         FIELD_TABLES[r][f].msb)) >> FIELD_TABLES[r][f].lsb;
}

/* Device-side full-word write (bypasses CPU access-kind refusals but
   keeps the per-kind fold — model.device_write). */
static void eng_device_write(int r, uint32_t value, const char **err) {
    volatile uint32_t *w = reg_word(r);
    int k = REG_KIND[r];
    value &= 0xFFFFFFFFu;
    if (k == K_WO) { *err = "runtime-device-write-wo"; return; }
    if (k == K_RW || k == K_RC || k == K_RO) { *w = value; return; }
    if (k == K_W1C || k == K_W1S) { *w = (uint32_t)(*w | value); return; }
    if (k == K_W0C) { *w = (uint32_t)(*w & value); return; }
    if (k == K_W0S) { *w = (uint32_t)(*w & ~value); return; }
    *err = "runtime-access-kind-unknown";
}

/* Device-side field write: overflow check only, NO enum check; per-
   kind fold, else full field replace (model.device_write_field). */
static void eng_device_write_field(int r, int f, uint32_t v, const char **err) {
    volatile uint32_t *w = reg_word(r);
    int k = REG_KIND[r];
    unsigned width = (unsigned)(FIELD_TABLES[r][f].msb -
                                FIELD_TABLES[r][f].lsb + 1);
    uint32_t encoded;
    if (v >= (1u << width)) { *err = "runtime-field-value-overflow"; return; }
    encoded = v << FIELD_TABLES[r][f].lsb;
    if (k == K_W1C || k == K_W1S) { *w |= encoded; return; }
    if (k == K_W0C || k == K_W0S) { *w &= ~encoded; return; }
    *w = (uint32_t)((*w & ~fmask(FIELD_TABLES[r][f].lsb,
                                 FIELD_TABLES[r][f].msb)) | encoded);
}

/* --- DMA -------------------------------------------------------------- */

static void eng_dma_write(int b, int fi, uint64_t v, const char **err,
                          int device_side) {
    volatile void *p = DMA_FIELD_PTRS[b][fi];
    const DmaFDesc *fd = &DMA_FIELD_DESCS[b][fi];
    v &= 0xFFFFFFFFULL;   /* the model masks DMA values to 32 bits */
    if (device_side && fd->owner != OWN_DEVICE) {
        *err = "runtime-dma-owner-violation"; return;
    }
    if (!device_side && fd->owner != OWN_CPU) {
        *err = "runtime-dma-owner-violation"; return;
    }
    switch (fd->size) {
        case 1: *(volatile uint8_t *)p = (uint8_t)v; break;
        case 2: *(volatile uint16_t *)p = (uint16_t)v; break;
        case 4: *(volatile uint32_t *)p = (uint32_t)v; break;
        case 8: *(volatile uint64_t *)p = v; break;
    }
}

static uint64_t eng_dma_read(int b, int fi, const char **err) {
    volatile void *p = DMA_FIELD_PTRS[b][fi];
    const DmaFDesc *fd = &DMA_FIELD_DESCS[b][fi];
    (void)err;
    switch (fd->size) {
        case 1: return *(volatile uint8_t *)p;
        case 2: return *(volatile uint16_t *)p;
        case 4: return *(volatile uint32_t *)p;
        case 8: return *(volatile uint64_t *)p;
    }
    return 0;
}

/* --- interrupts (port of the model's linkage logic) ------------------- */

static void eng_intr_role(int i, int role, const char **err) {
    /* role: 0 = pending(status), 1 = enabled, 2 = source-active */
    const IntrDesc *in = &INTRS[i];
    int r, f;
    if (role == 0)      { r = in->st_reg;  f = in->st_fld;  }
    else if (role == 1) { r = in->en_reg;  f = in->en_fld;  }
    else                { r = in->src_reg; f = in->src_fld; }
    if (r < 0) { trace_bool(0); return; }   /* no linkage → model: False */
    trace_bool(eng_read_field(r, f, err) != 0 ? 1 : 0);
}

static void eng_intr_clear(int i, const char **err) {
    const IntrDesc *in = &INTRS[i];
    if (in->clr_reg < 0) { *err = "runtime-interrupt-no-clear"; return; }
    if (in->clr_kind == K_W1C)
        eng_write_field_word(in->clr_reg, in->clr_fld, 1, err);
    else if (in->clr_kind == K_W0C)
        eng_write_field_word(in->clr_reg, in->clr_fld, 0, err);
    else if (in->clr_kind == K_RC)
        eng_read_reg(in->clr_reg, err);
    else { *err = "runtime-interrupt-clear-kind-unknown"; return; }
    if (*err) return;
    /* The controller drops the latched status — a raw mask clear
       (bypassing CPU access checks), exactly as the model does. */
    if (in->st_reg >= 0) {
        *reg_word(in->st_reg) &=
            ~fmask(FIELD_TABLES[in->st_reg][in->st_fld].lsb,
                   FIELD_TABLES[in->st_reg][in->st_fld].msb);
    }
}

/* --- op loop ----------------------------------------------------------- */

static void run_op(const char *op) {
    const char *err = NULL;
    uint32_t v32 = 0;
    uint64_t v64 = 0;
    int r, f, b, fi;

    if (!op) return;
    if (strcmp(op, "R") == 0) {
        char *rn = strtok(NULL, " \t\r\n");
        r = rn ? reg_find(rn) : -1;
        if (r < 0) { trace_err("runtime-register-unknown"); return; }
        v32 = eng_read_reg(r, &err);
        trace_done(err, 1, v32);
    } else if (strcmp(op, "Rf") == 0) {
        char *rn = strtok(NULL, " \t\r\n");
        char *fn = strtok(NULL, " \t\r\n");
        if (!rn || !fn) { trace_err("op-malformed"); return; }
        r = reg_find(rn);
        if (r < 0) { trace_err("runtime-register-unknown"); return; }
        f = field_find(r, fn);
        if (f < 0) { trace_err("runtime-field-unknown"); return; }
        v32 = eng_read_field(r, f, &err);
        trace_done(err, 1, v32);
    } else if (strcmp(op, "W") == 0 || strcmp(op, "D") == 0) {
        int dev = op[0] == 'D';
        char *rn = strtok(NULL, " \t\r\n");
        char *vn = strtok(NULL, " \t\r\n");
        if (!vn || !rn) { trace_err("op-malformed"); return; }
        r = reg_find(rn);
        if (r < 0) { trace_err("runtime-register-unknown"); return; }
        v32 = (uint32_t)strtoull(vn, NULL, 0);
        if (dev) eng_device_write(r, v32, &err);
        else eng_write_reg(r, v32, &err);
        trace_done(err, 0, 0);
    } else if (strcmp(op, "Wf") == 0 || strcmp(op, "Df") == 0) {
        int dev = op[0] == 'D';
        char *rn = strtok(NULL, " \t\r\n");
        char *fn = strtok(NULL, " \t\r\n");
        char *vn = strtok(NULL, " \t\r\n");
        if (!rn || !fn || !vn) { trace_err("op-malformed"); return; }
        r = reg_find(rn);
        if (r < 0) { trace_err("runtime-register-unknown"); return; }
        f = field_find(r, fn);
        if (f < 0) { trace_err("runtime-field-unknown"); return; }
        v32 = (uint32_t)strtoull(vn, NULL, 0);
        if (dev) eng_device_write_field(r, f, v32, &err);
        else eng_write_field(r, f, v32, &err);
        trace_done(err, 0, 0);
    } else if (strcmp(op, "DW") == 0 || strcmp(op, "DX") == 0) {
        int dev = op[1] == 'X';
        char *bn = strtok(NULL, " \t\r\n");
        char *fn = strtok(NULL, " \t\r\n");
        char *vn = strtok(NULL, " \t\r\n");
        if (!bn || !fn || !vn) { trace_err("op-malformed"); return; }
        b = dma_find(bn);
        if (b < 0) { trace_err("runtime-dma-buffer-unknown"); return; }
        fi = dma_field_find(b, fn);
        if (fi < 0) { trace_err("runtime-dma-field-unknown"); return; }
        v64 = strtoull(vn, NULL, 0);
        eng_dma_write(b, fi, v64, &err, dev);
        trace_done(err, 0, 0);
    } else if (strcmp(op, "DR") == 0) {
        char *bn = strtok(NULL, " \t\r\n");
        char *fn = strtok(NULL, " \t\r\n");
        if (!bn || !fn) { trace_err("op-malformed"); return; }
        b = dma_find(bn);
        if (b < 0) { trace_err("runtime-dma-buffer-unknown"); return; }
        fi = dma_field_find(b, fn);
        if (fi < 0) { trace_err("runtime-dma-field-unknown"); return; }
        v64 = eng_dma_read(b, fi, &err);
        trace_done(err, 1, (uint32_t)v64);
    } else if (strcmp(op, "RESET") == 0) {
        eng_reset();
        trace_done(NULL, 0, 0);
    } else if (strcmp(op, "IP") == 0 || strcmp(op, "PE") == 0 ||
               strcmp(op, "PS") == 0) {
        char *in = strtok(NULL, " \t\r\n");
        int role = op[1] == 'P' ? 0 : (op[1] == 'E' ? 1 : 2);
        if (!in) { trace_err("op-malformed"); return; }
        r = intr_find(in);
        if (r < 0) { trace_err("runtime-interrupt-unknown"); return; }
        eng_intr_role(r, role, &err);
        if (err) trace_err(err);
    } else if (strcmp(op, "PC") == 0) {
        char *in = strtok(NULL, " \t\r\n");
        if (!in) { trace_err("op-malformed"); return; }
        r = intr_find(in);
        if (r < 0) { trace_err("runtime-interrupt-unknown"); return; }
        eng_intr_clear(r, &err);
        trace_done(err, 0, 0);
    } else {
        trace_err("op-unknown");
    }
}

int main(void) {
    char line[512];
    eng_reset();
    while (fgets(line, sizeof line, stdin)) {
        run_op(strtok(line, " \t\r\n"));
    }
    return 0;
}
