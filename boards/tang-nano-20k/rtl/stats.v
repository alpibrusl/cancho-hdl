// Hand-written board glue (not generated, not part of the product): streaming sums for a least-squares line, behind the registers of
// stats/stats.chw. Each time the SAMPLE register changes value (toggle TOG for a repeated sample) the pair (x, y) is accumulated:
//   n, Sx, Sy (48-bit signed), Sxx, Syy (64-bit unsigned), Sxy (64-bit signed). x is 16-bit signed, y 15-bit signed. All integer, so the
// sums are exact; CTRL.CLR high clears them. 64-bit sums are read as two 32-bit registers (low, then high); the 48-bit sums' high
// words are sign-extended. The host derives slope, intercept and correlation from them.
`timescale 1ns/1ps
`default_nettype none
module stats (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        clr,
    input  wire [31:0] sample,
    output wire [31:0] n_out,
    output wire [63:0] sx_out, sy_out, sxx_out, sxy_out, syy_out
);
    reg [31:0] prev, n;
    reg signed [63:0] sx, sy, sxy;
    reg [63:0] sxx, syy;
    wire signed [15:0] x = sample[15:0];
    wire signed [15:0] y = {sample[30], sample[30:16]};       // 15-bit signed, sign-extended
    wire signed [31:0] xx = x * x, yy = y * y, xy = x * y;
    always @(posedge clk) begin
        prev <= sample;
        if (!rst_n || clr) begin n <= 0; sx <= 0; sy <= 0; sxx <= 0; sxy <= 0; syy <= 0; end
        else if (sample != prev) begin
            n <= n + 1; sx <= sx + x; sy <= sy + y;
            sxx <= sxx + {32'b0, xx}; syy <= syy + {32'b0, yy}; sxy <= sxy + {{32{xy[31]}}, xy};
        end
    end
    assign n_out = n;
    assign sx_out = sx; assign sy_out = sy; assign sxx_out = sxx; assign sxy_out = sxy; assign syy_out = syy;
endmodule
`default_nettype wire
