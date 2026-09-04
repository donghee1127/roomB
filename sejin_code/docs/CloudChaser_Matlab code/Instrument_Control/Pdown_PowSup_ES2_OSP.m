% Written by Bye-sah on 12/15/2022 based on "Pdown_PowSup_Osprey_NoPupCheck.m"
% 
% This scripts powers down the power supplies for the ES2 Osprey EVB
% PowSup1 outputs: '4V'        '1.8V_IO'    'DIG_1V'    
% PowSup2 output1: '1.8V_ANA'  '1.8V_DRV'

%% Configure the power supplies
% Check if the power supplies are up
DC_VI_Init_PowSup = Record_PS_VI_Return_ES2_OSP(0,PowSup1,PowSup2);
if min(DC_VI_Init_PowSup(1:5) - [3.3 1.6 0.8 1.6 1.6]) < 0
        keyboard; % Check if the power supplies are down
end

res = 0;
fprintf(PowSup1,['VOLT 3.3, (@' '1' ')']); if ~res && PS_Protection_Trip_Check(PowSup1,PowSup2); Record_PS_VI_Return_ES2_OSP(1,PowSup1,PowSup2); res = 1; end
fprintf(PowSup1,['VOLT 3.0, (@' '1' ')']); if ~res && PS_Protection_Trip_Check(PowSup1,PowSup2); Record_PS_VI_Return_ES2_OSP(1,PowSup1,PowSup2); res = 1; end
fprintf(PowSup1,['VOLT 2.7, (@' '1' ')']); if ~res && PS_Protection_Trip_Check(PowSup1,PowSup2); Record_PS_VI_Return_ES2_OSP(1,PowSup1,PowSup2); res = 1; end
fprintf(PowSup1,['VOLT 2.4, (@' '1' ')']); if ~res && PS_Protection_Trip_Check(PowSup1,PowSup2); Record_PS_VI_Return_ES2_OSP(1,PowSup1,PowSup2); res = 1; end
fprintf(PowSup1,['VOLT 2, (@' '1' ')']); if ~res && PS_Protection_Trip_Check(PowSup1,PowSup2); Record_PS_VI_Return_ES2_OSP(1,PowSup1,PowSup2); res = 1; end
fprintf(PowSup2,['VOLT 1.6, (@' '1,2' ')']); if ~res && PS_Protection_Trip_Check(PowSup1,PowSup2); Record_PS_VI_Return_ES2_OSP(1,PowSup1,PowSup2); res = 1; end
fprintf(PowSup1,['VOLT 1.6, (@' '1,2' ')']); if ~res && PS_Protection_Trip_Check(PowSup1,PowSup2); Record_PS_VI_Return_ES2_OSP(1,PowSup1,PowSup2); res = 1; end
fprintf(PowSup2,['VOLT 1.2, (@' '1,2' ')']); if ~res && PS_Protection_Trip_Check(PowSup1,PowSup2); Record_PS_VI_Return_ES2_OSP(1,PowSup1,PowSup2); res = 1; end
fprintf(PowSup1,['VOLT 1.2, (@' '1,2' ')']); if ~res && PS_Protection_Trip_Check(PowSup1,PowSup2); Record_PS_VI_Return_ES2_OSP(1,PowSup1,PowSup2); res = 1; end
fprintf(PowSup2,['VOLT 0.8, (@' '1,2' ')']); if ~res && PS_Protection_Trip_Check(PowSup1,PowSup2); Record_PS_VI_Return_ES2_OSP(1,PowSup1,PowSup2); res = 1; end
fprintf(PowSup1,['VOLT 0.8, (@' '1,2,3' ')']); if ~res && PS_Protection_Trip_Check(PowSup1,PowSup2); Record_PS_VI_Return_ES2_OSP(1,PowSup1,PowSup2); res = 1; end
fprintf(PowSup2,['VOLT 0.4, (@' '1,2' ')']); if ~res && PS_Protection_Trip_Check(PowSup1,PowSup2); Record_PS_VI_Return_ES2_OSP(1,PowSup1,PowSup2); res = 1; end
fprintf(PowSup1,['VOLT 0.4, (@' '1,2,3' ')']); if ~res && PS_Protection_Trip_Check(PowSup1,PowSup2); Record_PS_VI_Return_ES2_OSP(1,PowSup1,PowSup2); res = 1; end
fprintf(PowSup2,['VOLT 0, (@' '1,2' ')']); if ~res && PS_Protection_Trip_Check(PowSup1,PowSup2); Record_PS_VI_Return_ES2_OSP(1,PowSup1,PowSup2); res = 1; end
fprintf(PowSup1,['VOLT 0, (@' '1,2,3' ')']); if ~res && PS_Protection_Trip_Check(PowSup1,PowSup2); Record_PS_VI_Return_ES2_OSP(1,PowSup1,PowSup2); res = 1; end
    
Record_PS_VI_Return_ES2_OSP(1,PowSup1,PowSup2);
if PS_Protection_Trip_Check(PowSup1,PowSup2)
    beep; keyboard;
end
clear DC_VI_Init_PowSup