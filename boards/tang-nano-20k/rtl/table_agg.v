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
    reg [7:0]  raddr, clr_addr;
    reg signed [15:0] v;
    reg [31:0] rcnt, nrows, nkept, row_prev;
    reg signed [47:0] rsum;
    reg signed [15:0] rmin, rmax;
    reg [31:0] wcnt;
    reg signed [47:0] wsum;
    reg signed [15:0] wmin, wmax;
    reg        we, busy, clr_active, clr_prev;
    reg [1:0]  hs;
    wire [7:0] addr = busy ? raddr : clr_active ? clr_addr : sel[7:0];
    wire       we_i = we | clr_active;
    wire [31:0] wc = clr_active ? 32'd0 : wcnt;
    wire signed [47:0] ws = clr_active ? 48'sd0 : wsum;
    wire signed [15:0] wn = clr_active ? 16'sh7FFF : wmin;
    wire signed [15:0] wx = clr_active ? 16'sh8000 : wmax;
    always @(posedge clk) begin
        if (we_i) begin cnt_m[addr] <= wc; sum_m[addr] <= ws; min_m[addr] <= wn; max_m[addr] <= wx; end
        rcnt <= cnt_m[addr]; rsum <= sum_m[addr]; rmin <= min_m[addr]; rmax <= max_m[addr];
    end
    always @(posedge clk) begin
        row_prev <= row; clr_prev <= clr;
        if (!rst_n) begin busy <= 1'b0; we <= 1'b0; hs <= 2'd0; clr_active <= 1'b0; nrows <= 32'd0; nkept <= 32'd0; clr_addr <= 8'd0; end
        else if (clr) begin
            if (!clr_prev) begin clr_active <= 1'b1; clr_addr <= 8'd0; nrows <= 32'd0; nkept <= 32'd0; end
            else if (clr_active) begin if (clr_addr == 8'd255) clr_active <= 1'b0; else clr_addr <= clr_addr + 8'd1; end
            else we <= 1'b0;
        end else begin
            clr_active <= 1'b0;
            if (!busy && row != row_prev) begin
                nrows <= nrows + 32'd1;
                v <= row[23:8];
                if ($signed(row[23:8]) >= $signed(filter[15:0])) begin raddr <= row[7:0]; busy <= 1'b1; hs <= 2'd0; we <= 1'b0; nkept <= nkept + 32'd1; end
            end else if (busy) begin
                hs <= hs + 2'd1;
                if (hs == 2'd1) begin                        // rcnt, rsum, rmin, rmax hold the group read two clocks ago
                    wcnt <= rcnt + 32'd1; wsum <= rsum + v;
                    wmin <= (rcnt == 32'd0 || v < rmin) ? v : rmin;
                    wmax <= (rcnt == 32'd0 || v > rmax) ? v : rmax;
                    we <= 1'b1;
                end
                if (hs == 2'd2) we <= 1'b0;
                if (hs == 2'd3) busy <= 1'b0;
            end else we <= 1'b0;
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
