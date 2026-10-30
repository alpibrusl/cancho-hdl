// Test bench of the RAM self-test design, test code only. Writes and reads a byte, then runs the self-test in every pattern.
`timescale 1ns/1ps
module mem_tb;
    localparam CLK_NS = 37; localparam BIT_NS = 234 * CLK_NS;
    reg clk = 0; always #(CLK_NS/2) clk = ~clk;
    reg host_tx = 1'b1; wire host_rx; wire [5:0] led;
    top #(.CLKS_PER_BIT(234)) dut (.clk(clk), .uart_rx(host_tx), .uart_tx(host_rx), .led(led));
    reg [7:0] q [0:63]; integer qi = 0, qo = 0;
    initial begin #(10*CLK_NS); forever begin : l integer i; reg [7:0] v; @(negedge host_rx); #(BIT_NS/2);
        for (i=0;i<8;i=i+1) begin #(BIT_NS); v[i]=host_rx; end #(BIT_NS); q[qi%64]=v; qi=qi+1; end end
    task send(input [7:0] b); integer i; begin host_tx=0; #(BIT_NS); for(i=0;i<8;i=i+1) begin host_tx=b[i]; #(BIT_NS); end host_tx=1; #(BIT_NS); end endtask
    task get(output [7:0] b); begin while (qo==qi) #(CLK_NS); b=q[qo%64]; qo=qo+1; end endtask
    reg [7:0] a, b, c; integer p;
    initial begin
        #(40*CLK_NS);
        send("w"); send(8'h12); send(8'h34); send(8'hA7); get(a); $display("write ack %c", a);
        send("r"); send(8'h12); send(8'h34); get(a); $display("read back %h", a);
        for (p = 0; p < 5; p = p + 1) begin send("b"); send(p); get(a); get(b); get(c); $display("pattern %0d: %c errors %0d", p, a, {b, c}); end
        $finish;
    end
endmodule
