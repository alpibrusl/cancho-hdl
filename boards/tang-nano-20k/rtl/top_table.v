// Hand-written board glue: top level of the group-by design (rtl/table_agg.v behind the generated block of table/table.chw and the UART
// bridge). The six LEDs show the number of kept rows, low bits (active low).
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
    wire [31:0] ctrl, filter, row, sel, r_count, r_sum_lo, r_sum_hi, r_min, r_max, rows, kept, u [0:10];
    uart_axil_bridge #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_bridge (
        .clk(clk), .rst_n(rst_n), .rx(uart_rx), .tx(uart_tx),
        .awaddr(awaddr), .awvalid(awvalid), .awready(awready), .wdata(wdata), .wstrb(wstrb), .wvalid(wvalid), .wready(wready),
        .bresp(bresp), .bvalid(bvalid), .bready(bready), .araddr(araddr), .arvalid(arvalid), .arready(arready),
        .rdata(rdata), .rresp(rresp), .rvalid(rvalid), .rready(rready));
    table_axi u_regs (
        .clk(clk), .rst_n(rst_n),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
        .reg_r_count_in(r_count), .reg_r_sum_lo_in(r_sum_lo), .reg_r_sum_hi_in(r_sum_hi), .reg_r_min_in(r_min), .reg_r_max_in(r_max),
        .reg_rows_in(rows), .reg_kept_in(kept),
        .reg_ctrl_out(ctrl), .reg_filter_out(filter), .reg_row_out(row), .reg_sel_out(sel),
        .reg_r_count_out(u[0]), .reg_r_sum_lo_out(u[1]), .reg_r_sum_hi_out(u[2]), .reg_r_min_out(u[3]), .reg_r_max_out(u[4]),
        .reg_rows_out(u[5]), .reg_kept_out(u[6]));
    table_agg u_agg (.clk(clk), .rst_n(rst_n), .clr(ctrl[0]), .filter(filter), .row(row), .sel(sel), .r_count(r_count), .r_sum_lo(r_sum_lo),
                     .r_sum_hi(r_sum_hi), .r_min(r_min), .r_max(r_max), .rows(rows), .kept(kept));
    assign led = ~kept[5:0];
endmodule
`default_nettype wire
