// Test bench of the statistics design, test code only: sends three (x, y) pairs and checks the sums.
`timescale 1ns/1ps
module stats_tb;
    localparam CLK_NS = 37; localparam BIT_NS = 234 * CLK_NS;
    reg clk = 0; always #(CLK_NS/2) clk = ~clk;
    reg host_tx = 1'b1; wire host_rx; wire [5:0] led;
    top #(.CLKS_PER_BIT(234)) dut (.clk(clk), .uart_rx(host_tx), .uart_tx(host_rx), .led(led));
    reg [7:0] q [0:63]; integer qi = 0, qo = 0;
    initial begin #(10*CLK_NS); forever begin : l integer i; reg [7:0] v; @(negedge host_rx); #(BIT_NS/2);
        for (i=0;i<8;i=i+1) begin #(BIT_NS); v[i]=host_rx; end #(BIT_NS); q[qi%64]=v; qi=qi+1; end end
    task send(input [7:0] b); integer i; begin host_tx=0; #(BIT_NS); for(i=0;i<8;i=i+1) begin host_tx=b[i]; #(BIT_NS); end host_tx=1; #(BIT_NS); end endtask
    task get(output [7:0] b); begin while (qo==qi) #(CLK_NS); b=q[qo%64]; qo=qo+1; end endtask
    task wr(input [31:0] off, input [31:0] d); reg [7:0] r; integer i; begin send("W");
        for (i=3;i>=0;i=i-1) send((32'h40000000+off) >> (8*i)); for (i=3;i>=0;i=i-1) send(d >> (8*i)); get(r); end endtask
    task rd(input [31:0] off, output [31:0] d); reg [7:0] r, b3, b2, b1, b0; integer i; begin send("R");
        for (i=3;i>=0;i=i-1) send((32'h40000000+off) >> (8*i)); get(r); get(b3); get(b2); get(b1); get(b0); d = {b3,b2,b1,b0}; end endtask
    integer pass = 0, fail = 0;
    task chk(input [8*40-1:0] what, input integer got, input integer want);
        begin if (got == want) begin pass = pass + 1; $display("PASS  %0s = %0d", what, got); end
              else begin fail = fail + 1; $display("FAIL  %0s = %0d, wanted %0d", what, got, want); end end
    endtask
    reg [31:0] v; integer tog;
    task sample(input integer x, input integer y);
        begin tog = tog ^ 1; wr('h04, (tog << 31) | ((y & 32'h7FFF) << 16) | (x & 32'hFFFF)); end
    endtask
    function integer sx32(input [31:0] w); sx32 = w; endfunction
    initial begin
        #(40*CLK_NS);
        tog = 0;
        wr('h00, 1); wr('h00, 0);
        sample(1, 2); sample(-3, 4); sample(100, -50); sample(100, -50);   // the last is a repeated pair: TOG makes it count
        rd('h08, v); chk("n", v, 4);
        rd('h0C, v); chk("sx low", v, 198);
        rd('h10, v); chk("sx high (sign extension of a positive sum)", v, 0);
        rd('h14, v); chk("sy low (-94)", v, 32'hFFFFFFA2);
        rd('h18, v); chk("sy high (sign extension of a negative sum)", v, 32'hFFFFFFFF);
        rd('h1C, v); chk("sxx low", v, 20010);
        rd('h24, v); chk("sxy low (-10010 = 2 - 12 - 5000 - 5000)", v, 32'hFFFFD8E6);
        rd('h28, v); chk("sxy high", v, 32'hFFFFFFFF);
        rd('h2C, v); chk("syy low", v, 5020);
        wr('h00, 1); wr('h00, 0); rd('h08, v); chk("n after clear", v, 0);
        $display("RESULT: %0d passed, %0d failed", pass, fail);
        $finish;
    end
endmodule
