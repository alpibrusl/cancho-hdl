// Test bench of the image-filter design, test code only: a host on the other end of the UART. Sends a 6x5 image in every mode at the
// real bit rate, reading the results as they come (the board answers each pixel), and prints them as hex rows for the reference to judge.
`timescale 1ns/1ps
module img_tb;
    localparam CLK_NS = 37;
    localparam BIT_NS = 234 * CLK_NS;
    reg clk = 0;
    always #(CLK_NS/2) clk = ~clk;
    reg  host_tx = 1'b1;
    wire host_rx;
    wire [5:0] led;
    top #(.CLKS_PER_BIT(234)) dut (.clk(clk), .uart_rx(host_tx), .uart_tx(host_rx), .led(led));
    reg [7:0] rxq [0:4095];
    integer rx_in = 0;
    initial begin
        #(10 * CLK_NS);
        forever begin : rxloop
            integer i; reg [7:0] v;
            @(negedge host_rx);
            #(BIT_NS/2);
            for (i = 0; i < 8; i = i + 1) begin #(BIT_NS); v[i] = host_rx; end
            #(BIT_NS);
            rxq[rx_in % 4096] = v; rx_in = rx_in + 1;
        end
    end
    task send_byte(input [7:0] b);
        integer i;
        begin
            host_tx = 1'b0; #(BIT_NS);
            for (i = 0; i < 8; i = i + 1) begin host_tx = b[i]; #(BIT_NS); end
            host_tx = 1'b1; #(BIT_NS);
        end
    endtask
    integer m, k, base;
    reg [7:0] img [0:29];
    initial begin
        for (k = 0; k < 30; k = k + 1) img[k] = (k * 37 + (k / 6) * 11) % 256;
        #(40 * CLK_NS);
        for (m = 0; m < 5; m = m + 1) begin
            base = rx_in;
            send_byte("I"); send_byte(6); send_byte(5); send_byte(m); send_byte(100);
            for (k = 0; k < 30; k = k + 1) send_byte(img[k]);
            while (rx_in < base + 30) #(CLK_NS);
            $write("MODE %0d:", m);
            for (k = 0; k < 30; k = k + 1) $write(" %0d", rxq[(base + k) % 4096]);
            $write("\n");
        end
        // a long back-to-back stream in pass mode: 200x8 bytes, none may be lost or changed
        base = rx_in;
        send_byte("I"); send_byte(200); send_byte(8); send_byte(0); send_byte(0);
        for (k = 0; k < 1600; k = k + 1) send_byte((k * 7 + k / 200) % 256);
        while (rx_in < base + 1600 && $time < 64'd90000000000) #(CLK_NS);
        begin : chk integer bad; bad = 0;
            for (k = 0; k < 1600 && base + k < rx_in; k = k + 1) if (rxq[(base + k) % 4096] != (k * 7 + k / 200) % 256) bad = bad + 1;
            $display("STREAM received %0d of 1600, different %0d", rx_in - base, bad);
        end
        $display("LEDS %b", led);
        $finish;
    end
endmodule
