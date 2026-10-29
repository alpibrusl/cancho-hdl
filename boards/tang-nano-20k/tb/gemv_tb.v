// Test bench of the matrix-vector design, test code only: y = A x for a 3 x 3 matrix.
`timescale 1ns/1ps
module gemv_tb;
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
    reg [31:0] v; integer tog, i, j;
    integer a [0:8];
    integer xv [0:2];
    initial begin
        #(40*CLK_NS);
        a[0]=1; a[1]=2; a[2]=3; a[3]=4; a[4]=5; a[5]=6; a[6]=-7; a[7]=8; a[8]=-9; xv[0]=1; xv[1]=-2; xv[2]=3;
        wr('h00, 32'h303);
        for (i = 0; i < 3; i = i + 1) for (j = 0; j < 3; j = j + 1) begin
            wr('h04, i*32 + j); wr('h08, a[i*3+j] & 255); wr('h0C, i*3 + j + 1);
        end
        for (j = 0; j < 3; j = j + 1) begin wr('h10, j); wr('h14, xv[j] & 255); wr('h18, j + 1); end
        wr('h1C, 1);
        #(300*CLK_NS);
        rd('h20, v); chk("done", v, 1);
        wr('h24, 0); rd('h28, v); chk("y0 (1 - 4 + 9)", v, 6);
        wr('h24, 1); rd('h28, v); chk("y1 (4 - 10 + 18)", v, 12);
        wr('h24, 2); rd('h28, v); chk("y2 (-7 - 16 - 27)", v, -50);
        $display("RESULT: %0d passed, %0d failed", pass, fail);
        $finish;
    end
endmodule
