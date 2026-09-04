% Written by Bye-sah on 03/08/2022

[warnMsg, warnId] = lastwarn;
if ~isempty(warnMsg)
    beep; keyboard;
end
lastwarn('');