// Hand-written board glue (not generated, not part of the product): three small instruments behind the registers of lab/lab.chw.
//
//   analyzer   records every change of an 8-bit probe, with the 27 MHz tick it happened on, in a 512-entry FIFO. The probe is the UART's
//              RX pin (CTRL.PROBE_SEL=0) or the sequencer's output pins (PROBE_SEL=1). Enabling (CTRL.AN_EN 0 to 1) clears the FIFO and
//              records the level at that moment first. AN_POP changing value drops the head entry; AN_TS and AN_VAL show the head.
//              While enabled, the register traffic itself is on the RX pin and is recorded: disable before draining.
//   sequencer  replays up to 512 (tick, pins) events from RAM on the six LED pins: CTRL.SEQ_RUN 0 to 1 restarts at tick 0; an event fires
//              on the first clock its tick is reached. Events must be at least 3 ticks apart and sorted. SEQ_LOAD changing value
//              stores (SEQ_TIME, SEQ_MASK) at SEQ_ADDR. SEQ_STATUS: DONE, and the next event index.
//   histogram  4096 hbin of 16 bits. HIST_IN changing value (any bit, so toggle TOG for a repeated outcome) counts one shot in bin
//              OUTCOME. HIST_SEL picks the bin HIST_COUNT shows; HIST_TOTAL counts shots. CTRL.HIST_CLR high clears all hbin.
// Registers that read the instruments are inputs of the generated block (cancho-hdl#21); registers that act "on change" are plain RW
// registers watched here, because a generated block has no write strobe.
`timescale 1ns/1ps
`default_nettype none
module lab (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        rx_pin,
    input  wire [31:0] ctrl,
    input  wire [31:0] an_pop,
    output wire [31:0] an_status,
    output wire [31:0] an_ts,
    output wire [31:0] an_val,
    input  wire [31:0] seq_addr,
    input  wire [31:0] seq_time,
    input  wire [31:0] seq_mask,
    input  wire [31:0] seq_load,
    input  wire [31:0] seq_len,
    output wire [31:0] seq_status,
    input  wire [31:0] hist_in,
    input  wire [31:0] hist_sel,
    output wire [31:0] hist_count,
    output wire [31:0] hist_total,
    output wire [5:0]  seq_pins
);
    reg [31:0] tick;
    always @(posedge clk) if (!rst_n) tick <= 32'd0; else tick <= tick + 32'd1;

    // ---- analyzer ----
    reg [5:0]  seq_out;
    wire [7:0] probe_raw = ctrl[4] ? {2'b0, seq_out} : {7'b0, rx_pin};
    reg  [7:0] probe_s, probe_prev;
    reg        en_prev, en_prev_d;
    reg [31:0] ts_mem [0:511];
    reg [7:0]  val_mem [0:511];
    reg [9:0]  wptr, rptr;
    reg        ovf;
    reg [31:0] head_ts;
    reg [7:0]  head_val;
    reg [31:0] pop_prev;
    wire [9:0] count = wptr - rptr;
    wire an_en = ctrl[0];
    always @(posedge clk) begin
        head_ts  <= ts_mem[rptr[8:0]];
        head_val <= val_mem[rptr[8:0]];
        probe_s <= probe_raw; probe_prev <= probe_s; en_prev <= an_en; pop_prev <= an_pop;
        if (!rst_n) begin wptr <= 10'd0; rptr <= 10'd0; ovf <= 1'b0; end
        else begin
            if (an_en && !en_prev) begin wptr <= 10'd0; rptr <= 10'd0; ovf <= 1'b0; end   // arm: clear (the first entry follows)
            else if (an_en && (probe_s != probe_prev || !en_prev_d)) begin
                if (count == 10'd512) ovf <= 1'b1;
                else begin ts_mem[wptr[8:0]] <= tick; val_mem[wptr[8:0]] <= probe_s; wptr <= wptr + 10'd1; end
            end
            if (an_pop != pop_prev && count != 10'd0) rptr <= rptr + 10'd1;
        end
    end
    always @(posedge clk) en_prev_d <= en_prev;       // 0 for the one clock after arming: the initial level is recorded then
    assign an_status = {15'b0, ovf, 6'b0, count};
    assign an_ts = head_ts;
    assign an_val = {24'b0, head_val};

    // ---- sequencer ----
    reg [31:0] ev_time [0:511];
    reg [5:0]  ev_mask [0:511];
    reg [31:0] load_prev;
    reg [31:0] cur_time;
    reg [5:0]  cur_mask;
    reg [8:0]  idx;
    reg [31:0] stick;
    reg [1:0]  waitc;
    reg        run_prev, done;
    always @(posedge clk) begin
        load_prev <= seq_load; run_prev <= ctrl[1];
        if (seq_load != load_prev) begin ev_time[seq_addr[8:0]] <= seq_time; ev_mask[seq_addr[8:0]] <= seq_mask[5:0]; end
        cur_time <= ev_time[idx]; cur_mask <= ev_mask[idx];
        if (!rst_n) begin seq_out <= 6'd0; idx <= 9'd0; stick <= 32'd0; waitc <= 2'd0; done <= 1'b0; end
        else if (ctrl[1] && !run_prev) begin seq_out <= 6'd0; idx <= 9'd0; stick <= 32'd0; waitc <= 2'd3; done <= 1'b0; end
        else if (ctrl[1] && !done) begin
            stick <= stick + 32'd1;
            if (waitc != 2'd0) waitc <= waitc - 2'd1;
            else if ({23'b0, idx} >= seq_len) done <= 1'b1;
            else if (stick >= cur_time) begin seq_out <= cur_mask; idx <= idx + 9'd1; waitc <= 2'd3; end
        end
    end
    assign seq_status = {15'b0, idx, 7'b0, done};
    assign seq_pins = seq_out;

    // ---- histogram ----
    reg [15:0] hbin [0:4095];
    reg [11:0] raddr, clr_addr;
    reg [15:0] rd, wdata;
    reg        we, busy, clr_active, clr_prev;
    reg [1:0]  hs;
    reg [31:0] hin_prev, total;
    wire [11:0] addr = busy ? raddr : clr_active ? clr_addr : hist_sel[11:0];
    wire        we_i = we | clr_active;                 // clearing writes zero to the address of the same clock
    wire [15:0] wd_i = clr_active ? 16'd0 : wdata;
    always @(posedge clk) begin
        if (we_i) hbin[addr] <= wd_i;
        rd <= hbin[addr];
    end
    always @(posedge clk) begin
        hin_prev <= hist_in; clr_prev <= ctrl[2];
        if (!rst_n) begin busy <= 1'b0; we <= 1'b0; hs <= 2'd0; clr_active <= 1'b0; total <= 32'd0; clr_addr <= 12'd0; end
        else if (ctrl[2]) begin
            if (!clr_prev) begin clr_active <= 1'b1; clr_addr <= 12'd0; total <= 32'd0; end
            else if (clr_active) begin
                if (clr_addr == 12'd4095) clr_active <= 1'b0; else clr_addr <= clr_addr + 12'd1;
            end else we <= 1'b0;
        end else begin
            clr_active <= 1'b0;
            if (!busy && hist_in != hin_prev) begin raddr <= hist_in[11:0]; busy <= 1'b1; hs <= 2'd0; we <= 1'b0; end
            else if (busy) begin
                hs <= hs + 2'd1;
                if (hs == 2'd1) begin wdata <= rd + 16'd1; we <= 1'b1; end
                if (hs == 2'd2) begin we <= 1'b0; total <= total + 32'd1; end
                if (hs == 2'd3) busy <= 1'b0;
            end else we <= 1'b0;
        end
    end
    assign hist_count = {16'b0, rd};
    assign hist_total = total;
endmodule
`default_nettype wire
