// Hand-written board glue: top level of the RAM self-test design. The LEDs show the state machine's state (active low).
`timescale 1ns/1ps
`default_nettype none
module top #(parameter CLKS_PER_BIT = 234) (input wire clk, input wire uart_rx, output wire uart_tx, output wire [5:0] led);
    reg [3:0] rst_cnt = 4'd0;
    wire rst_n = &rst_cnt;
    always @(posedge clk) if (!rst_n) rst_cnt <= rst_cnt + 4'd1;
    wire rv, busy, start;
    wire [7:0] rd, td;
    wire [5:0] st;
    uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_rx (.clk(clk), .rst_n(rst_n), .rx(uart_rx), .valid(rv), .data(rd));
    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_tx (.clk(clk), .rst_n(rst_n), .start(start), .data(td), .tx(uart_tx), .busy(busy));
    mem_test u_mem (.clk(clk), .rst_n(rst_n), .rx_valid(rv), .rx_data(rd), .tx_start(start), .tx_data(td), .tx_busy(busy), .status(st));
    assign led = ~st;
endmodule
`default_nettype wire
