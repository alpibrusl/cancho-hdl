// Hand-written board glue: an 8N1 UART transmitter. `start` for one clock while `busy` is low sends `data`.
`timescale 1ns/1ps
`default_nettype none
module uart_tx #(
    parameter CLKS_PER_BIT = 234
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       start,
    input  wire [7:0] data,
    output reg        tx,
    output wire       busy
);
    reg [9:0]  shift;        // stop, data, start: shifted out from the least significant bit
    reg [3:0]  bits;
    reg [15:0] cnt;
    reg        active;
    assign busy = active;
    always @(posedge clk) begin
        if (!rst_n) begin tx <= 1'b1; active <= 1'b0; cnt <= 16'd0; bits <= 4'd0; shift <= 10'h3ff; end
        else if (!active) begin
            tx <= 1'b1;
            if (start) begin shift <= {1'b1, data, 1'b0}; bits <= 4'd0; cnt <= 16'd0; active <= 1'b1; tx <= 1'b0; end
        end else if (cnt == CLKS_PER_BIT - 1) begin
            cnt <= 16'd0;
            if (bits == 4'd9) begin active <= 1'b0; tx <= 1'b1; end
            else begin shift <= {1'b1, shift[9:1]}; tx <= shift[1]; bits <= bits + 4'd1; end
        end else cnt <= cnt + 16'd1;
    end
endmodule
`default_nettype wire
