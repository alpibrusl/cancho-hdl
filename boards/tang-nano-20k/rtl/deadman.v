// Hand-written board glue (not generated): the deadman logic behind the registers of deadman.chw.
// ENABLE=1 arms it. While armed, if no kick (a change of KICK.SEQ) arrives for TIMEOUT_MS milliseconds, `tripped` latches and
// `torque_ok` drops. A trip is cleared only by ENABLE=0. TIMEOUT_MS=0 never trips. Milliseconds are counted from the 27 MHz clock.
`timescale 1ns/1ps
`default_nettype none
module deadman #(parameter CLKS_PER_MS = 27000) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        enable,
    input  wire [15:0] timeout_ms,
    input  wire [15:0] kick_seq,
    output reg         tripped,
    output wire        torque_ok
);
    reg [15:0] kick_prev, age;
    reg [14:0] sub;
    reg        enable_prev;
    assign torque_ok = enable && !tripped;
    always @(posedge clk) begin
        if (!rst_n) begin
            tripped <= 1'b0; age <= 16'd0; sub <= 15'd0; kick_prev <= kick_seq; enable_prev <= 1'b0;
        end else begin
            kick_prev <= kick_seq; enable_prev <= enable;
            if (!enable) begin
                tripped <= 1'b0; age <= 16'd0; sub <= 15'd0;
            end else if (kick_seq != kick_prev || !enable_prev) begin
                age <= 16'd0; sub <= 15'd0;                      // a kick, or the moment of arming, restarts the clock
            end else begin
                if (sub == CLKS_PER_MS - 1) begin
                    sub <= 15'd0;
                    if (age != 16'hFFFF) age <= age + 16'd1;
                end else sub <= sub + 15'd1;
                if (timeout_ms != 16'd0 && age >= timeout_ms) tripped <= 1'b1;
            end
        end
    end
endmodule
`default_nettype wire
