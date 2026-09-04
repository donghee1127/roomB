% Copyright 2026 Sivers Semiconductors, All right reserved.
% Sivers Semiconductors Proprietary Shared under NDA.
%
% Written by Bye-sah on 02/16/2022
% Based on Mahmood's SP test script on 01/12/2022 for Osprey
% Edited by Bye-sah on 02/28/2022: 0.1sec delay is added before reading DC_VI 
% Edited by Bye-sah on 03/11/2022: Resend the SPI set command if it fails. TempADC is queried in reset state - data_temp_reset
% Edited by Bye-sah on 12/22/2022: Modified for ES2 OSP from "Meas_220311_Func_Osp_Prog_1ch1polEn" 
% Edited by Bye-sah on 02/16/2023: Captune is added
% Edited by Bye-sah on 04/16/2023: Added set_phase_cal, needed for set_rtps_attn() to work when efused IC is programmed.
% Edited by Bye-sah on 04/06/2023: Added get_DC_VI. If it's set to 0, this function will avoid reading the DC VI from the power supplies, which will speed up the measurement. 
% Edited by Bye-sah on 01/31/2024: Modified the script for enabling any channels and any beams. Changed "isequal()~=1" to "~isequal()".
% Edited by Aayush on 06/14/2024: Added a section to specify the cal atn code. Also All the three beams will be given different common attenuation code. This was done to put Daisy chain efuse common atn code and cal atn code. As requested by Daniel on 06/11/2024.
% Edited by Aayush on 5/5/2026: Hardcoded extra bias code for B2
% Modified by Aayush on 5/20/2026: Modified the script and hardcoded some registers which are different from Timberline.
%
% This script programs the ES2 Osprey EVB with any pol, any chan, and any
% beam enabled. All enabled beams will be connected to all enabled channels.
% Enabled channels and pols are defined in "enabled_chan_pol" array
%   - size: 4x2. Rows 1-4 for channels 0-3, respectively. Column 1 for Hpol and 2 for Vpol
%   - value of 0 means disabled and 1 means enabled
% Enabled beams are defined in "enabled_beam" vector
%   - size: 1x4. Columns 1-4 for beams 0-3, respectively.
%   - value of 0 means disabled and 1 means enabled
% The values in "extra_bias_code_manual" apply to all beams
% The values in "c_dist_captune" apply to all beams

