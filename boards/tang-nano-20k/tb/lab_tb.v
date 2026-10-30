// Test bench of the lab design, test code only: the host side of the UART at the real bit rate. Counts shots in the histogram, runs a
// three-event sequence while the analyzer watches the sequencer's pins, and drains the analyzer.
`timescale 1ns/1ps
module lab_tb;
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
    reg [31:0] v, t0, t1, t2, c, tp; integer k, tog;
    initial begin
        #(40*CLK_NS);
        // histogram: shots 3 3 5 3 7 5 -> bins 3:3, 5:2, 7:1, total 6
        wr('h00, 4); wr('h00, 0);                      // HIST_CLR pulse
        tog = 0;
        for (k = 0; k < 6; k = k + 1) begin
            tog = tog ^ 1;
            wr('h2C, (tog << 12) | ((k==0||k==1||k==3) ? 3 : (k==2||k==5) ? 5 : 0));
        end
        wr('h30, 3); rd('h34, v); chk("bin 3", v, 3);
        wr('h30, 5); rd('h34, v); chk("bin 5", v, 2);
        wr('h30, 0); rd('h34, v); chk("bin 0", v, 1);
        wr('h30, 4); rd('h34, v); chk("bin 4", v, 0);
        rd('h38, v); chk("total", v, 6);
        wr('h00, 4); wr('h00, 0);                      // clear again: bin 0 (counted into before) and bin 3 must read 0 after it
        wr('h30, 0); rd('h34, v); chk("bin 0 after the second clear", v, 0);
        wr('h30, 3); rd('h34, v); chk("bin 3 after the second clear", v, 0);
        rd('h38, v); chk("total after the second clear", v, 0);
        // sequencer: pins 000001 at tick 1000, 000011 at 3000, 000000 at 4000; analyzer on the sequencer's pins
        wr('h14, 0); wr('h18, 1000); wr('h1C, 1); wr('h20, 1);
        wr('h14, 1); wr('h18, 3000); wr('h1C, 3); wr('h20, 2);
        wr('h14, 2); wr('h18, 4000); wr('h1C, 0); wr('h20, 3);
        wr('h24, 3);
        wr('h00, 32'h11);                              // PROBE_SEL=1, AN_EN=1
        wr('h00, 32'h13);                              // + SEQ_RUN
        #(5000*CLK_NS);
        rd('h28, v); chk("sequencer status (done, index 3)", v, 32'h301);
        wr('h00, 32'h10);                              // AN_EN=0
        rd('h08, v); chk("analyzer entries", v[15:0], 4);
        for (k = 0; k < 4; k = k + 1) begin
            rd('h0C, t0); rd('h10, v);
            if (k == 1) tp = t0;
            if (k == 2) chk("spacing 1 to 2 (ticks)", t0 - tp, 2000);
            if (k == 3) chk("spacing 2 to 3 (ticks)", t0 - tp, 1000);
            tp = t0;
            wr('h04, k + 1);
        end
        $display("RESULT: %0d passed, %0d failed", pass, fail);
        $finish;
    end
endmodule
