// Test bench of the deadman design, test code only. Time is scaled (CLKS_PER_MS = 2000) so the bench is short; the 234-clock bit
// time is the real one. Arms with a 30 ms timeout, kicks it alive, stops kicking and expects a trip; then re-arm.
`timescale 1ns/1ps
module deadman_tb;
    localparam CLK_NS = 37; localparam BIT_NS = 234 * CLK_NS; localparam MS_NS = 2000 * CLK_NS;
    reg clk = 0; always #(CLK_NS/2) clk = ~clk;
    reg host_tx = 1'b1; wire host_rx; wire [5:0] led;
    top #(.CLKS_PER_BIT(234), .CLKS_PER_MS(2000)) dut (.clk(clk), .uart_rx(host_tx), .uart_tx(host_rx), .led(led));
    reg [7:0] q [0:63]; integer qi = 0, qo = 0;
    initial begin #(10*CLK_NS); forever begin : l integer i; reg [7:0] v; @(negedge host_rx); #(BIT_NS/2);
        for (i=0;i<8;i=i+1) begin #(BIT_NS); v[i]=host_rx; end #(BIT_NS); q[qi%64]=v; qi=qi+1; end end
    task send(input [7:0] b); integer i; begin host_tx=0; #(BIT_NS); for(i=0;i<8;i=i+1) begin host_tx=b[i]; #(BIT_NS); end host_tx=1; #(BIT_NS); end endtask
    task get(output [7:0] b); begin while (qo==qi) #(CLK_NS); b=q[qo%64]; qo=qo+1; end endtask
    task wr(input [31:0] a, input [31:0] d); reg [7:0] r; integer i; begin send("W");
        for (i=3;i>=0;i=i-1) send(a >> (8*i)); for (i=3;i>=0;i=i-1) send(d >> (8*i)); get(r); end endtask
    task st(output [7:0] s); reg [7:0] r, b3, b2, b1; begin send("R"); send(8'h40); send(8'h00); send(8'h00); send(8'h0C); get(r); get(b3); get(b2); get(b1); get(s); end endtask
    reg [7:0] s; integer k;
    initial begin
        #(40*CLK_NS);
        st(s); $display("disarmed: status %b", s[1:0]);
        wr(32'h40000004, 30); wr(32'h40000000, 1);
        st(s); $display("armed: status %b (want 01)", s[1:0]);
        for (k = 1; k <= 8; k = k + 1) begin wr(32'h40000008, k); #(10*MS_NS); end
        st(s); $display("after 8 kicks 10 ms apart: status %b (want 01)", s[1:0]);
        #(60*MS_NS);
        st(s); $display("60 ms without a kick: status %b (want 10)", s[1:0]);
        wr(32'h40000008, 99); st(s); $display("kick after trip: status %b (want 10)", s[1:0]);
        wr(32'h40000000, 0); st(s); $display("disarmed: status %b (want 00)", s[1:0]);
        wr(32'h40000000, 1); st(s); $display("re-armed: status %b (want 01)", s[1:0]);
        $finish;
    end
endmodule
