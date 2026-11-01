// Hand-written board glue: top level of the HDMI test pattern. 720x480 at 60 Hz (CEA-861 mode 3, a 27 MHz pixel clock),
// colour bars over a grey ramp, sent as DVI (no InfoFrames) on the board's HDMI connector. Pins and levels: Sipeed's own
// example for this board (TangNano-20K-example/hdmi, `hdmi.cst`): the four pairs on 33/34, 35/36, 37/38, 39/40, LVDS25.
// The 27 MHz crystal feeds a PLL to 135 MHz (5 x the pixel clock); a divider by 5 gives the pixel clock from the same
// edges, and each channel's ten bits per pixel leave through an OSER10 at DDR rate. led[0] is the PLL lock (active low).
// CAM=1: a 320x240 grey frame arrives over the UART (1 Mbaud: CLKS_PER_BIT = 27 clocks of the 27 MHz crystal), is kept in block RAM
// and is shown at 2x in the middle of the picture (the rest is black). A frame is the four bytes A5 5A C3 3C and then 76,800 bytes,
// row by row; a gap of about 40 ms between bytes drops the frame in progress and the receiver looks for a header again.
`timescale 1ns/1ps
`default_nettype none
module top #(parameter SOLID = 1, parameter NATIVE = 1, parameter PHASETEST = 0, parameter CLKPHASE = 2, parameter CAM = 1, parameter CLKS_PER_BIT = 27) (input wire clk, input wire uart_rx, output wire uart_tx,
            output wire tmds_clk_p, output wire tmds_clk_n,
            output wire [2:0] tmds_d_p, output wire [2:0] tmds_d_n,
            output wire [5:0] led);
    wire clk_x5, lock, clk_pix;
    rPLL #(.FCLKIN("27"), .IDIV_SEL(NATIVE ? 1 : 0), .FBDIV_SEL(NATIVE ? 18 : 4), .ODIV_SEL(NATIVE ? 4 : 8), .DEVICE("GW2AR-18C"),
           .DYN_IDIV_SEL("false"), .DYN_FBDIV_SEL("false"), .DYN_ODIV_SEL("false"),
           .PSDA_SEL("0000"), .DUTYDA_SEL("1000"), .CLKOUT_FT_DIR(1'b1), .CLKOUTP_FT_DIR(1'b1),
           .CLKOUT_DLY_STEP(0), .CLKOUTP_DLY_STEP(0), .CLKFB_SEL("internal"), .CLKOUT_BYPASS("false"),
           .CLKOUTP_BYPASS("false"), .CLKOUTD_BYPASS("false"), .DYN_SDIV_SEL(2), .CLKOUTD_SRC("CLKOUT"),
           .CLKOUTD3_SRC("CLKOUT"))
    pll (.CLKOUT(clk_x5), .LOCK(lock), .CLKOUTP(), .CLKOUTD(), .CLKOUTD3(), .RESET(1'b0), .RESET_P(1'b0),
         .CLKIN(clk), .CLKFB(1'b0), .FBDSEL(6'b0), .IDSEL(6'b0), .ODSEL(6'b0), .PSDA(4'b0), .DUTYDA(4'b0), .FDLY(4'b0));
    CLKDIV #(.DIV_MODE("5"), .GSREN("false")) div5 (.CLKOUT(clk_pix), .HCLKIN(clk_x5), .RESETN(lock), .CALIB(1'b0));

    // NATIVE=1: 1024 x 600 on a 1344 x 635 raster, a 51.3 MHz pixel clock (27 MHz x 19 / 2 = 256.5 MHz serial, ODIV 4: VCO 1026 MHz),
    // the mode small 7-inch HDMI panels (1024x600 IPS) are built for; sync pulses negative. NATIVE=0: 720 x 480 on 858 x 525 at
    // 27 MHz (CEA-861 mode 3; serial 135 MHz). The panel's scaler is the first thing to suspect when a picture is not clean.
    localparam HA = NATIVE ? 1024 : 720,  HFP = NATIVE ? 24 : 16,  HS = NATIVE ? 136 : 62, HT = NATIVE ? 1344 : 858;
    localparam VA = NATIVE ? 600 : 480,   VFP = NATIVE ? 3 : 9,    VS = NATIVE ? 6 : 6,    VT = NATIVE ? 635 : 525;
    reg [10:0] hc = 11'd0, vc = 11'd0;
    always @(posedge clk_pix) begin
        if (hc == HT - 1) begin
            hc <= 11'd0;
            vc <= (vc == VT - 1) ? 11'd0 : vc + 11'd1;
        end else hc <= hc + 11'd1;
    end
    wire de = (hc < HA) && (vc < VA);
    wire hs = ~((hc >= HA + HFP) && (hc < HA + HFP + HS));
    wire vs = ~((vc >= VA + VFP) && (vc < VA + VFP + VS));

    // SOLID=1: the whole screen one colour, changing every 128 frames (about 2 s): red, green, blue, white, black, yellow, cyan,
    // magenta. A bring-up pattern: a solid colour survives a bit slip that would scramble bars, and shows which lane is which.
    reg [9:0] frame = 10'd0;
    reg vs_d = 1'b1;
    always @(posedge clk_pix) begin vs_d <= vs; if (vs_d && !vs) frame <= frame + 10'd1; end
    wire [2:0] solid_rgb = frame[9:7] == 3'd0 ? 3'b100 : frame[9:7] == 3'd1 ? 3'b010 : frame[9:7] == 3'd2 ? 3'b001 :
                           frame[9:7] == 3'd3 ? 3'b111 : frame[9:7] == 3'd4 ? 3'b000 : frame[9:7] == 3'd5 ? 3'b110 :
                           frame[9:7] == 3'd6 ? 3'b011 : 3'b101;
    // Otherwise eight bars of 90 pixels (white, yellow, magenta, red, cyan, green, blue, black) in the top three quarters, a
    // grey ramp below: bit 2 of `rgb` is red, 1 green, 0 blue.
    wire [10:0] barw = hc * 8 / HA;               // which eighth of the line
    wire [2:0] bar = barw[2:0];
    wire [2:0] rgb = PHASETEST ? 3'b110 : SOLID ? solid_rgb : ~bar;
    wire ramp = !SOLID && vc >= (VA * 3 / 4);
    wire [10:0] greyw = hc * 256 / HA;
    wire [7:0] grey = greyw[7:0];                 // 0..255 across the line
    wire [7:0] r = !de ? 8'd0 : ramp ? grey : (rgb[2] ? 8'd235 : 8'd16);
    wire [7:0] g = !de ? 8'd0 : ramp ? grey : (rgb[1] ? 8'd235 : 8'd16);
    wire [7:0] b = !de ? 8'd0 : ramp ? grey : (rgb[0] ? 8'd235 : 8'd16);

    // ---- the frame store: written from the UART at 27 MHz, read at the pixel clock (a dual-clock block RAM)
    reg [3:0] rst_cnt = 4'd0;
    wire rst_n = &rst_cnt;
    always @(posedge clk) if (!rst_n) rst_cnt <= rst_cnt + 4'd1;
    wire rv;
    wire [7:0] rd;
    uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_rx (.clk(clk), .rst_n(rst_n), .rx(uart_rx), .valid(rv), .data(rd));
    localparam FW = 320, FH = 240, FN = 76800;
    reg [7:0] mem [0:FN-1];
    reg [16:0] wa = 17'd0;
    reg [2:0] hst = 3'd0;                        // 0..3: header bytes matched; 4: frame data
    reg [20:0] idle = 21'd0;
    reg [7:0] frames = 8'd0;
    reg got = 1'b0;                              // a whole frame has arrived: until then the window shows a ramp
    // Bring-up aid: the board answers on its UART: 'H' for every header matched, 'F' for every frame stored.
    reg [1:0] ans = 2'd0;                        // bit 0: an 'H' is owed, bit 1: an 'F'
    wire tx_busy;
    reg tx_start = 1'b0;
    reg [7:0] tx_data = 8'd0;
    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_tx (.clk(clk), .rst_n(rst_n), .start(tx_start), .data(tx_data), .tx(uart_tx), .busy(tx_busy));
    wire [7:0] hbyte = hst == 3'd0 ? 8'hA5 : hst == 3'd1 ? 8'h5A : hst == 3'd2 ? 8'hC3 : 8'h3C;
    always @(posedge clk) begin
        tx_start <= 1'b0;                        // the answers (set below, so a set wins over this clear)
        if (!tx_busy && !tx_start) begin
            if (ans[0]) begin tx_data <= 8'h48; tx_start <= 1'b1; ans[0] <= 1'b0; end
            else if (ans[1]) begin tx_data <= 8'h46; tx_start <= 1'b1; ans[1] <= 1'b0; end
        end
        idle <= rv ? 21'd0 : (idle == 21'h1FFFFF ? idle : idle + 21'd1);
        if (idle == 21'h1FFFFF) hst <= 3'd0;
        if (rv) begin
            if (hst != 3'd4) begin
                wa <= 17'd0;
                hst <= (rd == hbyte) ? hst + 3'd1 : (rd == 8'hA5 ? 3'd1 : 3'd0);
                if (hst == 3'd3 && rd == hbyte) ans[0] <= 1'b1;
            end else begin
                mem[wa] <= rd;
                wa <= wa + 17'd1;
                if (wa == FN - 1) begin hst <= 3'd0; frames <= frames + 8'd1; got <= 1'b1; ans[1] <= 1'b1; end
            end
        end
    end
    localparam X0 = (HA - 2 * FW) / 2, Y0 = (VA - 2 * FH) / 2;
    wire inwin = (hc >= X0) && (hc < X0 + 2 * FW) && (vc >= Y0) && (vc < Y0 + 2 * FH);
    // The read path, pipelined so that no stage is longer than one adder (the panel's pixel clock is 51.3 MHz):
    // 0 sx, sy; 1 sy*320 as two shifted terms; 2 the address; 3 the RAM; 4 the pixel, black outside the window; the flags run alongside.
    wire [10:0] sx0 = (hc - X0) >> 1;
    wire [10:0] sy0 = (vc - Y0) >> 1;
    reg [10:0] sx1 = 11'd0, sy1 = 11'd0;
    reg [16:0] row2 = 17'd0;
    reg [10:0] sx2 = 11'd0, sx3 = 11'd0, sx4 = 11'd0;
    reg [16:0] raddr = 17'd0;
    reg [7:0] pix = 8'd0;
    reg [4:0] fi = 5'd0, fd = 5'd0, fh = 5'h1F, fv = 5'h1F;     // in-window, de, hs, vs, delayed by 1..5 stages
    reg [7:0] cvr = 8'd0;
    always @(posedge clk_pix) begin
        sx1 <= sx0; sy1 <= sy0;
        row2 <= {sy1, 8'd0} + {sy1, 6'd0};
        sx2 <= sx1; sx3 <= sx2; sx4 <= sx3;
        raddr <= row2 + sx2;
        pix <= mem[raddr];
        fi <= {fi[3:0], inwin}; fd <= {fd[3:0], de}; fh <= {fh[3:0], hs}; fv <= {fv[3:0], vs};
        cvr <= (fd[3] && fi[3]) ? (got ? pix : sx4[7:0]) : 8'd0;      // after the RAM's output multiplexer, before the encoders
    end
    wire de2 = fd[4], hs2 = fh[4], vs2 = fv[4];
    wire [7:0] cv = cvr;
    wire [7:0] pr = CAM ? cv : r, pg = CAM ? cv : g, pb = CAM ? cv : b;
    wire pde = CAM ? de2 : de, phs = CAM ? hs2 : hs, pvs = CAM ? vs2 : vs;

    wire [9:0] t0, t1, t2;
    tmds_encoder e0 (.clk(clk_pix), .d(pb), .c({pvs, phs}), .de(pde), .q(t0));
    tmds_encoder e1 (.clk(clk_pix), .d(pg), .c(2'b00),    .de(pde), .q(t1));
    tmds_encoder e2 (.clk(clk_pix), .d(pr), .c(2'b00),    .de(pde), .q(t2));

    wire [2:0] ser;
    OSER10 s0 (.Q(ser[0]), .D0(t0[0]), .D1(t0[1]), .D2(t0[2]), .D3(t0[3]), .D4(t0[4]), .D5(t0[5]), .D6(t0[6]), .D7(t0[7]), .D8(t0[8]), .D9(t0[9]), .PCLK(clk_pix), .FCLK(clk_x5), .RESET(~lock));
    OSER10 s1 (.Q(ser[1]), .D0(t1[0]), .D1(t1[1]), .D2(t1[2]), .D3(t1[3]), .D4(t1[4]), .D5(t1[5]), .D6(t1[6]), .D7(t1[7]), .D8(t1[8]), .D9(t1[9]), .PCLK(clk_pix), .FCLK(clk_x5), .RESET(~lock));
    OSER10 s2 (.Q(ser[2]), .D0(t2[0]), .D1(t2[1]), .D2(t2[2]), .D3(t2[3]), .D4(t2[4]), .D5(t2[5]), .D6(t2[6]), .D7(t2[7]), .D8(t2[8]), .D9(t2[9]), .PCLK(clk_pix), .FCLK(clk_x5), .RESET(~lock));
    // The TMDS clock word, 0000011111 with D0 first, rotated by CLKPHASE places. Measured by eye on a 7-inch 1024x600 IPS panel (2026-11-01):
    // of phases 0-9 stepped, none was fully clean and 1-3 looked best; of 1, 2, 3 the operator picked 2. The picture is still not
    // perfect: the true-LVDS drive is only 3.5 mA (apycula forces DRIVE 0 for TLVDS_OBUF), so the sampling margin is thin. PHASETEST=1 steps ph through 1..3 every 128 frames, shown on the LEDs, to repeat the sweep.
    reg [3:0] ph = CLKPHASE;
    reg [6:0] fcount = 7'd0;
    always @(posedge clk_pix) if (vs_d && !vs) begin
        fcount <= fcount + 7'd1;
        if (PHASETEST && fcount == 7'd127) ph <= (ph >= 4'd3) ? 4'd1 : ph + 4'd1;
    end
    wire [19:0] kk = {10'b1111100000, 10'b1111100000} >> ph;
    reg [9:0] kreg = 10'b1111100000;
    always @(posedge clk_pix) kreg <= kk[9:0];
    wire ckser;
    OSER10 s_clk (.Q(ckser), .D0(kreg[0]), .D1(kreg[1]), .D2(kreg[2]), .D3(kreg[3]), .D4(kreg[4]), .D5(kreg[5]), .D6(kreg[6]), .D7(kreg[7]), .D8(kreg[8]), .D9(kreg[9]), .PCLK(clk_pix), .FCLK(clk_x5), .RESET(~lock));

    TLVDS_OBUF ob0 (.I(ser[0]), .O(tmds_d_p[0]), .OB(tmds_d_n[0]));
    TLVDS_OBUF ob1 (.I(ser[1]), .O(tmds_d_p[1]), .OB(tmds_d_n[1]));
    TLVDS_OBUF ob2 (.I(ser[2]), .O(tmds_d_p[2]), .OB(tmds_d_n[2]));
    TLVDS_OBUF obc (.I(ckser),  .O(tmds_clk_p),  .OB(tmds_clk_n));
    assign led = PHASETEST ? {2'b11, ~ph} : CAM ? ~{lock, frames[4:0]} : {5'b11111, ~lock};
endmodule
`default_nettype wire
