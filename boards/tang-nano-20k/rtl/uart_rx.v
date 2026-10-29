// Hand-written board glue: an 8N1 UART receiver. `valid` is one clock wide.
`timescale 1ns/1ps
`default_nettype none
module uart_rx #(
    parameter CLKS_PER_BIT = 234
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       rx,
    output reg        valid,
    output reg  [7:0] data
);
    reg        rx_q1, rx_q2;
    reg [1:0]  st;           // 0 idle, 1 start bit, 2 data bits, 3 stop bit
    reg [15:0] cnt;
    reg [2:0]  bit_i;
    always @(posedge clk) begin
        rx_q1 <= rx; rx_q2 <= rx_q1; valid <= 1'b0;
        if (!rst_n) begin st <= 2'd0; cnt <= 16'd0; bit_i <= 3'd0; data <= 8'h0; end
        else case (st)
            2'd0: if (!rx_q2) begin st <= 2'd1; cnt <= 16'd0; end
            2'd1: if (cnt == CLKS_PER_BIT/2 - 1) begin
                      cnt <= 16'd0;
                      if (!rx_q2) begin st <= 2'd2; bit_i <= 3'd0; end else st <= 2'd0;   // a glitch, not a start bit
                  end else cnt <= cnt + 16'd1;
            2'd2: if (cnt == CLKS_PER_BIT - 1) begin
                      cnt <= 16'd0; data <= {rx_q2, data[7:1]};
                      if (bit_i == 3'd7) st <= 2'd3; else bit_i <= bit_i + 3'd1;
                  end else cnt <= cnt + 16'd1;
            2'd3: if (cnt == CLKS_PER_BIT - 1) begin
                      cnt <= 16'd0; st <= 2'd0;
                      if (rx_q2) valid <= 1'b1;   // a byte with a bad stop bit is dropped
                  end else cnt <= cnt + 16'd1;
        endcase
    end
endmodule
`default_nettype wire
