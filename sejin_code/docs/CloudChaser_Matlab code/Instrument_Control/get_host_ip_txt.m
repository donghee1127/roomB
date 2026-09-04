% Copyright 2023 Sivers Semiconductors, All right reserved.
% Sivers Semiconductors Proprietary Shared under NDA.
%
% This script gets the IP address(s) of the host machine

function host_ip_txt = get_host_ip_txt()
    [stat,host_ip_txt] = system('ipconfig | findstr IPv4');
    if stat == 0
        host_ip_txt = erase(host_ip_txt,'IPv4 Address. . . . . . . . . . . : ');
        host_ip_txt = erase(host_ip_txt,' ');
    else
        host_ip_txt = NaN;
    end
end