function [DC_VI_Prog, data_temp_reset] = Meas_260520_Func_STMPD_Prog_NchNpolNbmEn(get_DC_VI,x,dev,enabled_chan_pol,enabled_beam,PowSup1,PowSup2,bias_FE,bias_IO,bias_fe_ctat,bias_fe_cbias,dist_bias_code_ctat,dist_cbias_manual,extra_bias_code_manual,extra_bias_code_manual_B2,fe_atten_code,fe_phase_code,common_atten_code,cal_atten_code,temp_offset_slope,temp_en_core_bandgap,PD_FE_en,PD_FE_gains,PD_Bm_en,PD_Bm_gains,clk_div,adcEn,chipID,c_fe_captune,c_dist_captune)   
% Set the control for the internal SPDT for Beam2 and Beam3
    if enabled_beam(3) == 1 && enabled_beam(4) == 1
        keyboard; % Beam2 and Beam3 can't be used at the same time!
    elseif enabled_beam(4) == 1
        sw2pol = 2;
    elseif enabled_beam(3) == 1
        sw2pol = 1;
    else
        sw2pol = 0;
    end
    
    % Define internal version of enabled_beam for the 3 internal beams
    enabled_beam_int = enabled_beam(1:3);
    enabled_beam_int(3) = max(enabled_beam(3:4));

    % Initialize output variable
    DC_VI_Prog = zeros(1,12); k_DC = 0;

    % Reset the chip
    x.spi_reset;
    k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end
    
    % Reset phase cal function settings
    dev.set_phase_cal(x,zeros(4,70)); % Needed for set_rtps_attn() to work when efused IC is programmed.

    if 1 % Center Enable
        %center_enables_code = [1 1 1 0 0 sw2pol 0 3 3 0];
        center_enables_code = [1 1 0 0 0 0 0 0 0 0];
        dev.set_center_enables(x, center_enables_code);
        [~,b]=dev.get_center_enables(x);
        while ~isequal(b,center_enables_code)
            warning('SPI returned wrong center enables code'); beep; 
            dev.set_center_enables(x, center_enables_code);
            [~,b]=dev.get_center_enables(x);
        end
        %enables is a 10 vector of
        %[center_ENBG center_ENREG center_PD_override SPI_CHAIN_DISABLE gbl_pwrdn sw2pol(2-bit) pulse_en ds_dout(2-bit) ds_chain(2-bit) efuse_pwrdn_dis]
        k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end
    end

    if 1 % Set the attenuator and phase shifter settings
        %common_gains_code = common_atten_code*[1 1 1];
        common_gains_code = common_atten_code;
        dev.set_common_gains(x,common_gains_code);
        %   gains is a 1x3 vector of 6 bit values
        %   [B0 B1 B2]
        [~,b]=dev.get_common_gains(x);
        while ~isequal(b,common_gains_code)
            warning('SPI returned wrong common gain'); beep;
            dev.set_common_gains(x,common_gains_code);
            [~,b]=dev.get_common_gains(x);
        end
        % k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end
        
        dev.set_cal(x,cal_atten_code);
        %   gains is a 3x4x2 vector of 4 bit values
        %   [1]:    [H0B0 V0B0]     [2]:    [H0B1 V0B1]
        %           [H1B0 V1B0]             [H1B1 V1B1].....
        [~,b]=dev.get_cal(x);
        while isequal(b,cal_atten_code) ~=1
               warning('SPI returned wrong cal atten code'); beep;
               dev.set_cal(x,cal_atten_code);
               [~,b]=dev.get_cal(x);
        end
        % k_DC = k_DC + 1; pause(0.1); DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2);

        beam_table_code=[fe_atten_code fe_phase_code fe_atten_code fe_phase_code fe_atten_code fe_phase_code fe_atten_code fe_phase_code];
        dev.load_beam_table(x,0,1,beam_table_code);
        % load_beam_table(intf, offset, n, values)
        % load n lines beam table starting from offset
        % each line is of the format:
        % [atten0 phase0 atten1 phase1 atten2 phase2 atten3 phase3] from 0 to 3
        [~,b]=dev.read_beam_table(x, 0, 1);
        while ~isequal(b,beam_table_code)
            warning('SPI returned wrong beam table'); beep;
            dev.load_beam_table(x,0,1,beam_table_code);
            [~,b]=dev.read_beam_table(x, 0, 1);
        end
        % k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end
    end
    
    if 1 % Set the FE captune settings
        dev.set_captune(x, c_fe_captune);
        % sets the captune value a 1x4 vector of 16 bit numbers
        % arranged channel 1 to 4
        [~,b] = dev.get_captune(x);
        while ~isequal(b,c_fe_captune)
            warning('SPI returned wrong fe_captune code'); beep;
            dev.set_captune(x,c_fe_captune);
            [~,b] = dev.get_captune(x);
        end
    end

    if 1 % Set the FE bias settings
        fe_bias_code = zeros(8,5);
        for k_ch = 1:4
            for k_pol = 1:2
                if enabled_chan_pol(k_ch,k_pol) == 1
                    bias_PA = bias_FE(k_pol,k_ch,1);
                    bias_DRV = bias_FE(k_pol,k_ch,2);
                    bias_Comb = bias_FE(k_pol,k_ch,3);
                    fe_bias_code(2*(k_ch-1)+k_pol,:)=[bias_PA bias_DRV bias_Comb bias_fe_ctat bias_fe_cbias];
                end
            end
        end
        dev.set_fe_bias(x, fe_bias_code);
        [~,b]=dev.get_fe_bias(x);
        % the bias vector is 8x5 of 6bit bias values
        % [PTAT_ST1 PTAT_ST2 PTAT_ST3 CTAT FE_CBIAS] 
        % with rows ordered CH0_H CH0_v CH1_h CH1_v ...
        while ~isequal(b,fe_bias_code)
           warning('SPI returned fe bias code'); beep;
           dev.set_fe_bias(x, fe_bias_code);
           [~,b]=dev.get_fe_bias(x);
        end
        % k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end
    end

    if 1 % Set active splitter St1 bias settings and DIST captune
        dist_bias_code_ptat = zeros(3,6);
        dist_bias_code_ptat(enabled_beam_int==1,:) = [0 0 0 dist_cbias_manual(1) 0 0] + zeros(size(dist_bias_code_ptat(enabled_beam_int==1,:)));
        dist_bias_code_ptat(enabled_beam_int==1,1) = bias_IO(enabled_beam_int==1,1);
        dev.set_dist_bias(x, dist_bias_code_ptat,dist_bias_code_ctat);
        %the bias vector is 3x6 of 6bit bias values
        %[PTAT_ST1 PTAT_ST2_0 PTAT_ST2_1 cbias_ST1 cbias_ST2_0 cbias_ST2_1] 
        %with rows ordered B0 B1 B2
        %ctat is the DIST_Ctat value
        [~,b,d]=dev.get_dist_bias(x);
        while ~isequal(b,dist_bias_code_ptat) || ~isequal(d,dist_bias_code_ctat)
            warning('SPI returned wrong dist bias code'); beep;
            dev.set_dist_bias(x, dist_bias_code_ptat,dist_bias_code_ctat);
            [~,b,d]=dev.get_dist_bias(x);
        end
        % k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end

        DIST_ct_bin = dec2bin(c_dist_captune,4);
        DIST_Bx_ST_1_Cbias = 1; % The default value of 1 for B0-2 for st1 bottom gm device matches ATE DC measurement spec.
        extra_bias_code = zeros(1,4);
        extra_bias_code(4) = bin2dec([DIST_ct_bin(1:2) DIST_ct_bin(1:2) DIST_ct_bin(1:2)]);
        extra_bias_code(1:3) = bin2dec([DIST_ct_bin(3:4) dec2bin(DIST_Bx_ST_1_Cbias,6)]);
        extra_bias_code(enabled_beam_int==1) = bin2dec([DIST_ct_bin(3:4) dec2bin(extra_bias_code_manual,6)]);
        extra_bias_code(3) = bin2dec([DIST_ct_bin(3:4) dec2bin(extra_bias_code_manual_B2,6)]); % Hard Coding extra bias code for B2.
        dev.set_extra(x, extra_bias_code);
        [~,b]=dev.get_extra(x);
        %the extra vector is 1x4 
        %[extra_B0(<2:0>:DIST_B0_ST_1_Cbias, <5:3>:DIST_B0_Tbias, <7:6>:DIST_B0_ST1_Input_Captune)  extra_b1 extra_B2 extra_misc(2-bit captune between DIST St1 & St2 in each beam, <6:0> for beam<2:0>)] 
        while ~isequal(b,extra_bias_code)
            warning('SPI returned wrong DIST extra code'); beep;
            dev.set_extra(x, extra_bias_code);
            [~,b]=dev.get_extra(x);
        end   
        
        
        % k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end
    end

    if 1 % Program the sensors and ADCs
        dev.set_temp_sensor(x,temp_offset_slope,temp_en_core_bandgap);
            [~,b]=dev.get_temp_cal(x);
            while ~isequal(b,[temp_offset_slope(:)' temp_en_core_bandgap(:)'])
                warning('SPI returned wrong temp sensor code'); beep;
                dev.set_temp_sensor(x,temp_offset_slope,temp_en_core_bandgap);
                [~,b]=dev.get_temp_cal(x);
            end
            k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end
        dev.set_power_detector(x,PD_FE_en,PD_FE_gains);
            [~,b,d]=dev.get_pd_setting(x);
            while ~isequal(b,PD_FE_en) || ~isequal(d,PD_FE_gains)
                warning('SPI returned wrong FE PowDet code'); beep;
                dev.set_power_detector(x,PD_FE_en,PD_FE_gains);
                [~,b,d]=dev.get_pd_setting(x);
            end
            k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end
        dev.set_port_pd(x,PD_Bm_en,PD_Bm_gains);
            [~,b,d]=dev.get_port_pd_setting(x);
            while ~isequal(b,PD_Bm_en) || ~isequal(d,PD_Bm_gains) 
                warning('SPI returned wrong Beam PowDet code'); beep;
                dev.set_port_pd(x,PD_Bm_en,PD_Bm_gains);
                [~,b,d]=dev.get_port_pd_setting(x);
            end
            k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end
        dev.set_adc(x,clk_div,adcEn,1);
            [~,b,d,bd]=dev.get_adc_setting(x);
            while ~isequal(b,clk_div) || ~isequal(d,adcEn) || ~isequal(bd,1)
                warning('SPI returned wrong ADC codes'); beep;
                dev.set_adc(x,clk_div,adcEn,1);
                [~,b,d,bd]=dev.get_adc_setting(x);
            end
            k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end
    end

    if 1 % Read ADCs
        readdata = -1;
        k_try_temp = 0;
        while readdata(1) <= 10 && k_try_temp <= 4
            k_try_temp = k_try_temp + 1;
            x.spi_adc_capture(chipID); x.spi_adc_capture(chipID);
            [~,readdata] = dev.get_adc_val(x);
            data_temp_reset = readdata(1);
        end
    end

    if 1 % Quad Enable
        quad_en_code = zeros(4,3);
        dummy = '000'; dummy(fliplr(enabled_beam_int==1)) = '1'; % Beam 2, 1, 0
        for k_ch = 1:4
            if max(enabled_chan_pol(k_ch,:)) == 1
                quad_en_code(k_ch,:) = [1 1 0]; % Both H and V must be connected to at least one beam input
                for k_pol = 1:2
                    if enabled_chan_pol(k_ch,k_pol) == 1
                        quad_en_code(k_ch,k_pol) = bin2dec(dummy);
                    end
                end
            end
        end
        dev.set_quad_enables(x,quad_en_code);
        %enables is a 4x3 vector of 
        %[quad_H_en(3-bit) quad_V_en(3-bit) pulse_en]
        %the rows are ordered CH0 CH1 CH2 CH3
        [~,b]=dev.get_quad_enables(x);
        while ~isequal(b,quad_en_code)
           warning('SPI returned wrong quad en code'); beep;
           dev.set_quad_enables(x,quad_en_code);
           [~,b]=dev.get_quad_enables(x);
        end
        % k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end
    end

    if 1 % Enable Quad Bias
        quad_pwrdn_code=zeros(4,5);
        for k_ch = 1:4
            if max(enabled_chan_pol(k_ch,:)) == 1
                quad_pwrdn_code(k_ch,:)=[0 1 1 0 0];
            end
        end
        % pwrdn is a 4x5 vector of
       %[quad_pwrdn (6-bit[combiner_V driver_V PA_V combiner_H driver_H PA_H]) quad_pwrdn_override quad_bias_en(1-bit) pulse_en quad_efuse_pwrdn_dis]
        % the rows are ordered CH0 CH1 CH2 CH3
        dev.set_quad_pwrdn(x,quad_pwrdn_code);
        [~,b]=dev.get_quad_pwrdn(x);
        while ~isequal(b,quad_pwrdn_code)
           warning('SPI returned wrong quad pwrdn code'); beep;
           dev.set_quad_pwrdn(x,quad_pwrdn_code);
           [~,b]=dev.get_quad_pwrdn(x);
        end
        k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end
    end
    
    if 1 % Enable Quad Bias & PA+DRV
        quad_pwrdn_code=zeros(4,5);
        for k_ch = 1:4
            dummy = '000000';
            for k_pol = 1:2
                if enabled_chan_pol(k_ch,k_pol) == 1
                    dummy([1:2] + (k_pol-1)*3 ) = '1';
                    quad_pwrdn_code(k_ch,:)=[bin2dec(dummy) 1 1 0 0];
                end
            end
        end
        % pwrdn is a 4x5 vector of      
        %[quad_pwrdn (6-bit[combiner_V driver_V PA_V combiner_H driver_H PA_H]) quad_pwrdn_override quad_bias_en(1-bit) pulse_en quad_efuse_pwrdn_dis]
        
        % the rows are ordered CH0 CH1 CH2 CH3
        dev.set_quad_pwrdn(x,quad_pwrdn_code);dev.set_quad_pwrdn(x,quad_pwrdn_code);
        [~,b]=dev.get_quad_pwrdn(x);
        while ~isequal(b,quad_pwrdn_code)
           warning('SPI returned wrong quad pwrdn code'); beep;
           dev.set_quad_pwrdn(x,quad_pwrdn_code);
           [~,b]=dev.get_quad_pwrdn(x);
        end
        k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end
    end

    if 1 % Enable Quad Bias & PA+DRV & Combiner
        quad_pwrdn_code=zeros(4,5);
        for k_ch = 1:4
            dummy = '000000';
            for k_pol = 1:2
                if enabled_chan_pol(k_ch,k_pol) == 1
                    dummy([1:3] + (k_pol-1)*3) = '1';
                    quad_pwrdn_code(k_ch,:)=[bin2dec(dummy) 1 1 0 0];
                end
            end
        end
        % pwrdn is a 4x5 vector of
       %[quad_pwrdn (6-bit[combiner_V driver_V PA_V combiner_H driver_H PA_H]) quad_pwrdn_override quad_bias_en(1-bit) pulse_en quad_efuse_pwrdn_dis]
        % the rows are ordered CH0 CH1 CH2 CH3
        dev.set_quad_pwrdn(x,quad_pwrdn_code);dev.set_quad_pwrdn(x,quad_pwrdn_code);
        [~,b]=dev.get_quad_pwrdn(x);
        while ~isequal(b,quad_pwrdn_code)
           warning('SPI returned wrong quad pwrdn code'); beep;
           dev.set_quad_pwrdn(x,quad_pwrdn_code);
           [~,b]=dev.get_quad_pwrdn(x);
        end
        k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end
    end

    if 1 % Enable active splitter bias
        beam_enables_code = zeros(3,4);
        beam_enables_code(enabled_beam_int==1,:) = [0 1 0 0] + zeros(size(beam_enables_code(enabled_beam_int==1,:)));
        dev.set_beam_enables(x, beam_enables_code);dev.set_beam_enables(x, beam_enables_code);
        [~,b]=dev.get_beam_enables(x);
        %   enables is a 3x4 vector of
        %   [beam_enables(8-bit,0000_ENCH3_ENCH2_ENCH1_ENCH0) beam_bias_en(1-bit) beam_pwrdn(4-bit,only LSB used) beam_match(1-bit)]
        %   the rows are ordered B0 B1 B2
        while ~isequal(b,beam_enables_code)
           warning('SPI returned wrong beam enables code'); beep;
           dev.set_beam_enables(x, beam_enables_code);
           [~,b]=dev.get_beam_enables(x);
        end
        k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end
    end

    if 1 % Enable active splitter bias & amp
        dummy = '0000'; % ENCH3_ENCH2_ENCH1_ENCH0
        for k_ch = 1:4
            if max(enabled_chan_pol(k_ch,:)) == 1
                dummy(5 - k_ch) = '1';
            end
        end
        beam_enable_code_chan = bin2dec(dummy); 
        beam_enables_code = zeros(3,4);
        beam_enables_code(enabled_beam_int==1,:) = [beam_enable_code_chan 1 1 0] + zeros(size(beam_enables_code(enabled_beam_int==1,:)));
        dev.set_beam_enables(x, beam_enables_code);
        [~,b]=dev.get_beam_enables(x);
        %   enables is a 3x4 vector of
        %   [beam_enables(8-bit,0000_ENCH3_ENCH2_ENCH1_ENCH0) beam_bias_en(1-bit) beam_pwrdn(4-bit,only LSB used) beam_match(1-bit)]
        %   the rows are ordered B0 B1 B2
        while ~isequal(b,beam_enables_code)
           warning('SPI returned wrong beam enables code'); beep;
           dev.set_beam_enables(x, beam_enables_code);
           [~,b]=dev.get_beam_enables(x);
        end
        k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end
    end

    if 1 % Set active splitter St2 bias
        dist_bias_code_ptat(enabled_beam_int==1,:) = [0 0 0 dist_cbias_manual] + zeros(size(dist_bias_code_ptat(enabled_beam_int==1,:)));
        dist_bias_code_ptat(enabled_beam_int==1,1) = bias_IO(enabled_beam_int==1,1);
        k_ch_bin = dec2bin(beam_enable_code_chan,4);
        if str2double(k_ch_bin(1)) || str2double(k_ch_bin(2))
            dist_bias_code_ptat(enabled_beam_int==1,2) = bias_IO(enabled_beam_int==1,2);
        end
        if str2double(k_ch_bin(3)) || str2double(k_ch_bin(4))
            dist_bias_code_ptat(enabled_beam_int==1,3) = bias_IO(enabled_beam_int==1,3);
        end
        dev.set_dist_bias(x, dist_bias_code_ptat,dist_bias_code_ctat);dev.set_dist_bias(x, dist_bias_code_ptat,dist_bias_code_ctat);
        %the bias vector is 3x6 of 6bit bias values
        %[PTAT_ST1 PTAT_ST2_0 PTAT_ST2_1 cbias_ST1 cbias_ST2_0 cbis_ST2_1] 
        %with rows ordered B0 B1 B2
        %ctat is the DIST_Ctat avlue
        [~,b,d]=dev.get_dist_bias(x);
        while ~isequal(b,dist_bias_code_ptat) || ~isequal(d,dist_bias_code_ctat)
            warning('SPI returned wrong dist bias code'); beep;
            dev.set_dist_bias(x, dist_bias_code_ptat,dist_bias_code_ctat);dev.set_dist_bias(x, dist_bias_code_ptat,dist_bias_code_ctat);
            [~,b,d]=dev.get_dist_bias(x);
        end
        k_DC = k_DC + 1; pause(0.1); if get_DC_VI; DC_VI_Prog(k_DC,:) = Record_PS_VI_Return_STMPD(0,PowSup1,PowSup2); end
    end
    
    
        % Externally setting the 104C register
    x.spi_load_address(0,4172);
    x.spi_write(0,3378);
    [s,y] = x.spi_read(0);
    if isequal(y,3378)
        keyboard;
    end

    % Externally setting the 104D register
    x.spi_load_address(0,4173);
    x.spi_write(0,3100);
    [s,y] = x.spi_read(0);
    if isequal(y,3100)
        keyboard;
    end

    % Externally setting the 1050 register
    x.spi_load_address(0,4176);
    x.spi_write(0,1542);
    [s,y] = x.spi_read(0);
    if isequal(y,1542)
        keyboard;
    end

    % Externally setting the 1051 register
    x.spi_load_address(0,4177);
    x.spi_write(0,6);
    [s,y] = x.spi_read(0);
    if isequal(y,6)
        keyboard;
    end

    % Externally setting the 1052 register
    x.spi_load_address(0,4178);
    x.spi_write(0,8);
    [s,y] = x.spi_read(0);
    if isequal(y,8)
        keyboard;
    end


    % Externally setting the 1058 register
    x.spi_load_address(0,4184);
    x.spi_write(0,8);
    [s,y] = x.spi_read(0);
    if isequal(y,8)
        keyboard;
    end

    % Externally setting the 1059 register
    x.spi_load_address(0,4185);
    x.spi_write(0,23);
    [s,y] = x.spi_read(0);
    if isequal(y,23)
        keyboard;
    end


    % Get all the register settings
    if 1
        i = 4096;
        x.spi_load_address(0,i);
        while i<4612
            add(i-4095,1) = upper(string(dec2hex(i)));%dec2hex(i,4);
            [s,mem_dump(i-4095,1)] = x.spi_read(chipID);
            i = i+1;
        end
    end

end