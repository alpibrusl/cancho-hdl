// Hand-written board glue: top level of the deadman design. The UART bridge reaches the registers of deadman.chw; `T` returns
// {tripped, torque_ok}. LED 0 is lit while torque is allowed, LED 1 while tripped (active low).
`timescale 1ns/1ps
`default_nettype none
module top #(parameter CLKS_PER_BIT = 234, parameter CLKS_PER_MS = 27000) (input wire clk, input wire uart_rx, output wire uart_tx, output wire [5:0] led);
    reg [3:0] rst_cnt = 4'd0;
    wire rst_n = &rst_cnt;
    always @(posedge clk) if (!rst_n) rst_cnt <= rst_cnt + 4'd1;
    wire [31:0] awaddr, wdata, araddr, rdata, reg_ctrl, reg_timeout, reg_kick;
    wire [3:0]  wstrb;
    wire [1:0]  bresp, rresp;
    wire awvalid, awready, wvalid, wready, bvalid, bready, arvalid, arready, rvalid, rready;
    wire tripped, torque_ok;
    uart_axil_bridge #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_bridge (
        .clk(clk), .rst_n(rst_n), .rx(uart_rx), .status({6'b0, tripped, torque_ok}), .tx(uart_tx),
        .awaddr(awaddr), .awvalid(awvalid), .awready(awready), .wdata(wdata), .wstrb(wstrb), .wvalid(wvalid), .wready(wready),
        .bresp(bresp), .bvalid(bvalid), .bready(bready), .araddr(araddr), .arvalid(arvalid), .arready(arready),
        .rdata(rdata), .rresp(rresp), .rvalid(rvalid), .rready(rready));
    deadman_axi u_regs (
        .clk(clk), .rst_n(rst_n),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
        .reg_ctrl_out(reg_ctrl), .reg_timeout_ms_out(reg_timeout), .reg_kick_out(reg_kick));
    deadman #(.CLKS_PER_MS(CLKS_PER_MS)) u_dm (.clk(clk), .rst_n(rst_n), .enable(reg_ctrl[0]), .timeout_ms(reg_timeout[15:0]),
        .kick_seq(reg_kick[15:0]), .tripped(tripped), .torque_ok(torque_ok));
    assign led = ~{4'b0, tripped, torque_ok};
endmodule
`default_nettype wire
