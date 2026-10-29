// Hand-written board glue (not generated): a byte-stream bridge from a UART to the AXI4-Lite slave that `chw generate --target
// systemverilog` writes. It exists so that a host can read and write the registers of a contract over the USB serial port of a
// board; it is not part of the product and nothing here is claimed verified beyond boards/tang-nano-20k/tb (docs/tang-nano-20k.md).
//
// Protocol, 8N1, bytes in the order shown, addresses and data big-endian (most significant byte first):
//   host -> 'W' a3 a2 a1 a0 d3 d2 d1 d0      one write, all byte strobes set       device -> resp
//   host -> 'R' a3 a2 a1 a0                  one read                              device -> resp d3 d2 d1 d0
// resp is the AXI response: 0x00 OKAY, 0x02 SLVERR (no register at the address, a write to a read-only register, a read of a
// write-only one). Any other command byte is ignored. A request that is never completed by the host leaves the bridge waiting.
`timescale 1ns/1ps
`default_nettype none
module uart_axil_bridge #(
    parameter CLKS_PER_BIT = 234
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        rx,
    output wire        tx,
    output reg  [31:0] awaddr,
    output reg         awvalid,
    input  wire        awready,
    output reg  [31:0] wdata,
    output wire [3:0]  wstrb,
    output reg         wvalid,
    input  wire        wready,
    input  wire [1:0]  bresp,
    input  wire        bvalid,
    output wire        bready,
    output reg  [31:0] araddr,
    output reg         arvalid,
    input  wire        arready,
    input  wire [31:0] rdata,
    input  wire [1:0]  rresp,
    input  wire        rvalid,
    output wire        rready
);
    assign wstrb  = 4'hf;
    assign bready = 1'b1;
    assign rready = 1'b1;

    wire       rx_valid;
    wire [7:0] rx_data;
    uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_rx (.clk(clk), .rst_n(rst_n), .rx(rx), .valid(rx_valid), .data(rx_data));

    reg        tx_start;
    reg  [7:0] tx_data;
    wire       tx_busy;
    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_tx (.clk(clk), .rst_n(rst_n), .start(tx_start), .data(tx_data), .tx(tx), .busy(tx_busy));

    localparam S_CMD = 4'd0, S_ARG = 4'd1, S_GO = 4'd2, S_WA = 4'd3, S_WB = 4'd4, S_RA = 4'd5, S_RR = 4'd6, S_TX = 4'd7;
    reg [3:0]  state;
    reg        is_write;
    reg [3:0]  need, nb;
    reg [63:0] acc;
    reg [39:0] txbuf;
    reg [2:0]  txn;
    reg        tx_wait;   // a byte was handed to the transmitter and it has not yet shown busy

    always @(posedge clk) begin
        tx_start <= 1'b0;
        if (!rst_n) begin
            state <= S_CMD; awvalid <= 1'b0; wvalid <= 1'b0; arvalid <= 1'b0;
            awaddr <= 32'h0; wdata <= 32'h0; araddr <= 32'h0; acc <= 64'h0; nb <= 4'd0; need <= 4'd0;
            is_write <= 1'b0; txbuf <= 40'h0; txn <= 3'd0; tx_wait <= 1'b0; tx_data <= 8'h0;
        end else begin
            case (state)
                S_CMD: if (rx_valid) begin
                    if (rx_data == 8'h57) begin is_write <= 1'b1; need <= 4'd8; nb <= 4'd0; state <= S_ARG; end
                    else if (rx_data == 8'h52) begin is_write <= 1'b0; need <= 4'd4; nb <= 4'd0; state <= S_ARG; end
                end
                S_ARG: if (rx_valid) begin
                    acc <= {acc[55:0], rx_data};
                    nb <= nb + 4'd1;
                    if (nb + 4'd1 == need) state <= S_GO;
                end
                S_GO: begin
                    if (is_write) begin
                        awaddr <= acc[63:32]; wdata <= acc[31:0]; awvalid <= 1'b1; wvalid <= 1'b1; state <= S_WA;
                    end else begin
                        araddr <= acc[31:0]; arvalid <= 1'b1; state <= S_RA;
                    end
                end
                S_WA: if (awready && wready) begin awvalid <= 1'b0; wvalid <= 1'b0; state <= S_WB; end
                S_WB: if (bvalid) begin txbuf <= {6'b0, bresp, 32'h0}; txn <= 3'd1; tx_wait <= 1'b0; state <= S_TX; end
                S_RA: if (arready) begin arvalid <= 1'b0; state <= S_RR; end
                S_RR: if (rvalid) begin txbuf <= {6'b0, rresp, rdata}; txn <= 3'd5; tx_wait <= 1'b0; state <= S_TX; end
                S_TX: begin
                    if (txn == 3'd0) state <= S_CMD;
                    else if (!tx_wait && !tx_busy) begin
                        tx_data <= txbuf[39:32]; tx_start <= 1'b1; tx_wait <= 1'b1;
                        txbuf <= {txbuf[31:0], 8'h0}; txn <= txn - 3'd1;
                    end else if (tx_wait && tx_busy) tx_wait <= 1'b0;
                end
                default: state <= S_CMD;
            endcase
        end
    end
endmodule
`default_nettype wire
