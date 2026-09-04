%% CONNECT_POWERSUPPLY1 Code for communicating with an instrument.
%
%   This is the machine generated representation of an instrument control
%   session. The instrument control session comprises all the steps you are
%   likely to take when communicating with your instrument. These steps are:
%   
%       1. Instrument Connection
%       2. Instrument Configuration and Control
%       3. Disconnect and Clean Up
% 
%   To run the instrument control session, type the name of the file,
%   Connect_PowerSupply1, at the MATLAB command prompt.
% 
%   The file, CONNECT_POWERSUPPLY1.M must be on your MATLAB PATH. For additional information 
%   on setting your MATLAB PATH, type 'help addpath' at the MATLAB command 
%   prompt.
% 
%   Example:
%       connect_powersupply1;
% 
%   See also SERIAL, GPIB, TCPIP, UDP, VISA, BLUETOOTH, I2C, SPI.
% 
%   Creation time: 03-Oct-2019 14:38:11

%% Instrument Connection

% Find a tcpip object.
PowSup1 = instrfind('Type', 'tcpip', 'RemoteHost', '192.168.5.103', 'RemotePort', 5025, 'Tag', '');

% Create the tcpip object if it does not exist
% otherwise use the object that was found.
if isempty(PowSup1)
    PowSup1 = tcpip('192.168.5.103', 5025);
else
    fclose(PowSup1);
    PowSup1 = PowSup1(1);
end

% Connect to instrument object, PowSup1.
fopen(PowSup1);