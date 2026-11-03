// Test bench of the tap design, test code only: a servo bus ping and its reply at 1 Mbaud (27 ticks a bit) on the `tap` pin, the analyzer
// armed and drained over the UART (115200), the bytes decoded from the recorded edges, and the turn-around between the command and the reply
// measured in ticks. The tap pin and the UART are independent: draining must not record the drain.
`timescale 1ns/1ps
module tap_tb;
    localparam CLK_NS = 36;   // even: the clock below is #(CLK_NS/2), so an odd value would run a 36 ns clock against 37 ns arithmetic
    localparam BIT_CLK = 27; localparam BIT_NS = 234 * CLK_NS; localparam TBIT = BIT_CLK * CLK_NS;
    localparam GAP_CLK = 8000;                         // idle between the end of the command and the start of the reply
    reg clk = 0; always #(CLK_NS/2) clk = ~clk;
    reg host_tx = 1'b1; wire host_rx; wire [5:0] led; reg tap = 1'b1;
    top #(.CLKS_PER_BIT(234)) dut (.clk(clk), .uart_rx(host_tx), .uart_tx(host_rx), .tap(tap), .led(led));
    reg [7:0] q [0:63]; integer qi = 0, qo = 0;
    initial begin #(10*CLK_NS); forever begin : l integer i; reg [7:0] v; @(negedge host_rx); #(BIT_NS/2);
        for (i=0;i<8;i=i+1) begin #(BIT_NS); v[i]=host_rx; end #(BIT_NS); q[qi%64]=v; qi=qi+1; end end
    task send(input [7:0] b); integer i; begin host_tx=0; #(BIT_NS); for(i=0;i<8;i=i+1) begin host_tx=b[i]; #(BIT_NS); end host_tx=1; #(BIT_NS); end endtask
    task get(output [7:0] b); begin while (qo==qi) #(CLK_NS); b=q[qo%64]; qo=qo+1; end endtask
    task wr(input [31:0] off, input [31:0] d); reg [7:0] r; integer i; begin send("W");
        for (i=3;i>=0;i=i-1) send((32'h40000000+off) >> (8*i)); for (i=3;i>=0;i=i-1) send(d >> (8*i)); get(r); end endtask
    task rd(input [31:0] off, output [31:0] d); reg [7:0] r, b3, b2, b1, b0; integer i; begin send("R");
        for (i=3;i>=0;i=i-1) send((32'h40000000+off) >> (8*i)); get(r); get(b3); get(b2); get(b1); get(b0); d = {b3,b2,b1,b0}; end endtask
    task bus_byte(input [7:0] b); integer i; begin tap=0; #(TBIT); for(i=0;i<8;i=i+1) begin tap=b[i]; #(TBIT); end tap=1; #(TBIT); end endtask
    integer pass = 0, fail = 0;
    task chk(input [8*40-1:0] what, input integer got, input integer want);
        begin if (got == want) begin pass = pass + 1; $display("PASS  %0s = %0d", what, got); end
              else begin fail = fail + 1; $display("FAIL  %0s = %0d, wanted %0d", what, got, want); end end
    endtask
    reg [31:0] ts [0:599]; reg [7:0] vl [0:599]; reg [7:0] by [0:31]; reg [31:0] bstart [0:31];
    integer n, k, nb, i, j, allowed; reg [31:0] v, t0; reg [7:0] cur;
    reg [7:0] pkt [0:11];
    initial begin
        pkt[0]=8'hFF; pkt[1]=8'hFF; pkt[2]=8'h01; pkt[3]=8'h02; pkt[4]=8'h01; pkt[5]=8'hFB;      // ping, servo 1
        pkt[6]=8'hFF; pkt[7]=8'hFF; pkt[8]=8'h01; pkt[9]=8'h02; pkt[10]=8'h00; pkt[11]=8'hFC;    // its status packet
        #(40*CLK_NS);
        wr('h00, 32'h01);                              // AN_EN=1, PROBE_SEL=0: the tap
        #(200*CLK_NS);
        for (k = 0; k < 6; k = k + 1) bus_byte(pkt[k]);
        #(GAP_CLK*CLK_NS);
        for (k = 6; k < 12; k = k + 1) bus_byte(pkt[k]);
        #(200*CLK_NS);
        wr('h00, 32'h00);                              // AN_EN=0
        rd('h08, v); n = v[15:0]; chk("no overflow", v[16], 0);
        $display("entries: %0d", n);
        for (k = 0; k < n; k = k + 1) begin
            rd('h0C, v); ts[k] = v; rd('h10, v); vl[k] = v[7:0]; wr('h04, k + 1);
        end
        // decode: a falling edge at or after `allowed` starts a byte; the bits are the level 1.5, 2.5, ... bit times later
        nb = 0; allowed = 0;
        for (k = 1; k < n; k = k + 1) begin
            if (vl[k][0] == 0 && vl[k-1][0] == 1 && ts[k] >= allowed) begin
                cur = 0;
                for (i = 0; i < 8; i = i + 1) begin
                    t0 = ts[k] + BIT_CLK * (i + 1) + BIT_CLK / 2;
                    j = k; while (j + 1 < n && ts[j + 1] <= t0) j = j + 1;
                    cur[i] = vl[j][0];
                end
                by[nb] = cur; bstart[nb] = ts[k]; nb = nb + 1; allowed = ts[k] + 10 * BIT_CLK - 5;
            end
        end
        chk("bytes decoded", nb, 12);
        for (k = 0; k < 12; k = k + 1) begin
            if (by[k] === pkt[k]) pass = pass + 1; else begin fail = fail + 1; $display("FAIL  byte %0d = %02x, wanted %02x", k, by[k], pkt[k]); end
        end
        $display("PASS  (12 bytes compared)");
        chk("byte spacing in a packet (ticks)", bstart[1] - bstart[0], 10 * BIT_CLK);
        chk("turn-around, end of command to reply (ticks)", bstart[6] - (bstart[5] + 10 * BIT_CLK), GAP_CLK);
        $display("RESULT: %0d passed, %0d failed", pass, fail);
        $finish;
    end
endmodule
