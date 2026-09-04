% Written by Aayush on 5/5/2026

function readData = Record_PS_VI_Return_STMPD(printDt,PowSup1,PowSup2)
% Read measurements
read_PS_V = [];
read_PS_I = [];

read_PS_V = [read_PS_V str2num(query(PowSup1,'MEAS:VOLT? (@1,2,3)'))];
    read_PS_I = [read_PS_I str2num(query(PowSup1,'MEAS:CURR? (@1,2,3)'))];
read_PS_V = [read_PS_V str2num(query(PowSup2,'MEAS:VOLT? (@1,2,3)'))];
    read_PS_I = [read_PS_I str2num(query(PowSup2,'MEAS:CURR? (@1,2,3)'))];

% Print voltage readings
if printDt
    n = size(read_PS_V,2);
    txtData = cell(3,n);
    txtData(1,:) = {'FE1' '1.8V' 'DIG_1V' 'FE2' 'FE3' '1.8V IO'};
    for k = 1:n
        txtData{2,k} = [num2sip(read_PS_V(k),3) 'V'];
    end
    n = size(read_PS_I,2);
    for k = 1:n
        txtData{3,k} = [num2sip(read_PS_I(k),3) 'A'];
    end
    disp(txtData);
    clear txtData;
end

% Merge readings
readData = [read_PS_V read_PS_I];
end