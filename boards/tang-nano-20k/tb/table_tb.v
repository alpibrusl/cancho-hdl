// Test bench of the group-by design, test code only: five rows, a filter, three groups.
`timescale 1ns/1ps
module table_tb;
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
    task row(input integer k, input integer val);
        begin tog = tog ^ 1; wr('h08, (tog << 31) | ((val & 32'hFFFF) << 8) | k); end
    endtask
    initial begin
        #(40*CLK_NS);
        tog = 0;
        wr('h00, 1); wr('h00, 0);
        wr('h04, -4 & 32'hFFFF);                       // WHERE v >= -4
        row(1, 10); row(2, -5); row(1, -3); row(1, 7); row(2, 100);
        rd('h24, v); chk("rows received", v, 5);
        rd('h28, v); chk("rows kept (-5 is filtered out)", v, 4);
        wr('h0C, 1);
        rd('h10, v); chk("group 1 count", v, 3);
        rd('h14, v); chk("group 1 sum (10 - 3 + 7)", v, 14);
        rd('h1C, v); chk("group 1 min", v, -3);
        rd('h20, v); chk("group 1 max", v, 10);
        wr('h0C, 2);
        rd('h10, v); chk("group 2 count", v, 1);
        rd('h14, v); chk("group 2 sum", v, 100);
        rd('h1C, v); chk("group 2 min", v, 100);
        wr('h0C, 3);
        rd('h10, v); chk("group 3 count (empty)", v, 0);
        rd('h1C, v); chk("group 3 min (empty: 32767)", v, 32767);
        rd('h20, v); chk("group 3 max (empty: -32768)", v, -32768);
        wr('h00, 1); wr('h00, 0); wr('h0C, 1); rd('h10, v); chk("group 1 count after clear", v, 0);
        $display("RESULT: %0d passed, %0d failed", pass, fail);
        $finish;
    end
endmodule
