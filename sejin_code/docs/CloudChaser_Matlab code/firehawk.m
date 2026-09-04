%
%  firehwak.m defines a class for the test and confiurations routines for 
%  programming the Mixcomm Firehawk device via matlab
%  This uses the SPIMIX2629 object which implements the SPI interface 
%  through the C232HM USB 2.0 HI-SPEED TO MPSSE CABLE from FTDI (http://www.ftdichip.com).
%  This class will access SPIMIX2629.m which defines the SPIMIX2629 class
%  the SPIMIX2629.dll which contains the SPI functions and the 
%  libMPSSE_MX.dll from ftdi.
%
%  copyright 2020 Mixcomm, Inc.  All right reserved.
%
% V1.0
% 1/17/22: fixed BEAM_ENABLES_ADDR, and added fe_cbias to fe_biad commaned, FAL
% V1.1
% 1/20/22: fixed set_common_gains so it cycles through gains vector, corrected some comments, FAL
% V1.2
% 1/22/22 : fixed get_beam_pointers and get_beam_set
% V1.3
% 1/24/22: fixed readback of fe gains
% V1.4
% 1/28/2022 added function to write atn and rtps phase code directly
% V1.5
% 2/08/2022 added enables for port power detector and test adc
% V1.6 
% 2/08/2022 added get_rtps
% V1.7
% 2/14/2022 fixed bug in set_power_detector
% V1.8
% 2/17/2022 fixed set_cal and get_cal to handle all 4 channels
% V1.9
% 8/16/2022 fixed beam_set(:,2*beam+hv+1) in get_rtps_attn
% 5/2/2023 added uint32 in get_test_adc_setting

classdef firehawk < handle
   
   properties(Constant, Hidden)
       SHORT_ID_ADDR = 4096;
       UID_ADDR = 4097;
       STATUS_ADDR = 4099;
       DAISY_AMP_ADDR = 4100;
       COMMON_GAIN = 4101;
       BEAM_ENABLES_ADDR = 4104;
       QUAD_ENABLES_ADDR = 4108;
       QUAD_PWRDN_ADDR = 4112;
       CAL_FREQ_ADDR = 4116;
       FE_GAIN_ADDR = 4120;
       PD_EN_ADDR = 4124;
       ADC_SET_ADDR = 4128;
       TEMP_CAL_ADDR = 4130;
       ADC_ADDR = 4131;
       TEST_ADC = 4145;
       PORT_PD = 4146;
       PD_GC_ADDR = 4148;
       BEAM_BIAS_ADDR = 4152;
       DIST_BIAS_ADDR = 4172;
       DAISY_BIAS_ADDR = 4180;
       EXTRA_ADDR	= 4184;
       BEAM_CAL_ADDR = 4188;
       CAPTUNE_ADDR = 4200;
       PHASE_CAL_ADDR = 4204;
       ADC_DBG_ADDR = 4484;
       BEAM_INDEX_DBG = 4492;
       BEAM_SET_DBG = 4516;
       EFUSE_DBG_ADDR = 4540;
       EFUSE_RAW_ADDR = 4572;
       EFUSE_STATUS_ADDR = 4604;
   end

   properties
       chip_id; % chip id for SPI accesses
   end
         
   methods
       function obj = firehawk(id_val)
           if nargin > 0
               obj.chip_id = id_val;
           else
               obj.chip_id = 255;   % default to broadcast ID
           end
       end
        
       function status = set_rtps_attn (obj, intf, atn, ph, ch, beam, hv)
           %set_rtps_attn (obj, intf, atn, ph, ch, beam, hv)
           % set the rtps and attenuator for a specific 
           % atteuator and rtps code
           % this assumes the beam_ptr is set to 0 for all channels and
           % beams
           %
           % intf is the spi interface
           % atn is the attenuator code 0:127
           % ph is the rtps code 0:511
           % ch is the channel 0:3
           % beam is the beam 0:2
           % hv is 0 for horizontal, 1 for vertical
           %
           
           bt_ph = fix(ph/4);
           ph_offset = mod(ph,4);
           ph_cal_addr = (beam + hv*3)*12 + ch;
           status = intf.spi_load_address(obj.chip_id, ch);
           if status ~= 0
               return 
           end
           status = intf.spi_write(obj.chip_id, bt_ph*128 + atn);
           if status ~= 0
               return 
           end
           status = intf.spi_load_address(obj.chip_id, obj.PHASE_CAL_ADDR+ph_cal_addr);
           if status ~= 0
               return 
           end
           status = intf.spi_write(obj.chip_id, 8192+ph_offset);
           if status ~= 0
               return 
           end
           status = intf.spi_load_address(obj.chip_id, obj.PHASE_CAL_ADDR+ph_cal_addr+4);
           if status ~= 0
               return 
           end
           status = intf.spi_write(obj.chip_id, 8192+ph_offset);
           if status ~= 0
               return 
           end
           status = intf.spi_load_address(obj.chip_id, obj.PHASE_CAL_ADDR+ph_cal_addr+8);
           if status ~= 0
               return 
           end
           status = intf.spi_write(obj.chip_id, 8192+ph_offset);
       end
       
       function [status,attn,rtps] = get_rtps_attn (obj, intf, ch, beam, hv)
           %get_rtps_attn (obj, intf, ch, beam, hv)
           % gets the rtps and attenuator for a specific 
           % the specfied channel, beam, and polarization
           % this assumes the beam_ptr is set to 0 for all channels and
           % beams
           %
           % intf is the spi interface
           % ch is the channel 0:3
           % beam is the beam 0:2
           % hv is 0 for horizontal, 1 for vertical
           %
            [status, beam_set] = obj.get_beam_set(intf, ch);
            attn = beam_set(1,2*beam+hv+1);
            rtps = beam_set(2,2*beam+hv+1);
       end
            
       function status =  load_beam_table(obj, intf, offset, n, values)
           %load_beam_table(intf, offset, n, values)
           % load n lines beam table starting from offset
           % each line is of the format:
           % [atten0 phase0 atten1 phase1 atten2 phase2 atten3 phase3]
           % atten and phase values should be integers in the range 0 to
           % 127
           % note: attn 127 will turn off fe beam 
           %
           % intf is the spi interface
           %
           sz = size(values);
           if sz(2) ~= 8
               disp("Beam table values must lines of 8");
               status = -1;
               return
           end
           if sz(1) < n
               fprintf("Only %d lines in table, load will be truncated\n", sz(1));
               n = sz(1);
           end
           if (offset + n)>1024
               n = 1024-offset;
               if n>0
                   fpritnf("Table address overflow, only %n lines will be loaded\n", n);
               else
                   disp("Invalid Offset");
                   status = -1;
                   return
               end
           end
           
           intf.spi_load_address(obj.chip_id, offset*4);
           beam_dat = bitor(bitand(uint32(values(:,[1 3 5 7])),127),bitshift(bitand(uint32(values(:,[2 4 6 8])),127),7));
           for i=1:n
               for k=1:4
                   status = intf.spi_write(obj.chip_id, beam_dat(i,k));
                   if status ~= 0
                       return 
                   end
               end
           end
       end
       
       function [status,values] =  read_beam_table(obj, intf, offset, n)  
           %read_beam_table(intf, offset, n)
           % read n lines beam table starting from offset and return
           % each line is of the format:
           % [atten0 phase0 atten1 phase1 atten2 phase2 atten3 phase3]
           % atten and phase values should be integers in the range 0 to 63
           %
           % intf is the spi interface
           %
           if obj.chip_id == 255
               fprintf("WARNING: Read from Broadcast CHIP ID (0x%02x) will not work\n", obj.chip_id);
           end
           if (offset + n)>1024
               n = 1024-offset;
               if n>0
                   fpritnf("Table address overflow, only %n lines will be loaded\n", n);
               else
                   disp("Invalid Offset");
                   status = -1;
                   return
               end
           end
           
           values = zeros(n, 8);
           intf.spi_load_address(obj.chip_id, offset*4);
           for i=1:n
               for k=1:4
                   [status, beam_dat] = intf.spi_read(obj.chip_id);
                   if status ~= 0
                       return 
                   end
                   values(i,2*k-1) = bitand(beam_dat,127);
                   values(i,2*k) = bitand(bitshift(beam_dat,-7),127);
               end
           end
       end
       
       function status = set_beam_pointers(obj, intf, ch, ptrs)
           %set_beam_pointers(intf, ch, ptrs)
           % set the beam pointers for the channels
           % ch = channel number 0:3
           % ptrs = [B0_H B0_V B1_H B1_V B2_H B2_V]
           %
           % intf is the spi interface
           %
           if nargin <4
               fprintf("Not enough paramaters\n");
               status = -1;
               return
           end
           for i = 1:3
               status = intf.spi_beam_sel(obj.chip_id, ptrs(2*(i-1)+1), (i-1)*8+2*ch);
               if status ~= 0
                    return
               end
               status = intf.spi_beam_sel(obj.chip_id, ptrs(2*i), (i-1)*8+2*ch+1);
               if status ~= 0
                    return
               end
          end
       end

       function [status,ptrs] = get_beam_set(obj, intf, ch)
           %get_beam_pointers(intf)
           % read the beam pointer for the channel
           % ch = channel number 0:3
           % ptrs = [B0_H_att, B0_V_att, B1_H_att, B1_V_att, B2_H_att, B2_V_att
           %         B0_H_phase, B0_V_phase, B1_H_phase, B0_V_phase, B2_H_phase, B0_V_phase]
           %
           % intf is the spi interface
           %
           ptrs = zeros(2,6);
           for i = 1:6
		       status = intf.spi_load_address(obj.chip_id, obj.BEAM_SET_DBG+ch+(i-1)*4);
               if status ~= 0
                    return
               end
               [status, cur_val] = intf.spi_read(obj.chip_id);
               ptrs(1,i) = bitand(cur_val,127);
               ptrs(2,i) = bitand(bitshift(cur_val,-7),511);
               if status ~= 0
                    return
               end
           end
       end

       function [status,ptrs] = get_beam_pointers(obj, intf, ch)
           %get_beam_pointers(intf)
           % read the beam pointer for the channel
           % ch = channel number 0:3
           % ptrs = [B0_H B0_V B1_H B1_V B2_H B2_V]
           %
           % intf is the spi interface
           %
           ptrs = zeros(1,6);
           for i = 1:6
		       status = intf.spi_load_address(obj.chip_id, obj.BEAM_INDEX_DBG+ch+(i-1)*4);
               if status ~= 0
                    return
               end
               [status, cur_val] = intf.spi_read(obj.chip_id);
               if (i<4) 
                   ptrs(1,2*i - 1) = cur_val;
               else
                   ptrs(1,2*(i-3)) = cur_val;
               end
               if status ~= 0
                    return
               end
           end
       end

       function status = update_beams(~, intf)
           %update_beams(obj, intf)
           % pulse the beam update pin
           % intf is the spi interface
           
           status = intf.spi_upd();
       end

       function status = set_daisy_ctrl(obj, intf, ctrl)
           %set_daisy_ctrl(intf, ctrl)
           % ctrl is a 4x4 vector of
           % [ampbypass ampthru china pwrdn chain_bias_pwrdn]
           % the rows are ordered Chain0 Chain1 Chain2 Chain3
           %
           % intf is the SPI interface
           %
           if nargin < 3
               fprintf("Not enough parameters\n");
               status = -1;
               return
           end
           status = intf.spi_load_address(obj.chip_id, obj.DAISY_AMP_ADDR);
           if status ~= 0
               return;
           end
           new_val = 0;
           for i=1:4
		           new_val = new_val + bitshift(ctrl(i,:)*[1 2^4 2^8 2^12]',i-1);
           end
           status = intf.spi_write(obj.chip_id, new_val);
           if status ~= 0
               return;
           end
       end

       function [status,ctrl] = qet_daisy_ctrl(obj, intf)
           %get_daisy_ctrl(intf)
           % returns ctrl is  4x4 vector of
           % [ampbypass ampthru china pwrdn chain_bias_pwrdn]
           % the rows are ordered Chain0 Chain1 Chain2 Chain3
           %
           % intf is the SPI interface
           %
           status = intf.spi_load_address(obj.chip_id, obj.DAISY_AMP_ADDR);
           if status ~= 0
               return;
           end
           [status,cur_val] = intf.spi_read(obj.chip_id);
           if status ~= 0
               return;
           end
           ctrl = zeros(4,4);
           for i=1:4
		           ctrl(i,1) = bitand(bitshift(cur_val,-i),1);
		           ctrl(i,2) = bitand(bitshift(cur_val,-i-4),1);
		           ctrl(i,3) = bitand(bitshift(cur_val,-i-8),1);
		           ctrl(i,4) = bitand(bitshift(cur_val,-i-2),1);
           end
       end

       function status = set_center_enables(obj, intf, enables)
           %set_center_enables(intf, enables)
           % enables is a 10 vector of
           % [centerbias_EN centermirror_EN center_PD_override SPI_CHAIN_DISABLE gbl_pwrdn sw2pol pulse_en ds_dout ds_chain efuse_pwrdn_dis]
           %
           % intf is the SPI interface
           %
           if nargin < 3
               fprintf("Not enough parameters\n");
               status = -1;
               return
           end
           status = intf.spi_load_address(obj.chip_id, obj.BEAM_ENABLES_ADDR);
           if status ~= 0
               return;
           end
           new_val = enables*[1 2 2^2 2^3 2^4 2^5 2^7 2^8 2^10 2^12]';
           status = intf.spi_write(obj.chip_id, new_val);
           if status ~= 0
               return;
           end
       end

       function [status,enables] = get_center_enables(obj, intf)
           %get_center_enables(intf)
           % returns enables  a 10 vector of
           % [center_ENBG center_ENREG center_PD_override SPI_CHAIN_DISABLE gbl_pwrdn sw2pol pulse_en ds_dout ds_chain efuse_pwrdn_dis]
           %
           % intf is the SPI interface
           %
           status = intf.spi_load_address(obj.chip_id, obj.BEAM_ENABLES_ADDR);
           if status ~= 0
               return;
           end
           [status,cur_val] = intf.spi_read(obj.chip_id);
           if status ~= 0
               return;
           end
           enables(1) = bitand(cur_val,1);
           enables(2) = bitand(bitshift(cur_val,-1),1);
           enables(3) = bitand(bitshift(cur_val,-2),1);
           enables(4) = bitand(bitshift(cur_val,-3),1);
           enables(5) = bitand(bitshift(cur_val,-4),1);
           enables(6) = bitand(bitshift(cur_val,-5),3);
           enables(7) = bitand(bitshift(cur_val,-7),1);
           enables(8) = bitand(bitshift(cur_val,-8),3);
           enables(9) = bitand(bitshift(cur_val,-10),3);
           enables(10) = bitand(bitshift(cur_val,-12),1);
       end

       function status = set_beam_enables(obj, intf, enables)
           %set_beam_enables(intf, enables)
           % enables is a 3x4 vector of
           % [beam_enables beam_bias_en beam_pwrdn beam_match]
           % the rows are ordered B0 B1 B2
           %
           % intf is the SPI interface
           %
           if nargin < 3
               fprintf("Not enough parameters\n");
               status = -1;
               return
           end
           status = intf.spi_load_address(obj.chip_id, obj.BEAM_ENABLES_ADDR+1);
           if status ~= 0
               return;
           end
           for i=1:3
	           new_val = enables(i,:)*[1 2^8 2^9 2^14]';
	           status = intf.spi_write(obj.chip_id, new_val);
	           if status ~= 0
	               return;
	           end
	         end
       end

       function [status,enables] = get_beam_enables(obj, intf)
           %get_beam_enables(intf)
           % returns enables is a 3x4 vector of
           % [beam_enables beam_bias_en beam_pwrdn beam_match]
           % the rows are ordered B0 B1 B2
           %
           % intf is the SPI interface
           %
           status = intf.spi_load_address(obj.chip_id, obj.BEAM_ENABLES_ADDR+1);
           if status ~= 0
               return;
           end
           enables = zeros(3,4);
           for i=1:3
		           [status,cur_val] = intf.spi_read(obj.chip_id);
		           if status ~= 0
		               return;
		           end
		           enables(i,1) = bitand(cur_val,255);
		           enables(i,2) = bitand(bitshift(cur_val,-8),1);
		           enables(i,3) = bitand(bitshift(cur_val,-9),31);
		           enables(i,4) = bitand(bitshift(cur_val,-14),1);
           end
       end

       function status = set_quad_enables(obj, intf, enables)
           %set_quad_enables(intf, enables)
           % enables is a 4x3 vector of
           % [quad_H_en quad_V_en pulse_en]
           % the rows are ordered CH0 CH1 CH2 CH3
           %
           % intf is the SPI interface
           %
           if nargin < 3
               fprintf("Not enough parameters\n");
               status = -1;
               return
           end
           status = intf.spi_load_address(obj.chip_id, obj.QUAD_ENABLES_ADDR);
           if status ~= 0
               return;
           end
           for i=1:4
	           new_val = enables(i,:)*[1 2^8 2^11]';
	           status = intf.spi_write(obj.chip_id, new_val);
	           if status ~= 0
	               return;
	           end
	         end
       end

       function [status,enables] = get_quad_enables(obj, intf)
           %get_quad_enables(intf)
           % returns enables is a 4x3 vector of
           % [quad_H_en quad_V_en pulse_en]
           % the rows are ordered CH0 CH1 CH2 CH3
           %
           % intf is the SPI interface
           %
           status = intf.spi_load_address(obj.chip_id, obj.QUAD_ENABLES_ADDR);
           if status ~= 0
               return;
           end
           enables = zeros(4,3);
           for i=1:4
		           [status,cur_val] = intf.spi_read(obj.chip_id);
		           if status ~= 0
		               return;
		           end
		           enables(i,1) = bitand(cur_val,7);
		           enables(i,2) = bitand(bitshift(cur_val,-8),7);
		           enables(i,3) = bitand(bitshift(cur_val,-11),1);
           end
       end

       function status = set_quad_pwrdn(obj, intf, pwrdn)
           %set_quad_pwrdn(intf, pwrdn)
           % pwrdn is a 4x5 vector of
           % [quad_pwrdn quad_pwrdn_override quad_bias_en pulse_en quad_efuse_pwrdn_dis]
           % the rows are ordered CH0 CH1 CH2 CH3
           %
           % intf is the SPI interface
           %
           if nargin < 3
               fprintf("Not enough parameters\n");
               status = -1;
               return
           end
           status = intf.spi_load_address(obj.chip_id, obj.QUAD_PWRDN_ADDR);
           if status ~= 0
               return;
           end
           for i=1:4
	           new_val = pwrdn(i,:)*[1 2^6 2^7 2^8 2^9]';
	           status = intf.spi_write(obj.chip_id, new_val);
	           if status ~= 0
	               return;
	           end
	         end
       end

       function [status,pwrdn] = get_quad_pwrdn(obj, intf)
           %get_quad_pwrdn(intf)
           % returns pwrdn is a 4x5 vector of
           % [quad_pwrdn quad_pwrdn_override quad_bias_en pulse_en quad_efuse_pwrdn_dis]
           % the rows are ordered CH0 CH1 CH2 CH3
           %
           % intf is the SPI interface
           %
           status = intf.spi_load_address(obj.chip_id, obj.QUAD_PWRDN_ADDR);
           if status ~= 0
               return;
           end
           pwrdn = zeros(4,5);
           for i=1:4
		           [status,cur_val] = intf.spi_read(obj.chip_id);
		           if status ~= 0
		               return;
		           end
		           pwrdn(i,1) = bitand(cur_val,63);
		           pwrdn(i,2) = bitand(bitshift(cur_val,-6),1);
		           pwrdn(i,3) = bitand(bitshift(cur_val,-7),1);
		           pwrdn(i,4) = bitand(bitshift(cur_val,-8),1);
		           pwrdn(i,5) = bitand(bitshift(cur_val,-9),1);
           end
       end

       function status = set_cal_freq(obj, intf, freq)
           %set_quad_pwrdn(intf, freq)
           % freq is a 4x4 vector of
           % [B0_cal_f B1_cal_f B2_cal_f pulse_en]
           % the rows are ordered CH0 CH1 CH2 CH3
           %
           % intf is the SPI interface
           %
           if nargin < 3
               fprintf("Not enough parameters\n");
               status = -1;
               return
           end
           status = intf.spi_load_address(obj.chip_id, obj.CAL_FREQ_ADDR);
           if status ~= 0
               return;
           end
           for i=1:4
	           new_val = freq(i,:)*[1 2^3 2^6 2^9]';
	           status = intf.spi_write(obj.chip_id, new_val);
	           if status ~= 0
	               return;
	           end
	         end
       end

       function [status,freq] = get_cal_freq(obj, intf)
           %get_cal_freq(intf)
           % returns freq a 4x4 vector of
           % [B0_cal_f B1_cal_f B2_cal_f pulse_en]
           % the rows are ordered CH0 CH1 CH2 CH3
           %
           % intf is the SPI interface
           %
           status = intf.spi_load_address(obj.chip_id, obj.CAL_FREQ_ADDR);
           if status ~= 0
               return;
           end
           freq = zeros(4,4);
           for i=1:4
		           [status,cur_val] = intf.spi_read(obj.chip_id);
		           if status ~= 0
		               return;
		           end
		           freq(i,1) = bitand(cur_val,7);
		           freq(i,2) = bitand(bitshift(cur_val,-3),7);
		           freq(i,3) = bitand(bitshift(cur_val,-6),7);
		           freq(i,4) = bitand(bitshift(cur_val,-9),1);
           end
       end
       
       function status = set_fe_gains(obj, intf, gains)
           %set_fe_gains(intf, gains)
           % gains is a 4x3 vector of 4 bit values
           % [Gain_H Gain_V pulse_enable]
           % the rows are ordered CH0 CH1 CH2 CH3
           %
           % intf is the SPI interface
           %
           if nargin < 3
               fprintf("Not enough parameters\n");
               status = -1;
               return
           end
           status = intf.spi_load_address(obj.chip_id, obj.FE_GAIN_ADDR);
           if status ~= 0
               return;
           end
           for i=1:4
		       new_val = gains(i,1) + bitshift(gains(i,2),8) + bitshift(gains(i,3),12);
               status = intf.spi_write(obj.chip_id, new_val);
               if status ~= 0
                   return;
               end
           end
       end

       function [status, gains] = get_fe_gains(obj, intf)
           %get_fe_gains(intf)
           % returns gain vector a 4x3 vector of 4 bit values
           % [Gain_H Gain_V pulse_enable]
           % the rows are ordered CH0 CH1 CH2 CH3
           %
           % intf is the SPI interface
           %
           status = intf.spi_load_address(obj.chip_id, obj.FE_GAIN_ADDR);
           if status ~= 0 
               return; 
           end
           gains = zeros(4,3);
           for i=1:4
	           [status,cur_val] = intf.spi_read(obj.chip_id);
	           if status ~= 0 
	               return; 
	           end
	           gains(i,1) = bitand(cur_val,15);
	           gains(i,2) = bitand(bitshift(cur_val,-8),15);
	           gains(i,3) = bitand(bitshift(cur_val,-12),1);
           end
        end 
       
       function status = set_common_gains(obj, intf, gains)
           %set_common_gains(intf, gains)
           % gains is a 1x3 vector of 6 bit values
           % [B0 B1 B2]
           %
           % intf is the SPI interface
           % note this pulse enable bit (64) can be added to B0 gain if desired
           %
           if nargin < 3
               fprintf("Not enough parameters\n");
               status = -1;
               return
           end
           status = intf.spi_load_address(obj.chip_id, obj.COMMON_GAIN);
           if status ~= 0
               return;
           end
           for i=1:3
               status = intf.spi_write(obj.chip_id, gains(i));
               if status ~= 0
                   return;
               end
           end
       end

       function [status, gains, pe] = get_common_gains(obj, intf)
           %get_common_gains(intf)
           % returns gain vector is 1x3 with the 6 bit gain values
           % [B0 B1 B2]
           %
           % intf is the SPI interface
           %
           status = intf.spi_load_address(obj.chip_id, obj.COMMON_GAIN);
           if status ~= 0 
               return; 
           end
           gains = zeros(1,3);
           for i=1:3
	           [status,cur_val] = intf.spi_read(obj.chip_id);
	           if status ~= 0 
	               return; 
	           end
	           gains(i) = bitand(cur_val,63);
	           if i==1
	           	pe = bitshift(cur_val,-6);
	           end
           end
        end 
         
        function status = set_temp_sensor(obj, intf, cal, enable)
            %set_temp_sensor(intf, cal, enable)
            % set the temp sensor calibration values and enables
            % cal = [offset slope], enable = [temp_core temp_bandgap]
            %
            % intf is the SPI interface
            %
            if nargin < 4
               fprintf("Not enough parameters\n");
               status = -1;
               return
            end
            new_val = uint32(cal(1));
            new_val = bitor(new_val, bitshift(cal(2),4));
            new_val = bitor(new_val, enable(1)*256);
            new_val = bitor(new_val, enable(2)*512);
            [status] = intf.spi_load_address(obj.chip_id, obj.TEMP_CAL_ADDR);
            if status ~= 0
                return
            end
            [status] = intf.spi_write(obj.chip_id, new_val);
        end

        function [status, cal_en] = get_temp_cal(obj, intf)
            %get_temp_cal(intf)
            % return a vector with the temp cal regsiter
            % [offset slope temp_core_en temp_bg_en]
            %
            % intf is the SPI interface
            %
            [status] = intf.spi_load_address(obj.chip_id, obj.TEMP_CAL_ADDR);
            if status ~= 0
                return
            end
            [status,cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0
                return
            end
            cal_en = [bitand(cur_val,15) bitand(bitshift(cur_val, -4),15) ...
                bitshift(bitand(cur_val, 256),-8) bitshift(bitand(cur_val, 512),-9)];
        end
        
        function status = set_power_detector(obj, intf, enables, gains)
            %set_power_detector(intf, enables, gains)
            % sets the values for the power detector enables (1x16) and
            % gains (1x8)
            % enables = [PD0H_en PD0H_bg PD0V_en PD0V_bg ... PD3H_en PD3H_bg PD3V_en PD3V_bg]
            % gains are 2 bit values ordered in the same fashion
            %
            % intf is the SPI interface
            %
            if nargin < 4
               fprintf("Not enough parameters\n");
               status = -1;
               return
            end
            for i=1:4
                [status] = intf.spi_load_address(obj.chip_id, obj.PD_EN_ADDR+i-1);
                if status ~= 0
                    return
                end
                [status, cur_val] = intf.spi_read(obj.chip_id);
                if status ~= 0
                    return
                end
	            new_val = uint32(enables(1,(i-1)*4+(1:4))*(2.^(0:3))') + bitand(cur_val, hex2dec('F0'));
                [status] = intf.spi_load_address(obj.chip_id, obj.PD_EN_ADDR+i-1);
                if status ~= 0
                    return
                end
	            status = intf.spi_write(obj.chip_id, new_val);
	            if status ~= 0
	                return
	            end
	          end
            [status] = intf.spi_load_address(obj.chip_id, obj.PD_GC_ADDR);
            if status ~= 0
                return
            end
            for i=1:4
	            new_val = uint32(gains(1,(i-1)*2+(1:2))*[1 4]');
	            status = intf.spi_write(obj.chip_id, new_val);
	            if status ~= 0
	                return
	            end
	          end
        end
        
        function [status, enables, gains] = get_pd_setting(obj, intf)
            %get_pd_setting(obj, intf)
            % returns the power detector enables (1x16) and gains (1x8) settings
            % enables = [PD0H_en PD0H_bg PD0V_en PD0V_bg ... PD3H_en PD3H_bg PD3V_en PD3V_bg]
            % gains are 2 bit values ordered in the same fashion
            %
            % intf is the SPI interface
            %
            [status] = intf.spi_load_address(obj.chip_id, obj.PD_EN_ADDR);
            if status ~= 0
                return
            end
            enables = zeros(1,16);
            gains = zeros(1,8);
            for i=1:4
	            [status, cur_val] = intf.spi_read(obj.chip_id);
	            if status ~= 0
	                return
	            end
	            enables((i-1)*4 + (1:4)) = (bitand(cur_val, uint32(2.^(0:3)))~=0);
	          end
            [status] = intf.spi_load_address(obj.chip_id, obj.PD_GC_ADDR);
            if status ~= 0
                return
            end
            for i=1:4
	            [status, cur_val] = intf.spi_read(obj.chip_id);
	            if status ~= 0
	                return
	            end
	            gains((i-1)*2+1) = (bitand(cur_val, 3));
	            gains((i-1)*2+2) = (bitand(bitshift(cur_val,-2), 3));
	          end
        end

        function status = set_port_pd(obj, intf, enables, gains)
            %set_port_pd(intf, enables, gains)
            % sets the values for the port power detector enables (1x8) and
            % gains (1x4)
            % enables = [PDP0_en PDP0_bg  ... PDP3_en PDP3_bg]
            % gains are 2 bit values ordered in the same fashion
            %
            % intf is the SPI interface
            %
            if nargin < 4
               fprintf("Not enough parameters\n");
               status = -1;
               return
            end
            [status] = intf.spi_load_address(obj.chip_id, obj.PORT_PD);
            if status ~= 0
                return
            end
            new_val = uint32(enables*(2.^(0:7))');
            status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
            new_val = uint32(gains*[1 4 16 64]');
            status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
        end
        
        function [status, enables, gains] = get_port_pd_setting(obj, intf)
            %get_port_pd_setting(obj, intf)
            % returns the port power detector enables (1x8) and gains (1x4) settings
            % enables = [PDP0_en PDP0_bg ... PDP3_en PDP3_bg]
            % gains are 2 bit values ordered in the same fashion
            %
            % intf is the SPI interface
            %
            [status] = intf.spi_load_address(obj.chip_id, obj.PORT_PD);
            if status ~= 0
                return
            end
            enables = zeros(1,8);
            gains = zeros(1,4);
            [status, cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0
                return
            end
            enables = (bitand(cur_val, uint32(2.^(0:7)))~=0);
            [status, cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0
                return
            end
            gains(1) = (bitand(cur_val, 3 ));
            gains(2) = bitshift(bitand(cur_val, 12 ), -2);
            gains(3) = bitshift(bitand(cur_val, 48 ), -4);
            gains(4) = bitshift(bitand(cur_val, 192 ), -6);
        end

        function status = set_test_adc(obj, intf, enable_quad, enables_center, gains, mode)
            %set_test_adc(intf, enable_quad, enables_center, gains, mode)
            % sets the values for the test adc detector enables (1x4) for quads 
            % (1 x 11) for the center, gains (2 bits), and mode (3 bits)
            %
            % intf is the SPI interface
            %
            if nargin < 4
               fprintf("Not enough parameters\n");
               status = -1;
               return
            end
            [status] = intf.spi_load_address(obj.chip_id, obj.TEST_ADC);
            if status ~= 0
                return
            end
            new_val = uint32(enables_center*(2.^(0:10))');
            new_val = new_val + uint32(gains*2^11);
            new_val = new_val + uint32(mode*2^13);
            status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
            for i=0:3
                [status] = intf.spi_load_address(obj.chip_id, obj.PD_EN_ADDR+i);
                if status ~= 0
                    return
                end
                [status, cur_val] = intf.spi_read(obj.chip_id);
                if status ~= 0
                    return
                end
                new_val = bitand(cur_val, 15) + uint32(enable_quad(i+1)*16);
                [status] = intf.spi_load_address(obj.chip_id, obj.PD_EN_ADDR+i);
                if status ~= 0
                    return
                end
                status = intf.spi_write(obj.chip_id, new_val);
                if status ~= 0
                    return
                end
            end
        end
        
        function [status, enable_quad, enables_center, gain, mode] = get_test_adc_setting(obj, intf)
            %get_test_adc_setting(obj, intf)
            % returns the port test_adc detector enable_quad (1x4),
            % enables_center (1x10), gain (2 bit), and mode(3 bit) settings
            %
            % intf is the SPI interface
            %
            enable_quad = zeros(1,4);
            [status] = intf.spi_load_address(obj.chip_id, obj.PD_EN_ADDR);
            if status ~= 0
                return
            end
            for i=0:3
                [status, cur_val] = intf.spi_read(obj.chip_id);
                if status ~= 0
                    return
                end
                enable_quad(i+1) = bitand(bitshift(cur_val,-4), 15);
            end
            [status] = intf.spi_load_address(obj.chip_id, obj.TEST_ADC);
            if status ~= 0
                return
            end
            [status, cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0
                return
            end
            enables_center = (bitand(cur_val,uint32(2.^(0:10)))~=0);
            gain = bitand(bitshift(cur_val, -11),3);
            mode = bitand(bitshift(cur_val, -13),7);
        end

        function status = set_adc (obj, intf, clk, enable, rst)
            %set_adc(intf, clk, enable, rst)
            % sets the clock divider and enable mask for the ADCs
            % clk is a 4 bit value which sets the clock divider = 2^N
            % enable is a 1x14 vector which enables the ADC to start on a
            % capture command
            % rst selects the polarity of the reset applied to ADCs 0 for
            % active low, 1 for active high
            %
            % intf is the SPI interface
            %
            if nargin < 5
               fprintf("Not enough parameters\n");
               status = -1;
               return
            end
            [status] = intf.spi_load_address(obj.chip_id, obj.ADC_SET_ADDR);
            if status ~= 0
                return
            end
            status = intf.spi_write(obj.chip_id, clk);
              if status ~= 0
                  return
              end
            new_val = [enable rst]*(2.^(0:14))';
            [status] = intf.spi_load_address(obj.chip_id, obj.ADC_SET_ADDR+1);
            if status ~= 0
                return
            end
            status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
        end

        function [status, clk, enable, rst] = get_adc_setting(obj, intf)
            %get_adc_setting(obj, intf)
            % returns the adc clk, enable, and reset settings
            % clk is the 4 bit clock divider exponent
            % enable is the 1x9 vector of ADC start enables
            % rst is the reset polarity for teh ADCS
            %
            % intf is the SPI interface
            %
            [status] = intf.spi_load_address(obj.chip_id, obj.ADC_SET_ADDR);
            if status ~= 0
                return
            end
            [status, clk] = intf.spi_read(obj.chip_id);
            if status ~= 0
                return
            end
            [status, cur_val] = intf.spi_read(obj.chip_id);
            enable = (bitand(cur_val, uint32(2.^(0:13)))~=0);
            rst = bitshift(cur_val, -14);
        end

        function status = set_fe_bias(obj, intf, bias)
           %set_fe_bias(intf, bias)
           % the bias vector is 8x5 of 6bit bias values
           % [PTAT_ST1 PTAT_ST2 PTAT_ST3 CTAT FE_CBIAS] 
           % with rows ordered CH0_H CH0_v CH1_h CH1_v ...
           %
           % intf is the SPI interface
           %
           if nargin < 3
               fprintf("Not enough parameters\n");
               status = -1;
               return
           end
           for i = 0:3
           	status = intf.spi_load_address(obj.chip_id, obj.BEAM_BIAS_ADDR+i);
            if status ~= 0
                return
            end
            new_val = bias(2*i+1,1) + bitshift(bias(2*i+1,2),8);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
           	status = intf.spi_load_address(obj.chip_id, obj.BEAM_BIAS_ADDR+i+4);
            if status ~= 0
                return
            end
            new_val = bias(2*i+1,3) + bitshift(bias(2*i+1,4),8);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
           	status = intf.spi_load_address(obj.chip_id, obj.BEAM_BIAS_ADDR+i+8);
            if status ~= 0
                return
            end
            new_val = bias(2*i+2,1) + bitshift(bias(2*i+2,2),8);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
           	status = intf.spi_load_address(obj.chip_id, obj.BEAM_BIAS_ADDR+i+12);
            if status ~= 0
                return
            end
            new_val = bias(2*i+2,3) + bitshift(bias(2*i+2,4),8);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
           	status = intf.spi_load_address(obj.chip_id, obj.BEAM_BIAS_ADDR+i+16);
            if status ~= 0
                return
            end
            new_val = bias(2*i+1,5) + bitshift(bias(2*i+2,5),8);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
           end
        end
        
        function [status, bias] = get_fe_bias(obj, intf)
            %get_bias(obj, intf)
            % returns a 8x5 matirx of 6 bit bias values ordered
            % [PTAT_ST1 PTAT_ST2 PTAT_ST3 CTAT FE_CBIAS] 
            % with rows ordered CH0_H CH0_v CH1_h CH1_v ...
            %
            % intf is the SPI interface
            %
            [status] = intf.spi_load_address(obj.chip_id, obj.BEAM_BIAS_ADDR);
            if status ~= 0
                return
            end
            bias_val = zeros(2, 20);
            for i = 1:20
                [status, cur_val] = intf.spi_read(obj.chip_id);
                if status ~= 0
                    return
                end
                bias_val(1,i) = bitand(cur_val, 63);
                bias_val(2,i) = bitand(bitshift(cur_val,-8),63);
            end
            bias(1,:) = [bias_val(1,1) bias_val(2,1) bias_val(1,5) bias_val(2,5) bias_val(1,17)];
            bias(2,:) = [bias_val(1,9) bias_val(2,9) bias_val(1,13) bias_val(2,13)  bias_val(2,17)];
            bias(3,:) = [bias_val(1,2) bias_val(2,2) bias_val(1,6) bias_val(2,6) bias_val(1,18)];  
            bias(4,:) = [bias_val(1,10) bias_val(2,10) bias_val(1,14) bias_val(2,14) bias_val(2,18)];
            bias(5,:) = [bias_val(1,3) bias_val(2,3) bias_val(1,7) bias_val(2,7) bias_val(1,19)];  
            bias(6,:) = [bias_val(1,11) bias_val(2,11) bias_val(1,15) bias_val(2,15) bias_val(2,19)];
            bias(7,:) = [bias_val(1,4) bias_val(2,4) bias_val(1,8) bias_val(2,8) bias_val(1,20)];  
            bias(8,:) = [bias_val(1,12) bias_val(2,12) bias_val(1,16) bias_val(2,16) bias_val(2,20)];
        end

        function status = set_dist_bias(obj, intf, bias, ctat)
           %set_dist_bias(intf, bias)
           % the bias vector is 3x6 of 6bit bias values
           % [PTAT_ST1 PTAT_ST2_0 PTAT_ST2_1 cbias_ST1 cbias_ST2_0 cbis_ST2_1] 
           % with rows ordered B0 B1 B2
           % ctat is th DIST_Ctat avlue
           %
           % intf is the SPI interface
           %
           if nargin < 4
               fprintf("Not enough parameters\n");
               status = -1;
               return
           end
            status = intf.spi_load_address(obj.chip_id, obj.DIST_BIAS_ADDR);
            if status ~= 0
                return
            end
            new_val = bias(1,1) + bitshift(bias(1,2),8);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
            new_val = bias(1,3) + bitshift(bias(1,4),6) + bitshift(bias(1,5),9) + bitshift(bias(1,6),12);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
            new_val = bias(2,1) + bitshift(bias(2,2),8);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
            new_val = bias(2,3) + bitshift(bias(2,4),6) + bitshift(bias(2,5),9) + bitshift(bias(2,6),12);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
            new_val = bias(3,1) + bitshift(bias(3,2),8);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
            new_val = bias(3,3) + bitshift(bias(3,4),6) + bitshift(bias(3,5),9) + bitshift(bias(3,6),12);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
           	status = intf.spi_write(obj.chip_id, ctat);
            if status ~= 0
                return
            end
        end
        
        function [status, bias_val, ctat] = get_dist_bias(obj, intf)
            %get_dist_bias(obj, intf)
            % returns a 3x6 matirx of 6 bit bias values ordered
            % [PTAT_ST1 PTAT_ST2_0 PTAT_ST2_1 cbias_ST1 cbias_ST2_0 cbis_ST2_1] 
            % with rows ordered B0 B1 B2
            %
            % intf is the SPI interface
            %
            [status] = intf.spi_load_address(obj.chip_id, obj.DIST_BIAS_ADDR);
            if status ~= 0
                return
            end
            [status, cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0
               return
            end
            bias_val(1,1) = bitand(cur_val, 63);
            bias_val(1,2) = bitand(bitshift(cur_val,-8),63);
            [status, cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0
               return
            end
            bias_val(1,3) = bitand(cur_val, 63);
            bias_val(1,4) = bitand(bitshift(cur_val,-6),7);
            bias_val(1,5) = bitand(bitshift(cur_val,-9),7);
            bias_val(1,6) = bitand(bitshift(cur_val,-12),7);
            [status, cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0
               return
            end
            bias_val(2,1) = bitand(cur_val, 63);
            bias_val(2,2) = bitand(bitshift(cur_val,-8),63);
            [status, cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0
               return
            end
            bias_val(2,3) = bitand(cur_val, 63);
            bias_val(2,4) = bitand(bitshift(cur_val,-6),7);
            bias_val(2,5) = bitand(bitshift(cur_val,-9),7);
            bias_val(2,6) = bitand(bitshift(cur_val,-12),7);
            [status, cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0
               return
            end
            bias_val(3,1) = bitand(cur_val, 63);
            bias_val(3,2) = bitand(bitshift(cur_val,-8),63);
            [status, cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0
               return
            end
            bias_val(3,3) = bitand(cur_val, 63);
            bias_val(3,4) = bitand(bitshift(cur_val,-6),7);
            bias_val(3,5) = bitand(bitshift(cur_val,-9),7);
            bias_val(3,6) = bitand(bitshift(cur_val,-12),7);
            [status, ctat] = intf.spi_read(obj.chip_id);
            if status ~= 0
               return
            end
       end

        function status = set_daisy_bias(obj, intf, bias)
           %set_daisy_bias(intf, bias)
           % the bias vector is 4x4 of 6bit bias values
           % [Bias Tuning Offset_bias cbias] 
           % with rows ordered Chaino CHain 1 CHain2 Chain3
           %
           % intf is the SPI interface
           %
           if nargin < 3
               fprintf("Not enough parameters\n");
               status = -1;
               return
           end
            status = intf.spi_load_address(obj.chip_id, obj.DAISY_BIAS_ADDR);
            if status ~= 0
                return
            end
            new_val = bias(1,1) + bitshift(bias(2,1),8);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
            new_val = bias(3,1) + bitshift(bias(4,1),8);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
            new_val = bias(1,2) + bitshift(bitand(bias(1,3),1),4) + bitshift(bitand(bias(1,4),7),5);
            new_val = new_val + bitshift(bias(2,2) + bitshift(bitand(bias(2,3),1),4) + bitshift(bitand(bias(2,4),7),5),8);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
            new_val = bias(3,2) + bitshift(bitand(bias(3,3),1),4) + bitshift(bitand(bias(3,4),7),5);
            new_val = new_val + bitshift(bias(4,2) + bitshift(bitand(bias(4,3),1),4) + bitshift(bitand(bias(4,4),7),5),8);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
        end
        
        function [status, bias_val] = get_daisy_bias(obj, intf)
            %get_daisy_bias(obj, intf)
           % return sthe bias vector a 4x4 of 6bit bias values
           % [Bias Tuning Offset_bias cbias] 
           % with rows ordered Chaino CHain 1 CHain2 Chain3
            %
            % intf is the SPI interface
            %
            [status] = intf.spi_load_address(obj.chip_id, obj.DAISY_BIAS_ADDR);
            if status ~= 0
                return
            end
            [status, cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0
               return
            end
            bias_val(1,1) = bitand(cur_val, 63);
            bias_val(2,1) = bitand(bitshift(cur_val,-8),63);
            [status, cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0
               return
            end
            bias_val(3,1) = bitand(cur_val, 63);
            bias_val(4,1) = bitand(bitshift(cur_val,-8),63);
            [status, cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0
               return
            end
            bias_val(1,2) = bitand(cur_val, 15);
            bias_val(1,3) = bitand(bitshift(cur_val,-4),1);
            bias_val(1,4) = bitand(bitshift(cur_val,-5),7);
            bias_val(2,2) = bitand(bitshift(cur_val,-8), 15);
            bias_val(2,3) = bitand(bitshift(cur_val,-12),1);
            bias_val(2,4) = bitand(bitshift(cur_val,-13),7);
            [status, cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0
               return
            end
            bias_val(3,2) = bitand(cur_val, 15);
            bias_val(3,3) = bitand(bitshift(cur_val,-4),1);
            bias_val(3,4) = bitand(bitshift(cur_val,-5),7);
            bias_val(4,2) = bitand(bitshift(cur_val,-8), 15);
            bias_val(4,3) = bitand(bitshift(cur_val,-12),1);
            bias_val(4,4) = bitand(bitshift(cur_val,-13),7);
       end  

        function status = set_extra(obj, intf, extra)
           %set_extra_bias(intf, bias)
           % the extra vector is 1x4 
           % [extra_B0  extra_b1 extra_B2 extra_misc] 
           %
           % intf is the SPI interface
           %
           if nargin < 3
               fprintf("Not enough parameters\n");
               status = -1;
               return
           end
            status = intf.spi_load_address(obj.chip_id, obj.EXTRA_ADDR);
            if status ~= 0
                return
            end
            new_val = extra(1,1) + bitshift(extra(1,2),8);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
            new_val = extra(1,3);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
            new_val = extra(1,4);
           	status = intf.spi_write(obj.chip_id, new_val);
            if status ~= 0
                return
            end
        end
        
        function [status, extra] = get_extra(obj, intf)
           %get_extra(obj, intf)
           % return sthe bias vector a 1x4  values
           % [extra_B0  extra_b1 extra_B2 extra_misc] 
            %
            % intf is the SPI interface
            %
            [status] = intf.spi_load_address(obj.chip_id, obj.EXTRA_ADDR);
            if status ~= 0
                return
            end
            [status, cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0
               return
            end
            extra(1,1) = bitand(cur_val, 255);
            extra(1,2) = bitand(bitshift(cur_val,-8),255);
            [status, cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0
               return
            end
            extra(1,3) = bitand(cur_val, 255);
            [status, extra(1,4)] = intf.spi_read(obj.chip_id);
            if status ~= 0
               return
            end
       end  
        
        function status = set_cal(obj, intf, cal)
           %set_cal(intf, cal)
           % the cal vector is 4x2x3 of 4bit cal values
           % [[H0_B0 H0_B1 H0_B2
           %  V0_B0 V0_B1 V0_B2],
           % [[H1_B0 H1_B1 H1_B2
           %  V1_B0 V1_B1 V1_B2],
           % [[H2_B0 H2_B1 H2_B2
           %  V2_B0 V2_B1 V2_B2],
           % [[H3_B0 H3_B1 H3_B2
           %  V3_B0 V3_B1 V3_B2]]
           %
           % intf is the SPI interface
           %
           if nargin <3
               fprintf("Not enough parameters\n");
               status = -1;
               return
           end
            status = intf.spi_load_address(obj.chip_id, obj.BEAM_CAL_ADDR);
            if status ~= 0
                return
            end
            for ch = 1:4
                new_val = cal(ch,1,1) + bitshift(cal(ch,1,2),8);
                status = intf.spi_write(obj.chip_id, new_val);
                if status ~= 0
                    return
                end
            end
            for ch = 1:4
                new_val = cal(ch,1,3) + bitshift(cal(ch,2,1),8);
                status = intf.spi_write(obj.chip_id, new_val);
                if status ~= 0
                    return
                end
            end
            for ch = 1:4
                new_val = cal(ch,2,2) + bitshift(cal(ch,2,3),8);
                status = intf.spi_write(obj.chip_id, new_val);
                if status ~= 0
                    return
                end
            end
        end
        
        function [status, cal] = get_cal(obj, intf)
            %get_cal(obj, intf)
           % return the cal vector which is 4x2x3 of 4bit cal values
           % [[H0_B0 H0_B1 H0_B2
           %  V0_B0 V0_B1 V0_B2],
           % [[H1_B0 H1_B1 H1_B2
           %  V1_B0 V1_B1 V1_B2],
           % [[H2_B0 H2_B1 H2_B2
           %  V2_B0 V2_B1 V2_B2],
           % [[H3_B0 H3_B1 H3_B2
           %  V3_B0 V3_B1 V3_B2]]
            %
            % intf is the SPI interface
            %
            cal = zeros(4,2,3);
            [status] = intf.spi_load_address(obj.chip_id, obj.BEAM_CAL_ADDR);
            if status ~= 0
                return
            end
            for ch = 1:4
                [status, cur_val] = intf.spi_read(obj.chip_id);
                if status ~= 0
                   return
                end
                cal(ch,1,1) = bitand(cur_val, 15);
                cal(ch,1,2) = bitand(bitshift(cur_val,-8),15);
            end
            for ch = 1:4
                [status, cur_val] = intf.spi_read(obj.chip_id);
                if status ~= 0
                   return
                end
                cal(ch,1,3) = bitand(cur_val, 15);
                cal(ch,2,1) = bitand(bitshift(cur_val,-8),15);
            end
            for ch = 1:4
                [status, cur_val] = intf.spi_read(obj.chip_id);
                if status ~= 0
                   return
                end
                cal(ch,2,2) = bitand(cur_val, 15);
                cal(ch,2,3) = bitand(bitshift(cur_val,-8),15);
            end
        end
        
        function status = set_captune(obj, intf, captune)
            %set_captune(obj, intf, captune)
            % sets the captune value a 1x4 vector of 16 bit numbers
            % arranged channel 1 to 4
            %
            % intf is the SPI interface
            %
            if nargin < 3
               fprintf("Not enough parameters\n");
               status = -1;
               return
            end
            status = intf.spi_load_address(obj.chip_id, obj.CAPTUNE_ADDR);
            if status ~= 0 
               return; 
            end
            for i=1:4
                status = intf.spi_write(obj.chip_id, captune(i));
                if status ~= 0 
                   return; 
                end
            end
        end
  
        function [status,captune] = get_captune(obj, intf)
            %get_captune(obj, intf)
            % returns the captune value a 1x4 vector of 16 bit numbers
            % arranged channel 1 to 4
            %
            % intf is the SPI interface
            %
            status = intf.spi_load_address(obj.chip_id, obj.CAPTUNE_ADDR);
            if status ~= 0 
               return; 
            end
            captune = zeros(1,4);
            for i=1:4
                [status,captune(i)] = intf.spi_read(obj.chip_id);
                if status ~= 0 
                   return; 
                end
            end
        end

        function [status,short_ID, version_ID] = get_short_ID(obj, intf)
            %get_short_ID(obj, intf)
            % returns the short ID value
            %
            % intf is the SPI interface
            %
            status = intf.spi_load_address(obj.chip_id, obj.SHORT_ID_ADDR);
            if status ~= 0 
               return; 
            end
            [status,cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0 
               return; 
            end
            short_ID = bitand(cur_val,255);
            version_ID = bitand(bitshift(cur_val,-8),255);
        end

        function [status,adc] = get_adc_val(obj, intf)
            %get_adc_val(obj, intf)
            % returns the captune value a 1x14 vector of 8 bit numbers
            % arranged [Temp PD0 PD1 ... PD7 Port0 Port1 Port2 Port3 DCTEST]
            %
            % intf is the SPI interface
            %
            status = intf.spi_load_address(obj.chip_id, obj.ADC_ADDR);
            if status ~= 0 
               return; 
            end
            adc = zeros(1,14);
            for i=1:14
                [status,cur_val] = intf.spi_read(obj.chip_id);
                adc(i) = cur_val;
                if status ~= 0 
                   return; 
                end
            end
        end

        function [status,UID] = get_unique_ID(obj, intf)
            %get_unique_ID(obj, intf)
            % returns the get_unique ID value
            %
            % intf is the SPI interface
            %
            status = intf.spi_load_address(obj.chip_id, obj.UID_ADDR);
            if status ~= 0 
               return; 
            end
            [status,cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0 
               return; 
            end
            UID = cur_val;
            [status,cur_val] = intf.spi_read(obj.chip_id);
            if status ~= 0 
               return; 
            end
            UID = UID + bitshift(cur_val,16);
        end

        function [status,efuse] = get_efuse_data(obj, intf)
            %get_efuse_data(obj, intf)
            % returns the get_efuse_data as a vector of 32 16 bit numbers
            %
            % intf is the SPI interface
            %
            status = intf.spi_load_address(obj.chip_id, obj.EFUSE_RAW_ADDR);
            if status ~= 0 
               return; 
            end
            efuse = zeros(1,32);
            for i=1:32
                [status,efuse(i)] = intf.spi_read(obj.chip_id);
                if status ~= 0 
                   return; 
                end
            end
        end

        function [status,efuse] = get_efuse_status(obj, intf)
            %get_efuse_status(obj, intf)
            % returns the get_efuse_status as a vector of 8 
            %
            % intf is the SPI interface
            %
            status = intf.spi_load_address(obj.chip_id, obj.EFUSE_STATUS_ADDR);
            if status ~= 0 
               return; 
            end
            efuse = zeros(1,8);
            for i=1:8
                [status,efuse(i)] = intf.spi_read(obj.chip_id);
                if status ~= 0 
                   return; 
                end
            end
        end
        
        function [status,quad] = get_quad_debug (obj, intf)
            %get_quad_debug(obj, intf)
            % returns the quad debug values as a vector of 4x9 matrix
            %
            % intf is the SPI interface
            %
            status = intf.spi_load_address(obj.chip_id, obj.ADC_DBG_ADDR);
            if status ~= 0 
               return; 
            end
            quad = zeros(4,19);
            for i=1:19
                for k=1:4
                    [status,quad(k,i)] = intf.spi_read(obj.chip_id);
                    if status ~= 0 
                       return; 
                    end
                end
            end
        end

        function [status] = set_phase_cal(obj, intf, ph_cal)
            %get_phase_cal(obj, intf)
            % set the phase cal data as a vector of 4x70 16 bit numbers
            %
            % intf is the SPI interface
            %
            status = intf.spi_load_address(obj.chip_id, obj.PHASE_CAL_ADDR);
            if status ~= 0 
               return; 
            end
            for i=1:70
	            for k=1:4
	                [status] = intf.spi_write(obj.chip_id, ph_cal(k,i));
	                if status ~= 0 
	                   return; 
	                end
	            end
	          end
        end

        function [status,ph_cal] = get_phase_cal(obj, intf)
            %get_phase_cal(obj, intf)
            % returns the phase cal data as a vector of 4x70 16 bit numbers
            %
            % intf is the SPI interface
            %
            status = intf.spi_load_address(obj.chip_id, obj.PHASE_CAL_ADDR);
            if status ~= 0 
               return; 
            end
            ph_cal = zeros(4,70);
            for i=1:70
	            for k=1:4
	                [status,ph_cal(k,i)] = intf.spi_read(obj.chip_id);
	                if status ~= 0 
	                   return; 
	                end
	            end
	          end
        end
     
   end
          
    methods (Static, Hidden)
       
   end
end
