// Hand-written board glue (not generated, not part of the product): an 8192-byte RAM and a built-in self-test, behind the UART.
//   'w' AH AL D     write D at address AH:AL (13 bits)          -> 'k'
//   'r' AH AL       read the byte at AH:AL                      -> the byte
//   'b' P           fill all 8192 bytes with pattern P, then read them back and count the bytes that differ -> 'B' EH EL
//        P=0 address (a[7:0] ^ a[12:8])  1 checkerboard (0x55 / 0xAA by address parity)  2 LFSR sequence  3 all ones  4 all zeros
// Other command bytes are ignored. The RAM is meant to map to block RAM (synchronous read).
`timescale 1ns/1ps
`default_nettype none
module mem_test (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       rx_valid,
    input  wire [7:0] rx_data,
    output reg        tx_start,
    output reg  [7:0] tx_data,
    input  wire       tx_busy,
    output wire [5:0] status
);
    reg [7:0] ram [0:8191];
    reg [12:0] addr;
    reg [7:0]  wdata, rdata;
    reg        we;
    always @(posedge clk) begin
        if (we) ram[addr] <= wdata;
        rdata <= ram[addr];
    end

    reg       pend_v;
    reg [7:0] pend_d;
    wire      take = pend_v;
    localparam S_CMD=0, S_WA1=1, S_WA2=2, S_WD=3, S_RA1=4, S_RA2=5, S_RWAIT=6, S_RWAIT2=7, S_REPLY=8, S_BP=9,
               S_FILL=10, S_VSET=11, S_VADDR=12, S_VCHK=13, S_E1=14, S_E2=15, S_E3=16;
    reg [4:0]  st;
    reg [4:0]  ret;           // where to go after S_REPLY
    reg [7:0]  cmd, reply, pat, lfsr, expect_, hi;
    reg [15:0] errs;
    reg [12:0] i;
    reg [7:0]  nextbyte_lfsr;

    function [7:0] lfsr_next(input [7:0] v);
        lfsr_next = {v[6:0], v[7] ^ v[5] ^ v[4] ^ v[3]};
    endfunction
    function [7:0] pattern(input [7:0] p, input [12:0] a, input [7:0] l);
        case (p)
            8'd0: pattern = a[7:0] ^ {3'b0, a[12:8]};
            8'd1: pattern = a[0] ? 8'hAA : 8'h55;
            8'd2: pattern = l;
            8'd3: pattern = 8'hFF;
            default: pattern = 8'h00;
        endcase
    endfunction

    assign status = {1'b0, st[4:0]};

    always @(posedge clk) begin
        if (!rst_n) begin
            st <= S_CMD; pend_v <= 1'b0; tx_start <= 1'b0; we <= 1'b0;
        end else begin
            tx_start <= 1'b0; we <= 1'b0;
            case (st)
                S_CMD:   if (take) begin pend_v <= 1'b0; cmd <= pend_d;
                             if (pend_d == "w") st <= S_WA1; else if (pend_d == "r") st <= S_RA1; else if (pend_d == "b") st <= S_BP; end
                S_WA1:   if (take) begin pend_v <= 1'b0; addr[12:8] <= pend_d[4:0]; st <= S_WA2; end
                S_WA2:   if (take) begin pend_v <= 1'b0; addr[7:0] <= pend_d; st <= S_WD; end
                S_WD:    if (take) begin pend_v <= 1'b0; wdata <= pend_d; we <= 1'b1; reply <= "k"; ret <= S_CMD; st <= S_REPLY; end
                S_RA1:   if (take) begin pend_v <= 1'b0; addr[12:8] <= pend_d[4:0]; st <= S_RA2; end
                S_RA2:   if (take) begin pend_v <= 1'b0; addr[7:0] <= pend_d; st <= S_RWAIT; end
                S_RWAIT: st <= S_RWAIT2;                       // the address is registered into the RAM, then the data
                S_RWAIT2: begin reply <= rdata; ret <= S_CMD; st <= S_REPLY; end
                S_REPLY: if (!tx_busy) begin tx_data <= reply; tx_start <= 1'b1; st <= ret; end
                S_BP:    if (take) begin pend_v <= 1'b0; pat <= pend_d; i <= 13'd0; lfsr <= 8'h5A; errs <= 16'd0; st <= S_FILL; end
                S_FILL:  begin                                   // write pattern(i) at i, for every i
                             addr <= i; wdata <= pattern(pat, i, lfsr); we <= 1'b1; lfsr <= lfsr_next(lfsr);
                             if (i == 13'd8191) begin i <= 13'd0; lfsr <= 8'h5A; st <= S_VSET; end else i <= i + 13'd1;
                         end
                S_VSET:  begin addr <= i; st <= S_VADDR; end     // present the address; data is there two cycles later
                S_VADDR: begin expect_ <= pattern(pat, i, lfsr); st <= S_VCHK; end
                S_VCHK:  begin
                             if (rdata != expect_) errs <= errs + 16'd1;
                             lfsr <= lfsr_next(lfsr);
                             if (i == 13'd8191) st <= S_E1; else begin i <= i + 13'd1; st <= S_VSET; end
                         end
                S_E1:    begin reply <= "B"; ret <= S_E2; st <= S_REPLY; end
                S_E2:    begin reply <= errs[15:8]; ret <= S_E3; st <= S_REPLY; end
                S_E3:    begin reply <= errs[7:0]; ret <= S_CMD; st <= S_REPLY; end
                default: st <= S_CMD;
            endcase
            if (rx_valid) begin pend_v <= 1'b1; pend_d <= rx_data; end
        end
    end
endmodule
`default_nettype wire
