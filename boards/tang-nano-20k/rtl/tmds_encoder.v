// TMDS 8b/10b encoder (DVI 1.0 section 3.2.3), one channel. Hand-written. de=1: eight bits of pixel data, encoded with the
// running disparity kept in `cnt`; de=0: one of the four control tokens, c = {c1,c0}. The output is registered; send q[0] first.
`timescale 1ns/1ps
`default_nettype none
module tmds_encoder (input wire clk, input wire [7:0] d, input wire [1:0] c, input wire de, output reg [9:0] q);
    wire [3:0] n1d = d[0] + d[1] + d[2] + d[3] + d[4] + d[5] + d[6] + d[7];
    wire use_xnor = (n1d > 4'd4) || (n1d == 4'd4 && !d[0]);
    wire [8:0] qm;
    assign qm[0] = d[0];
    genvar i;
    generate for (i = 1; i < 8; i = i + 1) begin : g
        assign qm[i] = use_xnor ? ~(qm[i-1] ^ d[i]) : (qm[i-1] ^ d[i]);
    end endgenerate
    assign qm[8] = ~use_xnor;
    wire [3:0] n1 = qm[0] + qm[1] + qm[2] + qm[3] + qm[4] + qm[5] + qm[6] + qm[7];
    wire [3:0] n0 = 4'd8 - n1;
    reg signed [5:0] cnt = 6'sd0;
    wire signed [5:0] diff = $signed({2'b00, n1}) - $signed({2'b00, n0});       // n1 - n0
    always @(posedge clk) begin
        if (!de) begin
            cnt <= 6'sd0;
            case (c)
                2'b00: q <= 10'b1101010100;
                2'b01: q <= 10'b0010101011;
                2'b10: q <= 10'b0101010100;
                default: q <= 10'b1010101011;
            endcase
        end else if (cnt == 6'sd0 || n1 == n0) begin
            q <= {~qm[8], qm[8], qm[8] ? qm[7:0] : ~qm[7:0]};
            cnt <= qm[8] ? cnt + diff : cnt - diff;
        end else if ((cnt > 6'sd0 && n1 > n0) || (cnt < 6'sd0 && n0 > n1)) begin
            q <= {1'b1, qm[8], ~qm[7:0]};
            cnt <= cnt + (qm[8] ? 6'sd2 : 6'sd0) - diff;
        end else begin
            q <= {1'b0, qm[8], qm[7:0]};
            cnt <= cnt - (qm[8] ? 6'sd0 : 6'sd2) + diff;
        end
    end
endmodule
`default_nettype wire
