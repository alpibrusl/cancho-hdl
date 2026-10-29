// Hand-written board glue (not generated, not part of the product): y = A x for a signed 8-bit matrix A of up to 32 x 32 and a signed
// 8-bit vector x, exact 32-bit sums, behind the registers of gemv/gemv.chw. A is stored row-major at index row*32 + col. One
// multiply-accumulate every 3 clocks. W_LOAD / X_LOAD / GO act when their register changes value (toggle TOG); STATUS.DONE is 0 from GO
// until the last row is stored; Y_SEL picks the row Y_VAL shows.
`timescale 1ns/1ps
`default_nettype none
module gemv (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [31:0] dim, w_addr, w_data, w_load, x_idx, x_val, x_load, go, y_sel,
    output wire [31:0] status,
    output wire [31:0] y_val
);
    reg signed [7:0]  wmem [0:1023];
    reg signed [7:0]  xmem [0:31];
    reg signed [31:0] ymem [0:31];
    reg [31:0] wl_prev, xl_prev, go_prev;
    reg [9:0]  wa;
    reg [4:0]  xa;
    reg signed [7:0] wd, xd;
    reg signed [31:0] acc, yv;
    reg [5:0] r, c;
    reg [2:0] st;
    reg done;
    wire [5:0] rows = dim[5:0], cols = dim[13:8];
    always @(posedge clk) begin
        wl_prev <= w_load; xl_prev <= x_load; go_prev <= go;
        if (w_load != wl_prev) wmem[w_addr[9:0]] <= w_data[7:0];
        if (x_load != xl_prev) xmem[x_idx[4:0]] <= x_val[7:0];
        wd <= wmem[wa]; xd <= xmem[xa]; yv <= ymem[y_sel[4:0]];
        if (!rst_n) begin st <= 3'd0; done <= 1'b0; end
        else case (st)
            3'd0: if (go != go_prev && rows != 0 && cols != 0) begin r <= 6'd0; c <= 6'd0; acc <= 32'sd0; done <= 1'b0; st <= 3'd1; end
            3'd1: begin wa <= {r[4:0], c[4:0]}; xa <= c[4:0]; st <= 3'd2; end          // present the addresses
            3'd2: st <= 3'd3;                                                          // the RAMs answer
            3'd3: begin
                acc <= acc + wd * xd;
                if (c == cols - 6'd1) st <= 3'd4; else begin c <= c + 6'd1; st <= 3'd1; end
            end
            3'd4: begin
                ymem[r[4:0]] <= acc; acc <= 32'sd0;
                if (r == rows - 6'd1) begin done <= 1'b1; st <= 3'd0; end else begin r <= r + 6'd1; c <= 6'd0; st <= 3'd1; end
            end
            default: st <= 3'd0;
        endcase
    end
    assign status = {31'b0, done};
    assign y_val = yv;
endmodule
`default_nettype wire
