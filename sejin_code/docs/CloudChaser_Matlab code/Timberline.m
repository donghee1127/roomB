%
%  Timberline.m defines a class for the control routines for programming the Mixcomm Summit 28 GHz via matlab
%  This uses the Timberline.dll which is a windows DLL using the LibMPSSE_SPI libraty to program the 
%	 SPI interface through the C232HM USB 2.0 HI-SPEED TO MPSSE CABLE from FTDI (http://www.ftdichip.com).
%
%  copyright 2020 Mixcomm, Inc.  All right reserved.
%

classdef Timberline
   properties (Constant)
       spi_trans_len = 4;     % basic spi transaction length
   end
   
   properties
        spi_clk = 500000;     
   end
   
   methods
       function obj = Timberline(path)
           if nargin>0
       			addpath(path);
           end
					if not(libisloaded('Timberline'))
		                 loadlibrary('Timberline.dll','Timberline.h');
					end
       end
       
       function status =  spi_initialize( obj, clk)  
            if nargin > 1
                obj.spi_clk = clk;
            end
            status = calllib('Timberline','spi_initialize', obj.spi_clk, obj.spi_trans_len, 0); end 

		function status =  spi_close(~)                                     
            status = calllib('Timberline','spi_close'); end                                  
		function status =  spi_reset(~ )                                     
            status = calllib('Timberline','spi_reset'); end                                  
		function status =  spi_upd(~ )                                       
            status = calllib('Timberline','spi_upd'); end                                    
		function status =  spi_load_address(~, chip_id, data)                                
            status = calllib('Timberline','spi_load_address',chip_id, data); end
		function [status, data] = spi_read(~, chip_id)
            ptr2data = libpointer('uint32Ptr',0);
            [status, data] = calllib('Timberline','spi_read',chip_id, ptr2data); end                            
		function status =  spi_write(~, chip_id,  data)                          
            status = calllib('Timberline','spi_write',chip_id, data); end                            
		function [status, data] = spi_read_extended(~, chip_id, len)
            ptr2data = libpointer('uint32Ptr',0);
            [status, data] = calllib('Timberline','spi_read_extended',chip_id, ptr2data, len); end                            
		function status =  spi_write_extended(~, chip_id,  data)                          
            ptr2data = libpointer('uint32Ptr',data);
            status = calllib('Timberline','spi_write_extended',chip_id, ptr2data, length(data)); end                            
		function status =  spi_beam_sel(~, chip_id,  beam_indx, idx_id)                           
            status = calllib('Timberline','spi_beam_sel',chip_id,  beam_indx, idx_id); end                         
		function status = spi_adc_capture(~, chip_id)
            status = calllib('Timberline','spi_adc_capture',chip_id); end                            
		function status = spi_do_enum(~, chip_id)
            status = calllib('Timberline','spi_do_enum',chip_id); end                            
		function status = spi_soft_reset(~, chip_id)
            status = calllib('Timberline','spi_soft_reset',chip_id); end                            
		function status = spi_efuse_prog(~, chip_id, row, data)
            status = calllib('Timberline','spi_efuse_prog', chip_id, row, data); end                            
		function status = spi_efuse_sense(~, chip_id, row)
            status = calllib('Timberline','spi_efuse_sense',chip_id, row); end                            
		function status = spi_efuse_ptime_set(~, chip_id, time)
            status = calllib('Timberline','spi_efuse_ptime_set',chip_id, time); end                            
		function status = spi_efuse_fval_set(~, chip_id, fval)
            status = calllib('Timberline','spi_efuse_fval_set',chip_id, fval); end                            
		function status = spi_efuse_char_set(~, chip_id, char_param)
            status = calllib('Timberline','spi_efuse_char_set',chip_id, char_param); end                            
	end
end

