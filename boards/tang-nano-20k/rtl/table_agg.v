// Hand-written board glue (not generated, not part of the product): SELECT key, COUNT(*), SUM(v), MIN(v), MAX(v) FROM rows
// WHERE v >= FILTER.MIN GROUP BY key, for rows (key: 8 bits, v: 16 bits signed) streamed in. Registers: table/table.chw. A row is taken when
// ROW changes value (toggle TOG for a repeated row); ROWS counts rows received, KEPT those that passed the filter. SEL picks the group the
// R_* registers show (R_SUM is 48-bit signed in two registers). CTRL.CLR high clears every group. min of an empty group reads 32767, max -32768.
`timescale 1ns/1ps
`default_nettype none
module table_agg (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        clr,
    input  wire [31:0] filter, row, sel,
    output wire [31:0] r_count, r_sum_lo, r_sum_hi, r_min, r_max, rows, kept
);
    reg [31:0]        cnt_m [0:255];
    reg signed [47:0] sum_m [0:255];
    reg signed [15:0] min_m [0:255];
    reg signed [15:0] max_m [0:255];
    reg [7:0]  raddr, clr_addr, ra, waddr;
    reg signed [15:0] v;
    reg [31:0] rcnt, nrows, nkept, row_prev;
    reg signed [47:0] rsum;
    reg signed [15:0] rmin, rmax;
    reg [31:0] wd_c;
    reg signed [47:0] wd_s;
    reg signed [15:0] wd_n, wd_x;
    reg        wen, busy, clr_active, clr_prev;
    reg [2:0]  hs;
    // Every input of the RAMs comes straight from a register (no logic between a flip-flop and a RAM pin): the read address `ra`, and the write
    // enable, address and data. nextpnr reported hold-time violations on the first version, where the write enable was `we | clr_active`.
    always @(posedge clk) begin
        if (wen) begin cnt_m[waddr] <= wd_c; sum_m[waddr] <= wd_s; min_m[waddr] <= wd_n; max_m[waddr] <= wd_x; end
        ra <= busy ? raddr : sel[7:0];
        rcnt <= cnt_m[ra]; rsum <= sum_m[ra]; rmin <= min_m[ra]; rmax <= max_m[ra];
    end
    always @(posedge clk) begin
        row_prev <= row; clr_prev <= clr;
        if (!rst_n) begin busy <= 1'b0; wen <= 1'b0; hs <= 3'd0; clr_active <= 1'b0; nrows <= 32'd0; nkept <= 32'd0; clr_addr <= 8'd0; end
        else if (clr) begin
            if (!clr_prev) begin clr_active <= 1'b1; clr_addr <= 8'd0; nrows <= 32'd0; nkept <= 32'd0; end
            else if (clr_active) begin
                wen <= 1'b1; waddr <= clr_addr; wd_c <= 32'd0; wd_s <= 48'sd0; wd_n <= 16'sh7FFF; wd_x <= 16'sh8000;
                if (clr_addr == 8'd255) clr_active <= 1'b0; else clr_addr <= clr_addr + 8'd1;
            end else wen <= 1'b0;
        end else begin
            clr_active <= 1'b0;
            if (!busy && row != row_prev) begin
                nrows <= nrows + 32'd1;
                v <= row[23:8];
                wen <= 1'b0;
                if ($signed(row[23:8]) >= $signed(filter[15:0])) begin raddr <= row[7:0]; busy <= 1'b1; hs <= 3'd0; nkept <= nkept + 32'd1; end
            end else if (busy) begin
                hs <= hs + 3'd1;
                if (hs == 3'd2) begin                        // rcnt, rsum, rmin, rmax hold the group: ra was set at hs 0, the RAM answered at hs 1
                    wd_c <= rcnt + 32'd1; wd_s <= rsum + v;
                    wd_n <= (rcnt == 32'd0 || v < rmin) ? v : rmin;
                    wd_x <= (rcnt == 32'd0 || v > rmax) ? v : rmax;
                    waddr <= raddr; wen <= 1'b1;
                end
                if (hs == 3'd3) wen <= 1'b0;                 // the write happened on this clock edge
                if (hs == 3'd4) busy <= 1'b0;
            end else wen <= 1'b0;
        end
    end
    assign r_count = rcnt;
    assign r_sum_lo = rsum[31:0];
    assign r_sum_hi = {{16{rsum[47]}}, rsum[47:32]};
    assign r_min = {{16{rmin[15]}}, rmin};
    assign r_max = {{16{rmax[15]}}, rmax};
    assign rows = nrows;
    assign kept = nkept;
endmodule
`default_nettype wire
