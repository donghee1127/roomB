% ipadd = '192.168.5.68';
% ipadd = '192.168.5.60';
% ipadd = '192.168.5.21';
ipadd = '192.168.5.66';

% Find a tcpip object.
PowMtr = instrfind('Type', 'tcpip', 'RemoteHost', ipadd, 'RemotePort', 5025, 'Tag', '');

% Create the tcpip object if it does not exist
% otherwise use the object that was found.
if isempty(PowMtr)
    PowMtr = tcpip(ipadd, 5025);
else
    fclose(PowMtr);
    PowMtr = PowMtr(1);
end

% Connect to instrument object, PowMtr.
fopen(PowMtr);