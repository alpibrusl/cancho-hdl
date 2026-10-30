// Hand-written board glue (not generated, not part of the product): a streaming 3x3 image filter behind the UART.
//
// Protocol (host -> board): 'I' W H MODE THR, then W*H pixel bytes, row by row (W, H in 3..255). The board answers each pixel byte with
// one result byte, in order, as the pixels arrive (so the host must read while it writes, or the serial buffers must hold the image).
//   MODE 0 pass | 1 invert (255-p) | 2 threshold (p >= THR ? 255 : 0)
//        3 sobel: min(255, |gx| + |gy|)  over the 3x3 window whose bottom-right pixel is the current one
//        4 box blur: (sum of the 3x3 window * 57) >> 9                  (57/512 is about 1/9)
//   The window of modes 3 and 4 ends at the current pixel, so the result is the image shifted by one pixel down and right;
//   the result is 0 where x < 2 or y < 2 (the window is not full). Other command bytes are ignored.
// Two line buffers of 256 bytes (block RAM when the tool maps them so) hold the rows above.
`timescale 1ns/1ps
`default_nettype none
module img_stream (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       rx_valid,
    input  wire [7:0] rx_data,
    output reg        tx_start,
    output reg  [7:0] tx_data,
    input  wire       tx_busy,
    output reg  [7:0] rows_done
);
    // results wait in a 256-byte FIFO for the serial transmitter: the host sends back to back at the line rate, and the transmitter
    // restarts a few clocks late after each byte, so without it the board falls behind and drops input bytes
    reg [7:0] fifo [0:255];
    reg [8:0] wptr, rptr;
    wire [8:0] fill = wptr - rptr;
    reg [7:0] fifo_q;
    reg       popping;

    // a byte that arrives while the filter is busy is kept (one deep): the host sends at the rate the board answers
    reg       pend_v;
    reg [7:0] pend_d;
    wire      take = pend_v;   // the byte pending at the start of this cycle

    localparam S_CMD = 4'd0, S_W = 4'd1, S_H = 4'd2, S_MODE = 4'd3, S_THR = 4'd4, S_PIX = 4'd5, S_RD = 4'd6, S_CALC = 4'd7,
               S_OUT = 4'd8, S_TX = 4'd9;
    reg [3:0] st;
    reg [7:0] w, h, mode, thr, x, y, px;
    reg [7:0] lb0 [0:255];
    reg [7:0] lb1 [0:255];
    reg [7:0] r0, r1;                 // the pixels above, read from the line buffers
    reg [7:0] c0t, c0m, c0b, c1t, c1m, c1b, c2t, c2m, c2b;   // window columns, oldest first; t = top row, b = bottom row (current)
    reg [7:0] res;

    wire signed [12:0] gx = ($signed({5'd0, c2t}) + 2 * $signed({5'd0, c2m}) + $signed({5'd0, c2b}))
                          - ($signed({5'd0, c0t}) + 2 * $signed({5'd0, c0m}) + $signed({5'd0, c0b}));
    wire signed [12:0] gy = ($signed({5'd0, c0b}) + 2 * $signed({5'd0, c1b}) + $signed({5'd0, c2b}))
                          - ($signed({5'd0, c0t}) + 2 * $signed({5'd0, c1t}) + $signed({5'd0, c2t}));
    wire [12:0] ax = gx[12] ? -gx : gx;
    wire [12:0] ay = gy[12] ? -gy : gy;
    wire [13:0] mag = {1'b0, ax} + {1'b0, ay};
    wire [11:0] sum = c0t + c0m + c0b + c1t + c1m + c1b + c2t + c2m + c2b;
    wire [19:0] boxp = sum * 20'd57;
    wire full = (x >= 8'd2) && (y >= 8'd2);

    always @(posedge clk) begin
        r0 <= lb0[x];                 // synchronous reads: block RAM
        r1 <= lb1[x];
        fifo_q <= fifo[rptr[7:0]];          // synchronous read of the byte at the read pointer
        if (!rst_n) begin
            st <= S_CMD; pend_v <= 1'b0; tx_start <= 1'b0; rows_done <= 8'd0; x <= 8'd0; y <= 8'd0; wptr <= 9'd0; rptr <= 9'd0; popping <= 1'b0;
        end else begin
            tx_start <= 1'b0;
            // transmitter side: a byte is read out of the FIFO (synchronous read), then sent when the transmitter is free
            if (popping) begin tx_data <= fifo_q; tx_start <= 1'b1; popping <= 1'b0; end
            else if (fill != 9'd0 && !tx_busy && !tx_start) begin rptr <= rptr + 9'd1; popping <= 1'b1; end
            case (st)
                S_CMD:  if (take) begin pend_v <= 1'b0; if (pend_d == 8'h49) st <= S_W; end
                S_W:    if (take) begin pend_v <= 1'b0; w <= pend_d; st <= S_H; end
                S_H:    if (take) begin pend_v <= 1'b0; h <= pend_d; st <= S_MODE; end
                S_MODE: if (take) begin pend_v <= 1'b0; mode <= pend_d; st <= S_THR; end
                S_THR:  if (take) begin
                            pend_v <= 1'b0; thr <= pend_d; x <= 8'd0; y <= 8'd0; rows_done <= 8'd0;
                            st <= (w < 8'd3 || h < 8'd3) ? S_CMD : S_PIX;
                        end
                S_PIX:  if (take) begin pend_v <= 1'b0; px <= pend_d; st <= S_RD; end   // x is the read address
                S_RD:   st <= S_CALC;                                                   // r0, r1 now hold the column above
                S_CALC: begin
                            c0t <= c1t; c0m <= c1m; c0b <= c1b;
                            c1t <= c2t; c1m <= c2m; c1b <= c2b;
                            c2t <= r1;  c2m <= r0;  c2b <= px;
                            lb1[x] <= r0; lb0[x] <= px;
                            st <= S_OUT;
                        end
                S_OUT:  begin
                            case (mode)
                                8'd0: res <= px;
                                8'd1: res <= 8'd255 - px;
                                8'd2: res <= (px >= thr) ? 8'd255 : 8'd0;
                                8'd3: res <= !full ? 8'd0 : (mag > 14'd255) ? 8'd255 : mag[7:0];
                                8'd4: res <= !full ? 8'd0 : boxp[16:9];
                                default: res <= px;
                            endcase
                            st <= S_TX;
                        end
                S_TX:   if (fill < 9'd256) begin
                            fifo[wptr[7:0]] <= res; wptr <= wptr + 9'd1;
                            if (x == w - 8'd1) begin
                                x <= 8'd0; rows_done <= rows_done + 8'd1;
                                if (y == h - 8'd1) begin y <= 8'd0; st <= S_CMD; end else begin y <= y + 8'd1; st <= S_PIX; end
                            end else begin x <= x + 8'd1; st <= S_PIX; end
                        end
                default: st <= S_CMD;
            endcase
            if (rx_valid) begin pend_v <= 1'b1; pend_d <= rx_data; end   // last, so a byte arriving as one is taken is kept
        end
    end

endmodule
`default_nettype wire
