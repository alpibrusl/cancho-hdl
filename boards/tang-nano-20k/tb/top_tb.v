// Test bench of the Tang Nano 20K design, test code only: a host on the other end of the UART. It sends the bridge's protocol
// (rtl/uart_axil_bridge.v) at the real bit rate (27 MHz, 234 clocks per bit) and checks the replies and the LED pins.
// Prints one PASS/FAIL line per check and `RESULT: n passed, m failed`.
`timescale 1ns/1ps
module top_tb;
    localparam CLK_NS = 37;                // 27 MHz, rounded to a whole nanosecond
    localparam BIT_NS = 234 * CLK_NS;
    reg clk = 0;
    always #(CLK_NS/2) clk = ~clk;
    reg  host_tx = 1'b1;                   // host -> FPGA (the board's uart_rx pin)
    wire host_rx;                          // FPGA -> host (the board's uart_tx pin)
    wire [5:0] led;
    top #(.CLKS_PER_BIT(234)) dut (.clk(clk), .uart_rx(host_tx), .uart_tx(host_rx), .led(led));

    integer pass = 0, fail = 0;
    task send_byte(input [7:0] b);
        integer i;
        begin
            host_tx = 1'b0; #(BIT_NS);
            for (i = 0; i < 8; i = i + 1) begin host_tx = b[i]; #(BIT_NS); end
            host_tx = 1'b1; #(BIT_NS);
        end
    endtask
    // The host's receiver runs on its own, as a real serial port does: the device may begin its reply before the host has
    // finished sending its own stop bit, so a receiver that only starts when the host asks would miss it.
    reg [7:0] rxq [0:63];
    integer rx_in = 0, rx_out = 0;
    reg started = 0;
    initial begin
        #(10 * CLK_NS); started = 1;
        forever begin : rxloop
            integer i;
            reg [7:0] v;
            @(negedge host_rx);
            #(BIT_NS/2);
            for (i = 0; i < 8; i = i + 1) begin #(BIT_NS); v[i] = host_rx; end
            #(BIT_NS);
            rxq[rx_in % 64] = v; rx_in = rx_in + 1;
        end
    end
    task recv_byte(output [7:0] b);
        begin
            while (rx_out == rx_in) #(CLK_NS);
            b = rxq[rx_out % 64]; rx_out = rx_out + 1;
        end
    endtask
    task send_word(input [31:0] w);
        begin send_byte(w[31:24]); send_byte(w[23:16]); send_byte(w[15:8]); send_byte(w[7:0]); end
    endtask
    task write(input [31:0] a, input [31:0] d, output [7:0] resp);
        begin send_byte("W"); send_word(a); send_word(d); recv_byte(resp); end
    endtask
    task read(input [31:0] a, output [7:0] resp, output [31:0] d);
        reg [7:0] b3, b2, b1, b0;
        begin send_byte("R"); send_word(a); recv_byte(resp); recv_byte(b3); recv_byte(b2); recv_byte(b1); recv_byte(b0); d = {b3, b2, b1, b0}; end
    endtask
    task check(input [8*64-1:0] what, input ok);
        begin
            if (ok) begin pass = pass + 1; $display("PASS  %0s", what); end
            else begin fail = fail + 1; $display("FAIL  %0s", what); end
        end
    endtask

    reg [7:0]  resp;
    reg [31:0] d;
    initial begin
        #(40 * CLK_NS);
        check("LEDs off after reset (active low)", led === 6'b111111);
        write(32'h40000000, 32'h00000005, resp);
        check("write LEDS answers OKAY", resp === 8'h00);
        check("LEDS=0b000101 lights LED0 and LED2 (pins low)", led === 6'b111010);
        read(32'h40000000, resp, d);
        check("read LEDS answers OKAY and 5", resp === 8'h00 && d === 32'h00000005);
        write(32'h40000004, 32'hdeadbeef, resp);
        read(32'h40000004, resp, d);
        check("SCRATCH reads back what was written", resp === 8'h00 && d === 32'hdeadbeef);
        check("writing SCRATCH leaves the LEDs alone", led === 6'b111010);
        read(32'h40000008, resp, d);
        check("a read of an address with no register answers SLVERR", resp === 8'h02 && d === 32'h0);
        write(32'h00000000, 32'hffffffff, resp);
        check("a write below the base answers SLVERR", resp === 8'h02);
        check("and changes nothing", led === 6'b111010);
        write(32'h40000000, 32'h0000003f, resp);
        check("all six LEDs on", led === 6'b000000);
        write(32'h40000000, 32'h00000000, resp);
        check("all six LEDs off", led === 6'b111111);
        $display("RESULT: %0d passed, %0d failed", pass, fail);
        $finish;
    end
    initial begin #(200_000_000); $display("RESULT: timeout"); $finish; end
endmodule
