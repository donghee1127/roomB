%% Instrument Connection
ip = '192.168.5.123';

% Find a tcpip object.
SMW = instrfind('Type', 'tcpip', 'RemoteHost', ip, 'RemotePort', 5025, 'Tag', '');

% Create the tcpip object if it does not exist
% otherwise use the object that was found.
if isempty(SMW)
    SMW = tcpip(ip, 5025);
else
    fclose(SMW);
    SMW = SMW(1);
end

% Connect to instrument object, SMW.
fopen(SMW);

clear ip;