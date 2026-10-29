// Hand-written board glue: top level of the matrix-vector design (rtl/gemv.v behind the generated block of gemv/gemv.chw and the UART
// bridge). The six LEDs show the first row's result, low bits, when done (active low).
`timescale 1ns/1ps
`default_nettype none
module top #(parameter CLKS_PER_BIT = 234) (input wire clk, input wire uart_rx, output wire uart_tx, output wire [5:0] led);
    reg [3:0] rst_cnt = 4'd0;
    wire rst_n = &rst_cnt;
    always @(posedge clk) if (!rst_n) rst_cnt <= rst_cnt + 4'd1;
    wire [31:0] awaddr, wdata, araddr, rdata;
    wire [3:0]  wstrb;
    wire [1:0]  bresp, rresp;
    wire awvalid, awready, wvalid, wready, bvalid, bready, arvalid, arready, rvalid, rready;
    wire [31:0] dim, w_addr, w_data, w_load, x_idx, x_val, x_load, go, y_sel, status, y_val, u0, u1;
    uart_axil_bridge #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_bridge (
        .clk(clk), .rst_n(rst_n), .rx(uart_rx), .tx(uart_tx),
        .awaddr(awaddr), .awvalid(awvalid), .awready(awready), .wdata(wdata), .wstrb(wstrb), .wvalid(wvalid), .wready(wready),
        .bresp(bresp), .bvalid(bvalid), .bready(bready), .araddr(araddr), .arvalid(arvalid), .arready(arready),
        .rdata(rdata), .rresp(rresp), .rvalid(rvalid), .rready(rready));
    gemv_axi u_regs (
        .clk(clk), .rst_n(rst_n),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
        .reg_status_in(status), .reg_y_val_in(y_val),
        .reg_dim_out(dim), .reg_w_addr_out(w_addr), .reg_w_data_out(w_data), .reg_w_load_out(w_load), .reg_x_idx_out(x_idx),
        .reg_x_val_out(x_val), .reg_x_load_out(x_load), .reg_go_out(go), .reg_status_out(u0), .reg_y_sel_out(y_sel), .reg_y_val_out(u1));
    gemv u_gemv (.clk(clk), .rst_n(rst_n), .dim(dim), .w_addr(w_addr), .w_data(w_data), .w_load(w_load), .x_idx(x_idx), .x_val(x_val),
                 .x_load(x_load), .go(go), .y_sel(y_sel), .status(status), .y_val(y_val));
    assign led = ~y_val[5:0];
endmodule
`default_nettype wire
