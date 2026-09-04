% Copyright 2021 Mixcomm, Inc. All right reserved.
% MixComm Proprietary Shared under NDA
%% Written by Mahmood on 02/06/2022
% This script runs SP measurements on 8 channels
% Thermocouple readings are not taken

function Answer=mem_test_spi(spi_if, chip_id, n)
if n>4095,
	n = 4095;
end
spi_if.spi_load_address(255,0);
for i= 1:n,
    spi_if.spi_write(255,i);
end
spi_if.spi_load_address(255,0);
for i= 1:n,
    [s,y] = spi_if.spi_read(chip_id);
    if y~=i 
        fprintf("read err at %d value = %d\n",i,y);
        Answer=0;
        return 
    end
end
fprintf("Test Complete\n");
Answer=1;