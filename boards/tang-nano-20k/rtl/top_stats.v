// Hand-written board glue: top level of the statistics design (rtl/stats.v behind the generated block of stats/stats.chw and the UART
// bridge). The six LEDs show the low bits of the sample count (active low).
`timescale 1ns/1ps
`default_nettype none
module top #(parameter CLKS_PER_BIT = 234) (input wire clk, input wire uart_rx, output wire uart_tx, output wire [5:0] led);
    reg [3:0] rst_cnt = 4'd0;
    wire rst_n = &rst_cnt;
    always @(posedge clk) if (!rst_n) rst_cnt <= rst_cnt + 4'd1;
    wire [31:0] awaddr, wdata, araddr, rdata, r_ctrl, r_sample, n;
    wire [63:0] sx, sy, sxx, sxy, syy;
    wire [3:0]  wstrb;
    wire [1:0]  bresp, rresp;
    wire awvalid, awready, wvalid, wready, bvalid, bready, arvalid, arready, rvalid, rready;
    wire [31:0] u [0:12];
    uart_axil_bridge #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_bridge (
        .clk(clk), .rst_n(rst_n), .rx(uart_rx), .tx(uart_tx),
        .awaddr(awaddr), .awvalid(awvalid), .awready(awready), .wdata(wdata), .wstrb(wstrb), .wvalid(wvalid), .wready(wready),
        .bresp(bresp), .bvalid(bvalid), .bready(bready), .araddr(araddr), .arvalid(arvalid), .arready(arready),
        .rdata(rdata), .rresp(rresp), .rvalid(rvalid), .rready(rready));
    stats_axi u_regs (
        .clk(clk), .rst_n(rst_n),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
        .reg_n_in(n), .reg_sx_lo_in(sx[31:0]), .reg_sx_hi_in(sx[63:32]), .reg_sy_lo_in(sy[31:0]), .reg_sy_hi_in(sy[63:32]),
        .reg_sxx_lo_in(sxx[31:0]), .reg_sxx_hi_in(sxx[63:32]), .reg_sxy_lo_in(sxy[31:0]), .reg_sxy_hi_in(sxy[63:32]),
        .reg_syy_lo_in(syy[31:0]), .reg_syy_hi_in(syy[63:32]),
        .reg_ctrl_out(r_ctrl), .reg_sample_out(r_sample),
        .reg_n_out(u[0]), .reg_sx_lo_out(u[1]), .reg_sx_hi_out(u[2]), .reg_sy_lo_out(u[3]), .reg_sy_hi_out(u[4]),
        .reg_sxx_lo_out(u[5]), .reg_sxx_hi_out(u[6]), .reg_sxy_lo_out(u[7]), .reg_sxy_hi_out(u[8]), .reg_syy_lo_out(u[9]), .reg_syy_hi_out(u[10]));
    stats u_stats (.clk(clk), .rst_n(rst_n), .clr(r_ctrl[0]), .sample(r_sample), .n_out(n), .sx_out(sx), .sy_out(sy), .sxx_out(sxx), .sxy_out(sxy), .syy_out(syy));
    assign led = ~n[5:0];
endmodule
`default_nettype wire
