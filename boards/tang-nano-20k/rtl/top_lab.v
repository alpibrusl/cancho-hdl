// Hand-written board glue: top level of the lab design (rtl/lab.v behind the generated block of lab/lab.chw and the UART bridge).
// The six LEDs show the sequencer's output pins (active low).
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
    wire [31:0] r_ctrl, r_an_pop, r_seq_addr, r_seq_time, r_seq_mask, r_seq_load, r_seq_len, r_hist_in, r_hist_sel;
    wire [31:0] i_an_status, i_an_ts, i_an_val, i_seq_status, i_hist_count, i_hist_total;
    wire [31:0] unused_an_status, unused_an_ts, unused_an_val, unused_seq_status, unused_hist_count, unused_hist_total;
    wire [5:0]  seq_pins;
    uart_axil_bridge #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_bridge (
        .clk(clk), .rst_n(rst_n), .rx(uart_rx), .tx(uart_tx),
        .awaddr(awaddr), .awvalid(awvalid), .awready(awready), .wdata(wdata), .wstrb(wstrb), .wvalid(wvalid), .wready(wready),
        .bresp(bresp), .bvalid(bvalid), .bready(bready), .araddr(araddr), .arvalid(arvalid), .arready(arready),
        .rdata(rdata), .rresp(rresp), .rvalid(rvalid), .rready(rready));
    lab_axi u_regs (
        .clk(clk), .rst_n(rst_n),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
        .reg_an_status_in(i_an_status), .reg_an_ts_in(i_an_ts), .reg_an_val_in(i_an_val),
        .reg_seq_status_in(i_seq_status), .reg_hist_count_in(i_hist_count), .reg_hist_total_in(i_hist_total),
        .reg_ctrl_out(r_ctrl), .reg_an_pop_out(r_an_pop), .reg_an_status_out(unused_an_status), .reg_an_ts_out(unused_an_ts),
        .reg_an_val_out(unused_an_val), .reg_seq_addr_out(r_seq_addr), .reg_seq_time_out(r_seq_time), .reg_seq_mask_out(r_seq_mask),
        .reg_seq_load_out(r_seq_load), .reg_seq_len_out(r_seq_len), .reg_seq_status_out(unused_seq_status),
        .reg_hist_in_out(r_hist_in), .reg_hist_sel_out(r_hist_sel), .reg_hist_count_out(unused_hist_count),
        .reg_hist_total_out(unused_hist_total));
    lab u_lab (
        .clk(clk), .rst_n(rst_n), .rx_pin(uart_rx), .ctrl(r_ctrl), .an_pop(r_an_pop), .an_status(i_an_status), .an_ts(i_an_ts),
        .an_val(i_an_val), .seq_addr(r_seq_addr), .seq_time(r_seq_time), .seq_mask(r_seq_mask), .seq_load(r_seq_load),
        .seq_len(r_seq_len), .seq_status(i_seq_status), .hist_in(r_hist_in), .hist_sel(r_hist_sel), .hist_count(i_hist_count),
        .hist_total(i_hist_total), .seq_pins(seq_pins));
    assign led = ~seq_pins;
endmodule
`default_nettype wire
