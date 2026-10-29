// Hand-written board glue: the top level of the Tang Nano 20K design. The register block is the module `chw generate --target
// systemverilog boards/tang-nano-20k/leds.chw` writes; the UART bridge lets a host read and write its registers over the board's
// USB serial port. LEDS[5:0] drive the six on-board LEDs (active low: a 1 in the register lights the LED).
`timescale 1ns/1ps
`default_nettype none
module top #(
    parameter CLKS_PER_BIT = 234    // 27 MHz / 115200 = 234.4
) (
    input  wire       clk,          // 27 MHz
    input  wire       uart_rx,      // from the USB-serial bridge
    output wire       uart_tx,      // to the USB-serial bridge
    output wire [5:0] led
);
    reg [3:0] rst_cnt = 4'd0;
    wire rst_n = &rst_cnt;
    always @(posedge clk) if (!rst_n) rst_cnt <= rst_cnt + 4'd1;

    wire [31:0] awaddr, wdata, araddr, rdata, reg_leds, reg_scratch;
    wire [3:0]  wstrb;
    wire [1:0]  bresp, rresp;
    wire awvalid, awready, wvalid, wready, bvalid, bready, arvalid, arready, rvalid, rready;

    uart_axil_bridge #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_bridge (
        .clk(clk), .rst_n(rst_n), .rx(uart_rx), .status(8'h00), .tx(uart_tx),
        .awaddr(awaddr), .awvalid(awvalid), .awready(awready),
        .wdata(wdata), .wstrb(wstrb), .wvalid(wvalid), .wready(wready),
        .bresp(bresp), .bvalid(bvalid), .bready(bready),
        .araddr(araddr), .arvalid(arvalid), .arready(arready),
        .rdata(rdata), .rresp(rresp), .rvalid(rvalid), .rready(rready));

    tang_leds_axi u_regs (
        .clk(clk), .rst_n(rst_n),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
        .reg_leds_out(reg_leds), .reg_scratch_out(reg_scratch));

    assign led = ~reg_leds[5:0];
endmodule
`default_nettype wire
