// Test bench for the behavioral roundtrip of the generated AXI4-Lite register module (tests/behavioral/sv_behavior.py).
// Test code only: nothing here is product logic. It reads bus operations from the file named by +CMDS and prints one
// trace line per operation in the shape of the reference model's trace (`OK`, `OK 0x<8 hex>`, `ERR slverr` for a response
// whose resp is not OKAY, or `ERR timeout`):
//
//   W <addr> <data>    one AXI4-Lite write (wstrb all ones)
//   WS <addr> <data> <strb>   the same with the byte strobes given (hex)
//   R <addr>           one AXI4-Lite read
//   RESET              rst_n low for three clocks
//
// +MODE=strict  a master that follows AXI4-Lite: a valid is held until its ready, then dropped, and the response is
//               waited for after that (AXI4-Lite A3.3: a valid may not depend on the other side's ready).
// +MODE=hold    a master that keeps awvalid/wvalid/arvalid up until the response arrives.
// +TIMEOUT=n    clocks to wait for a response (default 8).
//
// The module under test is instantiated by tests/behavioral/sv_wiring.svh, which the driver writes from the contract:
// it names the module and ties its register outputs off.
`timescale 1ns/1ps
module sv_device_tb;
  reg clk = 0;
  reg rst_n = 0;
  always #5 clk = ~clk;

  reg  [31:0] awaddr = 0, wdata = 0, araddr = 0;
  reg  [3:0]  wstrb = 4'hf;
  reg         awvalid = 0, wvalid = 0, bready = 0, arvalid = 0, rready = 0;
  wire        awready, wready, bvalid, arready, rvalid;
  wire [1:0]  bresp, rresp;
  wire [31:0] rdata;

  `include "sv_wiring.svh"

  integer fd, n, timeout, strict;
  reg [8*64-1:0] op, mode;
  reg [8*1024-1:0] path;
  reg [31:0] a, d; reg [3:0] st;
  reg done;

  task do_reset;
    begin
      @(negedge clk); rst_n = 0; repeat (3) @(negedge clk); rst_n = 1; @(negedge clk);
    end
  endtask

  task do_write(input [31:0] addr, input [31:0] data, input [3:0] strb);
    integer t; reg aw_seen, w_seen, got; reg [1:0] resp;
    begin
      @(negedge clk);
      awaddr = addr; wdata = data; wstrb = strb; awvalid = 1; wvalid = 1; bready = 1;
      got = 0; aw_seen = 0; w_seen = 0;
      for (t = 0; t < timeout && !got; t = t + 1) begin
        @(posedge clk);
        // sampled at the clock edge: what the module shows now is what it showed at that edge. In strict mode a
        // response only counts at an edge after the one where both requests were accepted (AXI4-Lite: the slave
        // waits for the handshake before it asserts BVALID).
        if (bvalid && (!strict || (aw_seen && w_seen))) begin got = 1; resp = bresp; end
        if (awready) aw_seen = 1;
        if (wready) w_seen = 1;
        @(negedge clk);
        if (strict) begin
          if (aw_seen) awvalid = 0;
          if (w_seen) wvalid = 0;
        end
      end
      awvalid = 0; wvalid = 0; bready = 0;
      wstrb = 4'hf;
      if (!got) $display("ERR timeout"); else if (resp != 0) $display("ERR slverr"); else $display("OK");
      @(negedge clk);
    end
  endtask

  task do_read(input [31:0] addr);
    integer t; reg ar_seen, got; reg [31:0] v; reg [1:0] resp;
    begin
      @(negedge clk);
      araddr = addr; arvalid = 1; rready = 1;
      got = 0; ar_seen = 0; v = 0;
      for (t = 0; t < timeout && !got; t = t + 1) begin
        @(posedge clk);
        if (rvalid && (!strict || ar_seen)) begin got = 1; v = rdata; resp = rresp; end
        if (arready) ar_seen = 1;
        @(negedge clk);
        if (strict && ar_seen) arvalid = 0;
      end
      arvalid = 0; rready = 0;
      if (!got) $display("ERR timeout"); else if (resp != 0) $display("ERR slverr"); else $display("OK 0x%08x", v);
      @(negedge clk);
    end
  endtask

  initial begin
    if (!$value$plusargs("TIMEOUT=%d", timeout)) timeout = 8;
    strict = 0;
    if ($value$plusargs("MODE=%s", mode)) if (mode == "strict") strict = 1;
    if (!$value$plusargs("CMDS=%s", path)) begin $display("ERR no +CMDS"); $finish; end
    fd = $fopen(path, "r");
    if (fd == 0) begin $display("ERR cannot open commands"); $finish; end
    do_reset;
    while (!$feof(fd)) begin
      n = $fscanf(fd, "%s", op);
      if (n == 1) begin
        if (op == "W") begin n = $fscanf(fd, " %h %h", a, d); do_write(a, d, 4'hf); end
        else if (op == "WS") begin n = $fscanf(fd, " %h %h %h", a, d, st); do_write(a, d, st); end
        else if (op == "R") begin n = $fscanf(fd, " %h", a); do_read(a); end
        else if (op == "RESET") begin do_reset; $display("OK"); end
      end
    end
    $finish;
  end
endmodule
