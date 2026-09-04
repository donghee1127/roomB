'''Imports'''
import os
from mvboard.GumStick import GumStick
from time import sleep
from enum import Enum
import time,math
import logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

'''User inputs'''
Center_f = {"Low": 27.0e9, "Mid": 28.0e9, "High": 29.0e9}

##############################################################################################
################################ Parameter Setting ###########################################
##############################################################################################

gumstick_port = 0 #1 for H1 Breakout board, 0 for H3 Breakoutboard
panel = 'donor'
txrx = 'tx'
beam = 'b1'
rf_freq = Center_f["Low"] # Select carrier
beam_index = 0
beam_mode = '30x15' # beam_mode is '30x15' , '30x30' , '60x15'
Tri_band = 1 # Single_band GS = 0
###############################################################################################

if rf_freq < 27.5e9:
    band = 'low'
elif rf_freq >= 27.5e9 and rf_freq <= 28.5e9:
    band = 'mid'
else:
    band = 'high'

if_freq = 5e9
ref_in_MHz = 122.88
FSPL_distance_metres = 0.7
pol = 'h' if beam == 'b1' else 'v'
lo_freq = (rf_freq - if_freq)
pll_freq_MHz = lo_freq/3e6

print("Donor or Relay:",panel)
print("T/Rx Mode:",txrx)
print("band:", band)
print("Beam:",beam)
print("Center Frequency:",rf_freq)
print("Initial Beam Index:",beam_index)
print("Initial Beam Mode:",beam_mode)
print("Triband(1), Single band(0):",Tri_band)
    
def init_RFIC():
    # Init PMU
    gs.init()
    #gs.digital_test()
    
    # Init vcxo pll
    gs.init_vcxo_pll()
    sleep(1)
    
    # Set rf
    print('** Intializing RFICs **')
    for fe_num,fe in enumerate(gs.fe):
        gs.comms.reset_mirror()
        fe.model.load_from_dataset('init')
        bg_code = fe.model.run_BG_cal_rtl(prnt=True)
        print(f'FE - {fe_num} : BG_code - {bg_code}')
    
    # Set mixer   
    gs.comms.reset_mirror()
    gs.mix[0].model.load_from_dataset('init')
    bg_code = gs.mix[0].model.run_BG_cal_rtl(prnt=True)
    print(f'IF_mix : BG_code - {bg_code}')
    
    # Set pll
    gs.comms.reset_mirror()
    gs.init_pll(pll = '3554')
    bg_code = gs.pll[0].model.run_BG_cal_rtl(dbg_prt=True)
    print(f'IF_PLL : BG_code - {bg_code}')    
    print(gs.fe[0].model.__class__)
    print(gs.mix[0].model.__class__)

def set_txrx(txrx='tx' , beam = 'b1', band = 'mid'):
    if_port_val = 'a' if txrx =='rx' else 'b'
    lo_mult = 1.5 if rf_freq < 32e9 else 2
    gs.set_pll_freq(pll="3554", ref_in_MHz=ref_in_MHz, freq_out_MHz=pll_freq_MHz, mult_val=lo_mult, vco_freq_cutoff=4990)
    sleep(0.2)
    #gs.pll_logen_cal(pll="3554", tssi_out_lim=1200) #sypark
    gs.pll_logen_cal(pll="3554", tssi_out_lim=900, prnt=True)

    gs.set_target(gs.mix[0])
    mv2853 = gs.mix[0].model
    mv2853.initialize_TX(beam=beam, if_sw=if_port_val, band=band, prnt=True) if txrx == "tx" else mv2853.initialize_RX(beam=beam,if_sw=if_port_val,band=band, prnt=True)
    mv2853.set_band(mode=txrx, rf_band=band, if_freq=if_freq, logen=lo_freq, beam = 'both', lo_cal_lim=550, freq_cutoff=18.5e9)
    mv2853.set_txif_attn(attn = 12)
    mv2853.set_PA_bias(13,13,13,2,9, beam='both') 
    
    for fe in gs.fe:
        gs.set_target(fe)
        fe.model.initialize_tx(path="all_off", prnt=True) if txrx == "tx" else fe.model.initialize_rx(path="all_off", prnt=True)
        fe.model.set_band_TX(band = band) if txrx == "tx" else fe.model.set_band_RX(band = band)
        fe.model.dreg.hv_swap.val = 0x09
        fe.model.set_PA_bias(13,13,13,1,9)

def flash_load_cal_section(start_addr, end_addr):
    if((start_addr%256 != 0) or (end_addr%256 != 0)):
        raise Exception("start/end address has to be start/end of a page, cannot load section from middle of a page..")
    else:
        start_page = start_addr//256
        no_of_pages = (end_addr-start_addr)//256
    for page_no in list(range(start_page, start_page + no_of_pages)):
        gs.run_load_beam_book_from_flash(page_no, 85)

def convert_to_int(list_data):
    val = 0
    for i in range(len(list_data)):
        val += (list_data[i] << (8*(len(list_data)-1-i)))
        print(list_data[i] << (8*(len(list_data)-1-i)))
        print(val)
    return val

def flash_load_cal_data(panel='donor', band='mid', loc = [0,1,3]):
    gs.comms.reset_mirror()
    print("-----------------------------------------------------")
    print("Donor or Relay\t\t\t:\t",panel)
    print("-----------------------------------------------------")
    
    '''loc format -> phasecal, beambook, extended gain lut, baseband gain lut'''
    band_dict = {'low':0xc00, 'mid':0xb00, 'high':0xa00}
    list_data = gs.flash_ctrl.read_page(band_dict[band])
    cal_st = convert_to_int(list_data[16:20])
    cal_end = convert_to_int(list_data[20:24])
    bbk_st = convert_to_int(list_data[28:32])
    bbk_end = convert_to_int(list_data[32:36])
    ext_st = convert_to_int(list_data[40:44])
    ext_end = convert_to_int(list_data[44:48])
    bbiq_st = convert_to_int(list_data[52:56])
    bbiq_end = convert_to_int(list_data[56:60])
    cal_array = {'start_addr_ary':[cal_st, bbk_st, ext_st, bbiq_st],
                 'end_addr_ary' : [cal_end, bbk_end, ext_end, bbiq_end]}

    for i in loc:
        start_addr = cal_array["start_addr_ary"][i]
        end_addr = cal_array["end_addr_ary"][i]+1
        flash_load_cal_section(start_addr, end_addr)
    print(cal_array['start_addr_ary'])
    print(cal_array['end_addr_ary'])
    gs.comms.reset_mirror()

def atten(n):
    if txrx=='tx':
        # TX Gain (> 48dB)_Mixer 8/ FE 13
        tx_gain ={15:[18,17],14:[18,17],13:[18,16],12:[18,15],11:[18,14],10:[18,13],9:[18,12],8:[18,11],7:[18,10],6:[18,9],
        5:[18,8],4:[17,8],3:[16,8],2:[15,8],1:[14,8],0:[13,8],-1:[13,7],-2:[13,6],-3:[13,5],-4:[12,5],
        -5:[11,5],-6:[10,5],-7:[9,5],-8:[8,5],-9:[7,5],-10:[7,4],-11:[7,3],-12:[6,3],-13:[5,3],-14:[4,3],
        -15:[3,3],-16:[3,2],-17:[2,2],-18:[2,1],-19:[1,1],-20:[1,0]}
        #Gain index Attn value: -15~20 (0~35)
        gs.set_gain_index_MIX_TX_RAM(index=tx_gain[n][1], b1=1, b2=1)
        # 2853 TX: 1dB gain step (Min:0, Max:15) default: 8
        gs.set_gain_index_FE_TX_RAM(index=tx_gain[n][0], b1=1, b2=1)
        # 2850 TX: 1dB gain step (Min:0, Max:15) default: 13

    else:
        # RX Gain (> 42dB)_Mixer 6/ FE 15
        rx_gain = {15:[15,21],14:[15,20],13:[15,19],12:[15,18],11:[15,17],10:[15,16],9:[15,15],8:[15,14],7:[15,13],6:[15,12],
        5:[15,11],4:[15,10],3:[15,9],2:[15,8],1:[15,7],0:[15,6],-1:[15,5],-2:[15,4],-3:[14,6],-4:[14,5],
        -5:[14,4],-6:[13,6],-7:[13,5],-8:[13,4],-9:[12,6],-10:[12,5],-11:[12,4],-12:[11,6],-13:[11,5],-14:[11,4],
        -15:[10,6],-16:[10,5],-17:[10,4],-18:[9,6],-19:[9,5],-20:[9,4],-21:[8,6],-22:[8,5],-23:[8,4],-24:[7,6],-25:[7,5],
        -26:[7,4],-27:[6,6],-28:[6,5],-29:[6,4],-30:[5,6]}
        #Gain index Attn value: -15~20 (0~35)
        gs.set_gain_index_MIX_RX_RAM(index=rx_gain[n][1], b1=1, b2=1)
        # 2853 RX: 1dB gain step (Min:0, Max:15) default: 6
        gs.set_gain_index_FE_RX_RAM(index=rx_gain[n][0])
        # 2850 RX: 3dB gain step (Min:0, Max:15) default: 15

def set_bm_idx(mode = 'tx', beam = 'b1', pol = 'h', idx = 0):
    getattr(gs,'set_beambook_index_%s'%mode)(gs.fe, beam=beam, pol=pol, index=idx)

def set_beam_mode(beam_mode = '30x15', beam = 'b1', pol = 'h', txrx = 'tx'):   
    txrx == "tx" if gs.enable_beambooks_tx() else gs.enable_beambooks_rx()
    if beam_mode=='30x15':
        set_bm_idx(txrx, beam, pol, 0)
        for ii in range(8):
           chip = gs.fe[ii].model
           chip.reg.bias_tc1_mag.val=129
           chip.reg.bias_tc1_slope.val=58  
        for fe in gs.fe:
            fe.model.set_PA_bias(13,13,13,1,9)
        gs.config_TX_FE_all_off() if txrx == 'tx' else gs.config_RX_FE_all_off()        
        gs.enable_selected_pol(chips=[gs.fe[0], gs.fe[1], gs.fe[2], gs.fe[3], gs.fe[4], gs.fe[5], gs.fe[6], gs.fe[7]], beam=beam, pol=pol, txrx=txrx)
    elif beam_mode=='60x15':
        set_bm_idx(txrx, beam, pol, 0)
        for ii in range(8):
           chip = gs.fe[ii].model
           chip.reg.bias_tc1_mag.val=129
           chip.reg.bias_tc1_slope.val=58  
        for fe in gs.fe:
            fe.model.set_PA_bias(13,13,13,1,9)
        gs.config_TX_FE_all_off() if txrx == 'tx' else gs.config_RX_FE_all_off()  
        gs.enable_selected_pol(chips=[gs.fe[0], gs.fe[1], gs.fe[2], gs.fe[3]], beam=beam, pol=pol, txrx=txrx)
    elif beam_mode=='30x30':
        set_bm_idx(txrx, beam, pol, 0)
        for ii in range(8):
           chip = gs.fe[ii].model
           chip.reg.bias_tc1_mag.val=129
           chip.reg.bias_tc1_slope.val=58  
        for fe in gs.fe:
            fe.model.set_PA_bias(13,13,13,1,9)
        gs.config_TX_FE_all_off() if txrx == 'tx' else gs.config_RX_FE_all_off()  
        gs.enable_selected_pol(chips=[gs.fe[0], gs.fe[1], gs.fe[4], gs.fe[5]], beam=beam, pol=pol, txrx=txrx) 
    else: 
        print('Error, Please resetting beam mode')
    
def set_beam_index(beam_index = 0):
    gs.enable_beambooks_tx() if txrx == 'tx' else gs.enable_beambooks_rx()  
    gs.set_beambook_index_tx(gs.fe, beam, pol, beam_index) if txrx == 'tx' else gs.set_beambook_index_rx(gs.fe, beam, pol, beam_index)

def config_FE_all_off(txrx = 'tx'):
    if txrx =='rx':
        gs.bc_fe.model.dreg.fe_lna_pd.val = 0xff
        gs.bc_fe.model.dreg.fe_rxda1_pd.val = 0xff
        gs.bc_fe.model.dreg.drv_trxda_pd.val = 0xf
        gs.bc_fe.model.dreg.fe_ps_rx_1_pu.val = 0x0
        gs.bc_fe.model.dreg.fe_ps_rx_2_pu.val = 0x0
    elif txrx == 'tx':
        gs.bc_fe.model.dreg.drv_trxda_pd.val = 0xf
        gs.bc_fe.model.dreg.fe_pa_pd.val = 0xff
        gs.bc_fe.model.dreg.fe_ps_tx_1_pu.val = 0x0
        gs.bc_fe.model.dreg.fe_ps_tx_2_pu.val = 0x0

def agc_enable(mix_en=0, fe_en=0):
    gs.set_target(gs.mix[0])
    mv2853 = gs.mix[0].model
    mv2853.dreg.agc_mode.val=mix_en

    for fe in gs.fe: 
        gs.set_target(fe)         
        fe.model.dreg.agc_ctrl3.val=fe_en     

def read_init_temp_after_boot():
    #Enable PMU
    gs.init() 

    for fe_num,fe in enumerate(gs.fe):
        gs.comms.reset_mirror()
        fe.model.load_from_dataset('init')
        bg_code = fe.model.run_BG_cal_rtl(prnt=True)

    gs.read_avgtemp()
    
    #Disable PMU
    gs.comms.write_reg(10, 0x0)

def get_chip_fe(beam = 'b1', pol = 'h', ant_idx = 0):
    fe_list = [3,4,1,2,2,1,4,3]
    chip_num = 4+(ant_idx//8)-2*(ant_idx&2)
    fe = fe_list[ant_idx % 8 ]
    beam_swap = True if chip_num<4 else False
    if beam == 'b1':
        beam_comp = 'b2'
    else:
        beam_comp = 'b1'
    log_path = f'{beam}_{fe}{pol}'
    phy_path = f'{beam_comp}_{fe}{pol}' if beam_swap else log_path
    return chip_num, fe, log_path, phy_path

def Element_On (beam = 'b1', pol = 'h', el = 0):
    chip_num, fe, log_path, phy_path = get_chip_fe(beam = beam, pol = pol, ant_idx = el)
    gs.config_FE_TX(chips=[gs.fe[chip_num]], fe=log_path)                 
                    
def Set_PS_Index_at_freq(path = 'b1_1h', phase_idx = 0, g_default = 7, fe_num = 0):
    gs.fe[fe_num].model.set_PS_Index_at_freq(selection=path, index=phase_idx, N=64,freq=rf_freq, g_index=g_default, txrx=txrx,return_IQ=False)
                
def element_on_withPhase(beam = 'b1', pol = 'h', phase = 0, g_default = 10, el = 0):
    chip_num, fe, log_path, phy_path = get_chip_fe(beam = beam, pol = pol, ant_idx = el)
    gs.config_FE_TX(chips=[gs.fe[chip_num]], fe=log_path)
    Set_PS_Index_at_freq(path = phy_path, phase_idx = phase, g_default = g_default, fe_num = chip_num)
    print("el: {},\tpath: {},\tswap_path: {},\tps_idx: {},\tg_idx: {}".format(el, log_path, phy_path, phase, g_default))
        


###############################################   GS Initial  ######################################################
gs = GumStick(n = gumstick_port) # G/S Open
init_RFIC() # Init PMU / Init vcxo pll / Set rf / Set mixer / Set pll
if panel == 'donor':
    gs.digital_test()  # use only Donor type
set_txrx(txrx=txrx , beam = beam, band = band) # Set txrx
FlashLoad = False
if FlashLoad:
    flash_load_cal_data(panel=panel, band=band, loc = [0,1,3]) # Load beambook -> beambook 로드 안하면 결과 왜 이상한지?
gs.config_TX_FE_all_off() # Tx fe off
gs.config_RX_FE_all_off() # Rx fe off
gs.pll_recal('3554') # PLL Recal
time.sleep(1)
<<<<<<< .mine
if FlashLoad:
    atten(0) # Attenuation
||||||| .r770
atten(0) # Attenuation
=======
#atten(0) # Attenuation
>>>>>>> .r771
#set_beam_mode('30x15', beam, pol, txrx) # Set beam mode           -->  beam_mode 설정 시 Lock 걸려서 Phase 움직이지 않음
#set_beam_index(0) # set beam index
gs.read_avgtemp() # Read AvgTemp
gs.config_TX_FE_all_off() # Tx fe off
'''
gs.config_TX_FE_all_off() # Tx fe off
element_on_withPhase('b1','h',0,7,17)
for phase in range(64):
    element_on_withPhase('b1', 'h', phase, 7, 0)
    time.sleep(0.2)  

element_on_withPhase('b1','h',10,7,1)
    
for gain in range(4,11):
    element_on_withPhase('b1', 'h', 0, gain, 0)
    time.sleep(1)    


for chip in range(32):
    print(get_chip_fe('b1','v',chip))
    
         
'''
######################################################################################################


################################   NI 장비 제어 ########################################################
# 레퍼런스에서 사용하는 NI 제어 래퍼 임포트
from pyrfdvt.test_modules.Instrument_Control_Module import Instrument_Control_Class as InstrCtrlFns
from pyrfdvt.test_modules.Test_Utils_Module import test_utils

# >>> GPT (NI-REF): 장비 인스턴스 생성 및 모드/측정 세팅
inst_dict = {'NI_resource': 'mmWave_VST'}
inst = InstrCtrlFns(**inst_dict)
print(inst)

# RFmx 네임스페이스 (레퍼런스와 동일)
import NationalInstruments.RFmx.SpecAnMX as an_mx
import NationalInstruments.RFmx.NRMX as nr_mx

# 사용자가 제공한 port_map / demod_state를 그대로 삽입
port_map = {'tx' : {'b1' :   {'rfsg' : 'if0'      , 'rfsa' : 'rf0/port0', 'if_sw' : 'b', 'ant_port' : 'port1'},
                    'b2' :   {'rfsg' : 'if1'      , 'rfsa' : 'rf0/port1', 'if_sw' : 'b', 'ant_port' : 'port2'}}, 
            'rx' : {'b1' :   {'rfsg' : 'rf0/port0', 'rfsa' : 'if0'      , 'if_sw' : 'a', 'ant_port' : 'port1'},
                    'b2' :   {'rfsg' : 'rf0/port1', 'rfsa' : 'if1'      , 'if_sw' : 'a', 'ant_port' : 'port2'}}}

demod_state  = {'tx' : {'rfsg' : {'64qam' : {'cw'      : r"C:\repos_git\waveforms\SG_CotinousWaveform.tdms",
                                             'mod_1cc' : r"C:\repos_git\waveforms\SG_NR_FR2_Uplink_BW_100MHz_scs_120kHz_QAM64_ATE.tdms"}},
                        
                        'rfsa' : {'64qam' : {'cw'      : r"C:\repos_git\waveforms\SA_ContinousWaveform.tdms",
                                             'mod_1cc' : r"C:\repos_git\waveforms\SA_NR_FR2_Uplink_BW_100MHz_scs_120kHz_QAM64_ATE.tdms"}}},
                
                'rx' : {'rfsg' : {'64qam' : {'cw'      : r"C:\repos_git\waveforms\SG_CotinousWaveform.tdms",
                                             'mod_1cc' : r"C:\repos_git\waveforms\SG_NR_FR2_Uplink_BW_100MHz_scs_120kHz_QAM64_ATE.tdms"}}, 
                        
                        'rfsa' : {'64qam' : {'cw'      : r"C:\repos_git\waveforms\SA_ContinousWaveform.tdms",
                                             'mod_1cc' : r"C:\repos_git\waveforms\SA_NR_FR2_Uplink_BW_100MHz_scs_120kHz_QAM64_ATE.tdms"}}}}
class Mode(Enum):
    nr_single = 0
    nr_multi  = 1
    spec_an   = 2
    txp       = 3

class Test(Enum):
    evm_chp   = 'evm_chp'
    aclr      = 'aclr'
    spectrum  = 'spectrum'
    txp       = 'txp'
    temp_sweep= 'temp_sweep'

mode = Mode.spec_an
meas = Test.spectrum

def config_generator(txrx='tx', beam='b1', qam='64qam', cc=1, freq=5e9, pwr=-20, ext_atten=0, lo_offset="auto"):
    port_map_filtered = port_map[txrx][beam]
    logging.info(" Tester.config_generator: SG Port :{}, cc :{}, Freq :{} Hz, Pwr :{} dBm, Atten :{} dB".format(port_map_filtered['rfsg'], cc, freq, pwr, ext_atten))

    inst.rfsg.RF_off()
    inst.rfsg.config(port=port_map_filtered['rfsg'], freq=freq, pwr=pwr)
    inst.rfsg.config_LO(lo_sharing='disabled', lo_offset=lo_offset)
    
    if (mode == Mode.nr_single) or (mode == Mode.nr_multi):
        sg_path = demod_state[txrx]['rfsg'][qam]['mod_{}cc'.format(cc)]
    elif (mode == Mode.spec_an) or (mode == Mode.txp):
        sg_path = demod_state[txrx]['rfsg'][qam]['cw']
    logging.info(" load SG wavefome file is {}".format(sg_path))
    
    inst.rfsg.load_waveform(waveform_path=sg_path)
    inst.rfsg.rfsg_session.RF.ExternalGain = ext_atten
    inst.rfsg.mod_on()
    return 0

def config_analyzer(txrx='tx', beam='b1', qam='64qam', cc=1, freq=28e9, ref_level=-30, ext_atten=0):
    port_map_filtered = port_map[txrx][beam]
    logging.info(" Tester.config_analyzer: SA Port :{}, cc :{}, Freq :{} Hz, Ref :{} dBm, Atten :{} dB".format(port_map_filtered['rfsa'], cc, freq, ref_level, ext_atten))
    
    if (mode == Mode.nr_single) or (mode == Mode.nr_multi):
        sa_path = demod_state[txrx]['rfsa'][qam]['mod_{}cc'.format(cc)]
        inst.rfmx.set_mode(mode="nr")
        inst.rfmx.load_state(path=sa_path)
    elif (mode == Mode.spec_an) or (mode == Mode.txp):
        sa_path = demod_state[txrx]['rfsa'][qam]['cw']
        inst.rfmx.set_mode(mode="spec_an")
        inst.rfmx.load_state(path=sa_path)
        # 스펙트럼 기본값은 아래 meas_settings에서 재설정
    logging.info(" load SA wavefome file is {}".format(sa_path))
        
    inst.rfmx.config(port=port_map_filtered['rfsa'], freq=freq)
    inst.rfmx.config_LO(lo_sharing='disabled', lo_leakage_avoidance=True) 
    inst.rfmx.meas_mode.ConfigureRF("", freq, ref_level, ext_atten)
    return 0

def meas_settings(meas=Test.spectrum, txrx='tx', cc=1, avgCnt=3):
    if (meas == Test.spectrum):
        # SPECTRUM 기본 세팅 (레퍼런스 스타일)
        rbw_filter_type = an_mx.RFmxSpecAnMXSpectrumRbwFilterType.FftBased
        rbw = 10e3
        span = 1e6
        inst.rfmx.meas_mode.Spectrum.Configuration.ConfigureSpan("", span)
        inst.rfmx.meas_mode.Spectrum.Configuration.ConfigureRbwFilter("", True, rbw, rbw_filter_type)
        averagingEnabled = True
        averagingCount = avgCnt
        averagingType = an_mx.RFmxSpecAnMXSpectrumAveragingType.Rms
        inst.rfmx.meas_mode.Spectrum.Configuration.ConfigureAveraging("", averagingEnabled, averagingCount, averagingType)
    elif (meas == Test.txp):
            rbw = 10e3
            vbw = 30e3 
            rbw_filter_type = nr_mx.RFmxNRMXAcpRbwFilterType.Gaussian
            inst.rfmx.meas_mode.SelectMeasurements("", inst.rfmx.rfmx_sa.RFmxSpecAnMXMeasurementTypes.Txp, True)
            inst.rfmx.meas_mode.Spectrum.Configuration.ConfigureRbwFilter("", True, rbw, rbw_filter_type)
            if txrx == 'tx':
                inst.rfmx.meas_mode.Spectrum.Configuration.ConfigureRbwFilter("", True, rbw, rbw_filter_type)
    pass

def meas_results(meas=Test.spectrum, cc=1, sleep=.005, autoLevel=.001, timeout=30, logEn=False, include_delta=False):
    if (meas == Test.spectrum):
        autolevel_bw = 100e3
        try:
            inst.rfmx.meas_mode.AutoLevel("", autolevel_bw, 0.001, 0)
        except:
            time.sleep(0.001)
            inst.rfmx.meas_mode.AutoLevel("", autolevel_bw, 0.001, 0)
        inst.rfmx.meas_mode.Initiate("", "")
        inst.rfmx.meas_mode.WaitForMeasurementComplete("", -1)
        pk_pwr = inst.rfmx.meas_mode.Spectrum.Results.GetPeakAmplitude("", timeout)[1]
        pk_freq = inst.rfmx.meas_mode.Spectrum.Results.GetPeakFrequency("", timeout)[1]
        if logEn:
            logging.info(" -------Center Carrier Spectrum Measurements-------")
            logging.info(" Peak Amplitude[dBm]:\t{:.2f}".format(pk_pwr))
            logging.info(" Peak Frequency(GHz):\t{:.6f}".format(pk_freq/1e9))
        return [pk_pwr, pk_freq]
    elif (meas == Test.txp):
            inst.rfmx.meas_mode.Initiate("", "")
            inst.rfmx.meas_mode.WaitForMeasurementComplete("", -1)
            avg_pwr = inst.rfmx.meas_mode.Txp.Results.GetAverageMeanPower("", 30)[1]
            return [avg_pwr, 0]
    else:
        logging.info('Selected meas not implemented in this flow.')
        return [float('nan'), float('nan')]
    

# CSV 유틸
import csv
from typing import List
def init_result_matrix(phases: int = 64, elements: int = 32):
    return [[0.0 for _ in range(elements)] for _ in range(phases)]

def save_matrix_csv(matrix: List[List[float]], csv_path: str, include_phase_col: bool = True):
    header = []
    if include_phase_col:
        header.append("phase_idx")
    header += [f"el{e}" for e in range(32)]
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for p in range(len(matrix)):
            row = [p] + matrix[p] if include_phase_col else matrix[p]
            w.writerow(row)
    logger.info(f"CSV save complete: {csv_path}")

# ===============================  Phase Cal Select  =================================
phase_cal_method = 'original' # 'original' 'rev' 'irev' 'maxcal'

# ===============================  Phase Cal  =================================
SETTLE_TIME_S = 0.1
EXTRA_WAIT_AFTER_SG_S = 3.0
SG_FIXED_POWER_DBM = -20.0

# 1) 참조 엘리먼트 고정 설정 (gain 10, phase 0)
element_on_withPhase(beam, pol, 0, 7, 17)  # 17번 reference beam = 'b1', pol = 'h', phase = 0, g_default = 10, el = 0

# 2) NI 장비 구성 (네 레퍼런스 함수 사용)
config_generator(txrx=txrx, beam=beam, qam='64qam', cc=1, freq=if_freq, pwr=SG_FIXED_POWER_DBM, ext_atten=0)
time.sleep(EXTRA_WAIT_AFTER_SG_S)
config_analyzer(txrx=txrx, beam=beam, qam='64qam', cc=1, freq=rf_freq, ref_level=0, ext_atten=0)
meas_settings(meas=Test.txp, txrx=txrx, cc=1)

# 3) 결과 매트릭스 준비 (행=phase, 열=element; 17은 0으로 유지)
result = init_result_matrix(phases=64, elements=32)

try:
    # ===================== 기존 Doosan이 사용하는 Phase Cal 방법 (Ref=17번, gain=7 기준) =====================
    if phase_cal_method == 'original':      #phase sweep cal
        t0 = time.perf_counter_ns()                                                         ##########################Time 측정 시작
        best_phase_idx = [0]*32
        best_power_dbm = [float("-inf")]*32
        for element in range(32):       
            max_pwr = float("-inf")
            max_idx = 0
            if element == 17:           # 엘리먼트 0..31 (단, 17은 스킵)
                logger.info("Reference Element(17) skip and fill all 0")
                continue

            gs.config_TX_FE_all_off()           # sweep 시작 전 모든 element turn off
            element_on_withPhase(beam, pol, 0, 7, 17)       # Reference element 17번만 ON

            logger.info(f"[Element {element}] ON, Phase sweep start")
            for phase in range(64):
                element_on_withPhase(beam, pol, phase, 7, element)
                time.sleep(SETTLE_TIME_S)
                pk_pwr_dbm, _pk_freq = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
                if pk_pwr_dbm > max_pwr:
                    max_pwr = pk_pwr_dbm
                    max_idx = phase
                    logger.info(f"[El {element:02d}] phase {phase:02d} -> {pk_pwr_dbm:.2f} dBm  (NEW MAX)")
                result[phase][element] = pk_pwr_dbm
                logger.info(f"[El {element:02d}] phase {phase:02d} -> {pk_pwr_dbm:.2f} dBm")
            best_phase_idx[element] = max_idx
            best_power_dbm[element] = max_pwr
            print(f'max power: {max_pwr} max index: {max_idx}')
            element_on_withPhase(beam, pol, max_idx, 7, element)

        for i, (idx, pwr) in enumerate(zip(best_phase_idx, best_power_dbm)):
            if math.isfinite(pwr):
                print(f"#{i:02d}: {idx}(index), {pwr:.2f}(dBm)")
            else:
                # 예: 참조 엘리먼트 17은 -inf라 N/A로 표기
                print(f"#{i:02d}: {idx}(index), N/A(dBm)")                                    

        #gain sweep cal
        #17번은 gain=7에서 파워 측정 후 OFF
        #각 element(0..31, 17 제외)는 gain 4~10 스윕해서 참조 파워와 가장 유사한 gain 선택

        GAIN_SWEEP_RANGE = range(4, 11)  # 4~10 inclusive
        matched_gain = [None]*32
        matched_pwr  = [None]*32
        gain_err_db  = [None]*32  # (elem_power - ref_power)

        # 1) 참조(17번) @ gain=7 파워 측정
        gs.config_TX_FE_all_off()
        ref_phase = 0
        try:
            # phase 보정 결과가 있으면 사용, 없으면 0
            ref_phase = best_phase_idx[17]
        except Exception:
            ref_phase = 0

        element_on_withPhase(beam, pol, ref_phase, 7, 17)   
        time.sleep(SETTLE_TIME_S)
        ref_pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
        logger.info(f"[REF el17] phase={ref_phase}, gain=7 -> {ref_pwr_dbm:.2f} dBm")

        # 참조 OFF
        gs.config_TX_FE_all_off()

        # 2) 각 엘리먼트에 대해 gain 4~10 스윕 → 참조 파워에 가장 가까운 gain 선택
        for element in range(32):
            if element == 17:
                logger.info("Skip element 17 (reference)")
                matched_gain[element] = 7
                matched_pwr[element]  = ref_pwr_dbm
                gain_err_db[element]  = 0.0
                continue

            # 이 엘리먼트에서 사용할 phase (phase 보정값 사용; 없으면 0)
            try:
                el_phase = best_phase_idx[element]
            except Exception:
                el_phase = 0

            best_g   = None
            best_pwr = None
            min_err  = float("inf")

            logger.info(f"[El {element:02d}] Gain sweep start (phase={el_phase}, target={ref_pwr_dbm:.2f} dBm)")
            for g in GAIN_SWEEP_RANGE:
                gs.config_TX_FE_all_off()
                element_on_withPhase(beam, pol, el_phase, g, element)
                time.sleep(SETTLE_TIME_S)
                pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)

                err = abs(pwr_dbm - ref_pwr_dbm)
                logger.info(f"[El {element:02d}] gain={g:2d} -> {pwr_dbm:.2f} dBm (Δ={pwr_dbm - ref_pwr_dbm:+.2f} dB)")

                if err < min_err:
                    min_err  = err
                    best_g   = g
                    best_pwr = pwr_dbm

            # 스윕 종료: 최적 gain 적용
            matched_gain[element] = best_g
            matched_pwr[element]  = best_pwr
            gain_err_db[element]  = (best_pwr - ref_pwr_dbm) if best_pwr is not None else None

            gs.config_TX_FE_all_off()
            element_on_withPhase(beam, pol, el_phase, best_g, element)
            logger.info(f"[El {element:02d}] BEST gain={best_g}, phase={el_phase} -> {best_pwr:.2f} dBm (Δ={best_pwr - ref_pwr_dbm:+.2f} dB)")

        dt_ns = time.perf_counter_ns() - t0                                                     ##########################Time 측정 끝
        # (선택) 요약 출력
        import math
        for i, (g, p, d) in enumerate(zip(matched_gain, matched_pwr, gain_err_db)):
            if p is None or not math.isfinite(p):
                print(f"#{i:02d}: gain={g}, power=N/A,  Δ=N/A")
            else:
                print(f"#{i:02d}: gain={g}, power={p:.2f} dBm, Δ={d:+.2f} dB")

        print(f"elapsed: {dt_ns/1e6:.3f} ms")                                                   ###########################Time 측정 결과 출력
        
        logger.info("[APPLY] Apply final original phase (per-element) and final gain to all elements")
        gs.config_TX_FE_all_off()
        for n in range(32):
            phase_final = best_phase_idx[n] if best_phase_idx[n] is not None else 0
            gain_final  = matched_gain[n]          if matched_gain[n]          is not None else 7
            element_on_withPhase(beam, pol, phase_final, gain_final, n)

        time.sleep(0.2)
        final_pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
        logger.info(f"[FINAL] TxP Avg Mean Power (proxy EIRP) = {final_pwr_dbm:.2f} dBm")

        # CSV 저장 (phase sweep 결과, gain/phase 선택된 index table)
        CSV_PATH = r"C:\Users\Dosan\Desktop\Sejin\00. Sejin Archive\gain_index_sweep_log_original.csv"
        save_matrix_csv(result, CSV_PATH, include_phase_col=True)
        open(os.path.splitext(CSV_PATH)[0] + "_settings.csv","w").write("element,phase_idx,gain_idx\n" + "\n".join(f"{i},{best_phase_idx[i]},{matched_gain[i]}" for i in range(32)))

        
   # ===================================================  REV Calibration  ===========================================================
    elif phase_cal_method == 'rev':
        t0 = time.perf_counter_ns()


        # ====================== 선택 옵션 ======================
        # 'fast'    : 한 번의 미세 스윕 (현재 방식)
        # 'two_pass': 1차 피크로 중심 재정렬 후 2차 미세 스윕 (후반 미세 변화 대응)
        rev_mode = "two_pass"            # "fast" 또는 "two_pass"
        AVG_N    =  1                    # 측정 평균 횟수 (1~3 권장)
        USE_ACCUM = True                 # 서브-스텝 누산 보정 (양자화 완화)

        # ---------- helpers ----------
        PHASE_STEP_RAD = 2.0 * math.pi / 64.0   # 1 step = 360/64 = 5.625°
        SETTLE_TIME_S  = 0.10
        FINE_HALF_WIN  = 16                     # ±16 index (≈ ±90°)

        def wrap_idx(i, m=64): return (i + m) % m

        def ang_wrap_rad(a):
            while a >= math.pi:  a -= 2*math.pi
            while a <  -math.pi: a += 2*math.pi
            return a

        def fine_indices(center, half_win=FINE_HALF_WIN):
            return [wrap_idx(center + k) for k in range(-half_win, half_win + 1)]  # 포함형 → 총 33포인트

        def dbm_to_mw(p_dbm):  return 10.0 ** (p_dbm / 10.0)
        def mw_to_v(p_mw):     return math.sqrt(max(p_mw * 1e-3, 0.0))  # mW→W 변환 후 √ → |E|

        def measure_power_avg():
            """AVG_N번 측정해서 전력 선형 평균 후 dBm 변환."""
            if AVG_N <= 1:
                return meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)[0]
            ps = []
            for _ in range(AVG_N):
                p_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
                ps.append(dbm_to_mw(p_dbm))
            p_avg_mw = sum(ps) / max(len(ps), 1)
            return 10.0 * math.log10(max(p_avg_mw, 1e-15))

        # ---------- RAW 버퍼 초기화 (행=phase 0..63, 열=element 0..31) ----------
        # 베이스라인에 이미 있으면 이 줄은 생략 가능하나, 안전하게 재초기화
        result = [[float("nan") for _ in range(32)] for _ in range(64)]

        # ---------- initialize: all ON with phase=0, gain=7 ----------
        logger.info("REV: Initialize all elements ON with phase=0, gain=7")
        for el in range(32):
            element_on_withPhase(beam, pol, 0, 7, el)
        time.sleep(0.2)

        # ---------- 저장 버퍼 ----------
        base_phase_idx   = [0]*32      # PASS-1 결과 (π 오프셋 보정된 기준 위상 ϕ′)
        best_phase_idx   = [0]*32      # PASS-2 결과 (최종 위상)
        mu_list          = [None]*32
        gamma_list       = [None]*32
        delta0_deg_list  = [None]*32
        X_idx_list       = [None]*32
        offset_flag      = [0]*32      # 0: no π, 1: +π
        phase_accum_rad  = [0.0]*32    # 서브-스텝 누산기 (라디안)
        gain_idx_state   = [7]*32      # (현재 게인 인덱스 상태; 필요시 이후 게인 캘에서 갱신)

        logger.info("REV: Flow = PASS-1(two-point) -> PASS-2(fine sweep) [-> PASS-2b if two_pass] -> compute X -> apply (+accum)")

        def do_fine_sweep(elem, center_idx):
            """center_idx 기준 ±16 인덱스 스윕, RAW 기록 및 피크 탐색 후 (Emax,Emin, i_max) 반환"""
            idxs = fine_indices(center_idx, FINE_HALF_WIN)
            pk = float("-inf"); i_max = center_idx
            for idx in idxs:
                element_on_withPhase(beam, pol, idx, 7, elem)
                time.sleep(SETTLE_TIME_S)
                p_dbm = measure_power_avg()
                result[idx][elem] = p_dbm  # RAW 저장(행=phase, 열=element)
                if p_dbm > pk:
                    pk = p_dbm; i_max = idx
                logger.info(f"[PASS-2][El {elem:02d}] phase {idx:02d} -> {p_dbm:.3f} dBm")

            P_mw_max = dbm_to_mw(max(result[i][elem] for i in idxs))
            P_mw_min = dbm_to_mw(min(result[i][elem] for i in idxs))
            E_max = mw_to_v(P_mw_max)
            E_min = mw_to_v(P_mw_min)
            return E_max, E_min, i_max

        # ---------- 요소별 순차 ----------
        for n in range(32):
            if n == 17:
                logger.info("[El 17] reference skipped")
                continue

            # === PASS-1: 두 점(ϕ, ϕ+π)으로 π 오프셋 판별 ===
            phi_probe = best_phase_idx[n] if best_phase_idx[n] else 0

            # P(ϕ)
            element_on_withPhase(beam, pol, phi_probe, 7, n)
            time.sleep(SETTLE_TIME_S)
            P0_dbm = measure_power_avg()

            # P(ϕ+π)
            element_on_withPhase(beam, pol, wrap_idx(phi_probe + 32), 7, n)
            time.sleep(SETTLE_TIME_S)
            P1_dbm = measure_power_avg()

            # 전압 크기(|E|) 비교 → 0/π 쏠림 방지
            A0 = mw_to_v(dbm_to_mw(P0_dbm))
            A1 = mw_to_v(dbm_to_mw(P1_dbm))
            logger.info(f"[PASS-1][El {n:02d}] P(phi)={P0_dbm:.3f} dBm, P(phi+pi)={P1_dbm:.3f} dBm, |E0|={A0:.4e}, |E1|={A1:.4e}")

            if A1 < A0:
                base_phase_idx[n] = phi_probe
                offset_flag[n]    = 0
                logger.info(f"[PASS-1][El {n:02d}] offset=NO, phi_base={base_phase_idx[n]}")
            else:
                base_phase_idx[n] = wrap_idx(phi_probe + 32)
                offset_flag[n]    = 1
                logger.info(f"[PASS-1][El {n:02d}] offset=YES(pi), phi_base={base_phase_idx[n]}")

            # 기준 위상 적용 후 PASS-2
            c = base_phase_idx[n]
            element_on_withPhase(beam, pol, c, 7, n)

            # === PASS-2: 미세 스윕 ===
            if rev_mode == "fast":
                E_max, E_min, i_max = do_fine_sweep(n, c)
            else:  # "two_pass"
                logger.info(f"[PASS-2a][El {n:02d}] first fine sweep around c={c}")
                E_max_a, E_min_a, i_max_a = do_fine_sweep(n, c)
                c = i_max_a
                element_on_withPhase(beam, pol, c, 7, n)
                logger.info(f"[PASS-2b][El {n:02d}] recentered to c={c}, second fine sweep")
                E_max, E_min, i_max = do_fine_sweep(n, c)

            # μ 계산 (진폭 기준) 및 Γ 케이스 판정
            mu = (E_max - E_min) / max(E_max + E_min, 1e-15)
            mu = max(0.0, min(mu, 0.999))  # clamp
            mu_list[n] = mu

            E0a = 0.5*(E_max + E_min)
            Ena = 0.5*(E_max - E_min)
            if Ena <= E0a:
                case_str = "outside"
                Gamma = Ena / max(E0a, 1e-15)
            else:
                case_str = "inside"
                Gamma = E0a / max(Ena, 1e-15)
            gamma_list[n] = Gamma

            # Δ0: 중심(c) 대비 최대점(i_max) 각도 → Δ0 = -θ_max
            theta_max = ang_wrap_rad((i_max - c) * PHASE_STEP_RAD)
            Delta0 = ang_wrap_rad(-theta_max)
            Delta0_deg = Delta0 * 180.0 / math.pi
            delta0_deg_list[n] = Delta0_deg

            # 보정 X(rad) = atan2(Γ sinΔ0, 1 + Γ cosΔ0)
            X_rad = math.atan2(Gamma * math.sin(Delta0), 1.0 + Gamma * math.cos(Delta0))

            # --- 서브-스텝 누산 보정 (임계: 0.5 step 초과 시 1 step 적용) ---
            if USE_ACCUM:
                phase_accum_rad[n] += X_rad
                if abs(phase_accum_rad[n]) >= (PHASE_STEP_RAD / 2.0):
                    apply_steps = int(math.copysign(1, phase_accum_rad[n]))  # ±1 step만 적용 (필요시 누적)
                    phase_accum_rad[n] -= apply_steps * PHASE_STEP_RAD
                    X_idx = (-apply_steps) % 64  # new_idx = c - X_idx 규약 유지
                else:
                    X_idx = 0
            else:
                X_idx = int(round(X_rad / PHASE_STEP_RAD)) % 64

            X_idx_list[n] = X_idx
            new_idx = wrap_idx(c - X_idx)   # 최종 적용
            element_on_withPhase(beam, pol, new_idx, 7, n)
            best_phase_idx[n] = new_idx

            logger.info(f"[RESULT][El {n:02d}] mode={rev_mode}, case={case_str}, mu={mu:.4f}, Γ={Gamma:.4f}, Δ0={Delta0_deg:.2f}°, X_idx={X_idx}, final_idx={new_idx}")

        # ---------- PASS-2 RAW 저장 (행=phase, 열=element) ----------
        CSV_PATH = r"C:\Users\Dosan\Desktop\Sejin\00. Sejin Archive\gain_index_sweep_log_rev.csv"
        try:
            os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
        except Exception as e:
            logger.warning(f"[SAVE] mkdir fail for {CSV_PATH}: {e}")
        save_matrix_csv(result, CSV_PATH, include_phase_col=True)
        logger.info(f"[SAVE] PASS-2 RAW matrix -> {CSV_PATH}")

        # ---------- 최종 Phase/Gain 테이블 저장 ----------
        import csv, datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = os.path.dirname(CSV_PATH) or "."
        final_path = os.path.join(out_dir, f"rev_result_phase_gain_{rev_mode}_{ts}.csv")
        try:
            with open(final_path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["element", "phase_idx", "gain_idx"])
                for el in range(32):
                    if el == 17:
                        w.writerow([el, "REF(17)", "REF(17)"])
                    else:
                        w.writerow([el, best_phase_idx[el], gain_idx_state[el]])
            logger.info(f"[SAVE] Final phase/gain table -> {final_path}")
        except Exception as e:
            logger.error(f"[SAVE][ERROR] Cannot write final table: {e}")


        # ============================== Gain Alignment (Two Methods) ==============================
        # 공통: 참조(17) 단독 파워 @ gain=7
        gs.config_TX_FE_all_off()
        ref_phase_idx = best_phase_idx[17] if best_phase_idx[17] else 0
        element_on_withPhase(beam, pol, ref_phase_idx, 7, 17)
        time.sleep(SETTLE_TIME_S)
        ref_pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
        logger.info(f"[GAIN][REF 17] phase={ref_phase_idx}, gain=7 -> {ref_pwr_dbm:.2f} dBm")

        # ---- Method-A: Single-element sweep to match reference power ----
        logger.info("[GAIN][Method-A] Single-element sweep (4..10) to match reference power")
        GAIN_SWEEP_RANGE = range(4, 11)
        gain_A = [7]*32
        for n in range(32):
            if n == 17:
                gain_A[n] = 7
                continue
            el_phase = best_phase_idx[n] if best_phase_idx[n] else 0
            best_g, best_p, min_err = None, None, float("inf")
            for g in GAIN_SWEEP_RANGE:
                gs.config_TX_FE_all_off()
                element_on_withPhase(beam, pol, el_phase, g, n)
                time.sleep(SETTLE_TIME_S)
                p_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
                err = abs(p_dbm - ref_pwr_dbm)
                if err < min_err:
                    min_err, best_g, best_p = err, g, p_dbm
                logger.info(f"[GAIN-A][El {n:02d}] phase={el_phase}, gain={g:2d} -> {p_dbm:.2f} dBm, d={p_dbm - ref_pwr_dbm:+.2f} dB")
            gain_A[n] = best_g
            logger.info(f"[GAIN-A][El {n:02d}] selected_gain={best_g}, power={best_p:.2f} dBm, error={best_p - ref_pwr_dbm:+.2f} dB")

        # ---- Method-B: Formula-based K to gain index (clamped 4..10) ----
        logger.info("[GAIN][Method-B] Formula-based K to gain index (clamped to 4..10)")
        gain_B = [7]*32
        for n in range(32):
            if n == 17:
                gain_B[n] = 7
                continue

            Gamma = gamma_list[n]
            Delta0 = (delta0_deg_list[n] or 0.0) * math.pi / 180.0

            # [FIX] 수치 안정성: Gamma/1/Gamma 분기 전에 None/경계값 처리
            if Gamma is None or not math.isfinite(Gamma):
                K = 1.0
                case_str = "unknown"
            elif Gamma <= 1.0:
                denom = math.sqrt(max(1.0 + 2.0*Gamma*math.cos(Delta0) + Gamma*Gamma, 1e-15))
                K = Gamma / denom
                case_str = "outside"
            else:
                ginv = 1.0 / max(Gamma, 1e-15)
                denom = math.sqrt(max(1.0 + 2.0*ginv*math.cos(Delta0) + ginv*ginv, 1e-15))
                K = ginv / denom
                case_str = "inside"

            # [FIX] 전압비 → dB → 1 dB/step 매핑 (base=7), clamp
            delta_db = 20.0 * math.log10(max(K, 1e-12))
            g_idx = 7 + int(round(delta_db))
            g_idx = max(4, min(10, g_idx))
            gain_B[n] = g_idx
            logger.info(f"[GAIN-B][El {n:02d}] case={case_str}, Gamma={Gamma if Gamma is not None else float('nan'):.2f}, "
                        f"Delta0={delta0_deg_list[n]:.2f}, K={K:.3f}, delta_db={delta_db:+.2f} dB -> gain_idx={g_idx}")

        # ---- 최종 적용: 원하는 방법 선택 Method-A or Method-B 적용 예시 ----
        logger.info("[APPLY] Apply final REV phase (per-element) and final gain (Method-B) to all elements")
        gs.config_TX_FE_all_off()
        for n in range(32):
            phase_final = best_phase_idx[n] if best_phase_idx[n] is not None else 0
            gain_final  = gain_A[n]          if gain_A[n]          is not None else 7
            element_on_withPhase(beam, pol, phase_final, gain_final, n)

        time.sleep(0.2)
        final_pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
        logger.info(f"[FINAL] TxP Avg Mean Power (proxy EIRP) = {final_pwr_dbm:.2f} dBm")

        # 요약 로그
        for i in range(32):
            if i== 17:
                continue
            logger.info(f"[SUMMARY][El {i:02d}] phi_base={base_phase_idx[i]}, phi_final={best_phase_idx[i]}, "
                        f"mu={mu_list[i]:.2f}, Gamma={gamma_list[i]:.2f}, Delta0={delta0_deg_list[i]:.2f}, X_idx={X_idx_list[i]}, "
                        f"offset_pi={offset_flag[i]}")
        dt_ns = time.perf_counter_ns() - t0
        print(f"elapsed: {dt_ns/1e6:.3f} ms")

        # 요약 CSV 저장 (phase/gain index 테이블)
        import os
        open(os.path.splitext(CSV_PATH)[0] + "_settings_rev.csv","w").write(
            "element,phase_idx,gain_idx\n" + "\n".join(f"{i},{best_phase_idx[i]},{gain_A[i]}" for i in range(32))
        )

    # ===================================================  IREV Calibration (REV + attenuation probe)  ==================================================================
    elif phase_cal_method == 'irev':
        t0 = time.perf_counter_ns()

        # ====================== 선택 옵션 ======================
        # 'fast'    : 한 번의 미세 스윕
        # 'two_pass': 1차 피크로 중심 재정렬 후 2차 미세 스윕
        rev_mode   = "two_pass"
        AVG_N      = 1                      # dBm 평균 측정 횟수
        USE_ACCUM  = True                   # 서브-스텝 누산 보정
        # ----- IREV 전용 옵션 -----
        irev_atten_db             = 2.0     # 감쇠 탐침 크기(1~3 dB 권장)
        irev_min_probe_halfwin    = 8       # 최소점 주변 재스윕 반경(±step, 기본 ±45°)
        irev_verify_after_apply   = True    # 보정 후 짧은 검증 스윕

        # ---------- helpers ----------
        PHASE_STEP_RAD = 2.0 * math.pi / 64.0   # 5.625°
        SETTLE_TIME_S  = 0.10
        FINE_HALF_WIN  = 16                     # ±16 index(≈±90°)

        def wrap_idx(i, m=64): return (i + m) % m

        def ang_wrap_rad(a):
            while a >= math.pi:  a -= 2*math.pi
            while a <  -math.pi: a += 2*math.pi
            return a

        def fine_indices(center, half_win):
            return [wrap_idx(center + k) for k in range(-half_win, half_win + 1)]  # 포함형

        def dbm_to_mw(p_dbm):  return 10.0 ** (p_dbm / 10.0)
        def mw_to_v(p_mw):     return math.sqrt(max(p_mw * 1e-3, 0.0))  # mW→W→|E|

        def measure_power_avg():
            """AVG_N번 측정해서 전력 선형 평균 후 dBm 변환."""
            if AVG_N <= 1:
                return meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)[0]
            ps = []
            for _ in range(AVG_N):
                p_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
                ps.append(dbm_to_mw(p_dbm))
            p_avg_mw = sum(ps) / max(len(ps), 1)
            return 10.0 * math.log10(max(p_avg_mw, 1e-15))

        # ---------- RAW 버퍼 초기화 (행=phase 0..63, 열=element 0..31) ----------
        result = [[float("nan") for _ in range(32)] for _ in range(64)]

        # ---------- initialize: all ON with phase=0, gain=7 ----------
        logger.info("IREV: Initialize all elements ON with phase=0, gain=7")
        for el in range(32):
            element_on_withPhase(beam, pol, 0, 7, el)
        time.sleep(0.2)

        # ---------- 저장 버퍼 ----------
        base_phase_idx   = [0]*32      # PASS-1 기준 위상
        best_phase_idx   = [0]*32      # 최종 위상
        mu_list          = [None]*32
        gamma_list       = [None]*32
        delta0_deg_list  = [None]*32
        X_idx_list       = [None]*32
        offset_flag      = [0]*32      # 0: no π, 1: +π
        phase_accum_rad  = [0.0]*32
        gain_idx_state   = [7]*32      # (게인 캘 전까지는 7 유지)

        logger.info("IREV: Flow = PASS-1(two-point) -> PASS-2(fine sweep) [-> PASS-2b] -> Atten-probe(case) -> compute X -> apply (+accum)")

        def do_fine_sweep(elem, center_idx):
            """center_idx 기준 ±16 인덱스 스윕, RAW 기록 및 (Emax,Emin,i_max,i_min) 반환"""
            idxs = fine_indices(center_idx, FINE_HALF_WIN)
            pk = float("-inf"); i_max = center_idx
            mn = float("+inf"); i_min = center_idx
            for idx in idxs:
                element_on_withPhase(beam, pol, idx, 7, elem)
                time.sleep(SETTLE_TIME_S)
                p_dbm = measure_power_avg()
                result[idx][elem] = p_dbm
                if p_dbm > pk: pk, i_max = p_dbm, idx
                if p_dbm < mn: mn, i_min = p_dbm, idx
                logger.info(f"[PASS-2][El {elem:02d}] phase {idx:02d} -> {p_dbm:.3f} dBm")

            P_mw_max = dbm_to_mw(pk)
            P_mw_min = dbm_to_mw(mn)
            E_max = mw_to_v(P_mw_max)
            E_min = mw_to_v(P_mw_min)
            return E_max, E_min, i_max, i_min

        def sweep_min_power_around(elem, center_idx, halfwin, gain_idx):
            """center_idx±halfwin 범위에서 지정 gain으로 스윕해 최소 전력(dBm)과 index를 반환"""
            idxs = fine_indices(center_idx, halfwin)
            mn = float("+inf"); i_min = center_idx
            for idx in idxs:
                element_on_withPhase(beam, pol, idx, gain_idx, elem)
                time.sleep(SETTLE_TIME_S)
                p_dbm = measure_power_avg()
                if p_dbm < mn:
                    mn, i_min = p_dbm, idx
            return mn, i_min

        # ---------- 요소별 순차 ----------
        for n in range(32):
            if n == 17:
                logger.info("[El 17] reference skipped")
                continue

            # === PASS-1: 두 점(ϕ, ϕ+π)으로 π 오프셋 판별 ===
            phi_probe = best_phase_idx[n] if best_phase_idx[n] else 0

            element_on_withPhase(beam, pol, phi_probe, 7, n)
            time.sleep(SETTLE_TIME_S)
            P0_dbm = measure_power_avg()

            element_on_withPhase(beam, pol, wrap_idx(phi_probe + 32), 7, n)
            time.sleep(SETTLE_TIME_S)
            P1_dbm = measure_power_avg()

            A0 = mw_to_v(dbm_to_mw(P0_dbm))
            A1 = mw_to_v(dbm_to_mw(P1_dbm))
            logger.info(f"[PASS-1][El {n:02d}] P(phi)={P0_dbm:.3f} dBm, P(phi+pi)={P1_dbm:.3f} dBm, |E0|={A0:.4e}, |E1|={A1:.4e}")

            if A1 < A0:
                base_phase_idx[n] = phi_probe
                offset_flag[n]    = 0
                logger.info(f"[PASS-1][El {n:02d}] offset=NO, phi_base={base_phase_idx[n]}")
            else:
                base_phase_idx[n] = wrap_idx(phi_probe + 32)
                offset_flag[n]    = 1
                logger.info(f"[PASS-1][El {n:02d}] offset=YES(pi), phi_base={base_phase_idx[n]}")

            # 기준 위상 적용 후 PASS-2
            c = base_phase_idx[n]
            element_on_withPhase(beam, pol, c, 7, n)

            # === PASS-2: 미세 스윕 ===
            if rev_mode == "fast":
                E_max, E_min, i_max, i_min = do_fine_sweep(n, c)
            else:  # "two_pass"
                logger.info(f"[PASS-2a][El {n:02d}] first fine sweep around c={c}")
                E_max_a, E_min_a, i_max_a, i_min_a = do_fine_sweep(n, c)
                c = i_max_a
                element_on_withPhase(beam, pol, c, 7, n)
                logger.info(f"[PASS-2b][El {n:02d}] recentered to c={c}, second fine sweep")
                E_max, E_min, i_max, i_min = do_fine_sweep(n, c)

            # μ, E0a, Ena
            mu  = (E_max - E_min) / max(E_max + E_min, 1e-15)
            mu  = max(0.0, min(mu, 0.999))
            mu_list[n] = mu

            E0a = 0.5*(E_max + E_min)
            Ena = 0.5*(E_max - E_min)

            # -------------------- IREV: 감쇠 탐침으로 inside/outside 결정 --------------------
            # 최소점 주변에서 baseline 최소 전력
            P_min0_dbm, i_min0 = sweep_min_power_around(n, i_min, irev_min_probe_halfwin, gain_idx=7)

            # 같은 윈도우에서 엘리먼트 n만 임시 감쇠 (gain index ↓ Δg)
            delta_g = int(round(irev_atten_db))
            gain_probe = max(4, 7 - delta_g)
            P_min1_dbm, i_min1 = sweep_min_power_around(n, i_min, irev_min_probe_halfwin, gain_idx=gain_probe)

            # inside/outside 판별
            if P_min1_dbm > P_min0_dbm:
                case_str = "inside"
                Gamma = E0a / max(Ena, 1e-15)
            else:
                case_str = "outside"
                Gamma = Ena / max(E0a, 1e-15)  # (= μ)

            gamma_list[n] = Gamma

            # Δ0: 중심(c) 대비 최대점(i_max) 각도 → Δ0 = −θ_max
            theta_max = ang_wrap_rad((i_max - c) * PHASE_STEP_RAD)
            Delta0    = ang_wrap_rad(-theta_max)
            Delta0_deg = Delta0 * 180.0 / math.pi
            delta0_deg_list[n] = Delta0_deg

            # 보정 X(rad) = atan2(Γ sinΔ0, 1 + Γ cosΔ0)
            X_rad = math.atan2(Gamma * math.sin(Delta0), 1.0 + Gamma * math.cos(Delta0))

            # --- 서브-스텝 누산 보정 ---
            if USE_ACCUM:
                phase_accum_rad[n] += X_rad
                if abs(phase_accum_rad[n]) >= (PHASE_STEP_RAD / 2.0):
                    apply_steps = int(math.copysign(1, phase_accum_rad[n]))  # ±1 step만
                    phase_accum_rad[n] -= apply_steps * PHASE_STEP_RAD
                    X_idx = (-apply_steps) % 64  # new_idx = c - X_idx 규약
                else:
                    X_idx = 0
            else:
                X_idx = int(round(X_rad / PHASE_STEP_RAD)) % 64

            X_idx_list[n] = X_idx
            new_idx = wrap_idx(c - X_idx)
            element_on_withPhase(beam, pol, new_idx, 7, n)
            best_phase_idx[n] = new_idx

            logger.info(f"[IREV-RESULT][El {n:02d}] mode={rev_mode}, case={case_str}, mu={mu:.4f}, Γ={Gamma:.4f}, "
                        f"Δ0={Delta0_deg:.2f}°, X_idx={X_idx}, final_idx={new_idx}, "
                        f"Pmin0={P_min0_dbm:.2f} dBm, Pmin1={P_min1_dbm:.2f} dBm, probe_gain={gain_probe}")

            # (옵션) 보정 후 짧은 검증
            if irev_verify_after_apply:
                _chk_min_dbm, _ = sweep_min_power_around(n, new_idx, halfwin=4, gain_idx=7)  # ±22.5°만 확인
                logger.info(f"[VERIFY][El {n:02d}] quick check around {new_idx}: Pmin={_chk_min_dbm:.2f} dBm")

        # ---------- PASS-2 RAW 저장 ----------
        CSV_PATH = r"C:\Users\Dosan\Desktop\Sejin\00. Sejin Archive\gain_index_sweep_log_irev.csv"
        try:
            os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
        except Exception as e:
            logger.warning(f"[SAVE] mkdir fail for {CSV_PATH}: {e}")
        save_matrix_csv(result, CSV_PATH, include_phase_col=True)
        logger.info(f"[SAVE] PASS-2 RAW matrix -> {CSV_PATH}")

        # ---------- 최종 Phase/Gain 테이블 저장 ----------
        import csv, datetime, os
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = os.path.dirname(CSV_PATH) or "."
        final_path = os.path.join(out_dir, f"irev_result_phase_gain_{rev_mode}_{ts}.csv")
        try:
            with open(final_path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["element", "phase_idx", "gain_idx"])
                for el in range(32):
                    if el == 17:
                        w.writerow([el, "REF(17)", "REF(17)"])
                    else:
                        w.writerow([el, best_phase_idx[el], 7])  # 게인은 아래 Gain Alignment에서 확정
            logger.info(f"[SAVE] Final phase/gain table (phase only) -> {final_path}")
        except Exception as e:
            logger.error(f"[SAVE][ERROR] Cannot write final table: {e}")

        # ============================== Gain Alignment (Two Methods) ==============================
        # 공통: 참조(17) 단독 파워 @ gain=7
        gs.config_TX_FE_all_off()
        ref_phase_idx = best_phase_idx[17] if best_phase_idx[17] else 0
        element_on_withPhase(beam, pol, ref_phase_idx, 7, 17)
        time.sleep(SETTLE_TIME_S)
        ref_pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
        logger.info(f"[GAIN][REF 17] phase={ref_phase_idx}, gain=7 -> {ref_pwr_dbm:.2f} dBm")

        # ---- Method-A: Single-element sweep to match reference power (최종 적용) ----
        logger.info("[GAIN][Method-A] Single-element sweep (4..10) to match reference power")
        GAIN_SWEEP_RANGE = range(4, 11)
        gain_A = [7]*32
        for n in range(32):
            if n == 17:
                gain_A[n] = 7
                continue
            el_phase = best_phase_idx[n] if best_phase_idx[n] else 0
            best_g, best_p, min_err = None, None, float("inf")
            for g in GAIN_SWEEP_RANGE:
                gs.config_TX_FE_all_off()
                element_on_withPhase(beam, pol, el_phase, g, n)
                time.sleep(SETTLE_TIME_S)
                p_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
                err = abs(p_dbm - ref_pwr_dbm)
                if err < min_err:
                    min_err, best_g, best_p = err, g, p_dbm
                logger.info(f"[GAIN-A][El {n:02d}] phase={el_phase}, gain={g:2d} -> {p_dbm:.2f} dBm, d={p_dbm - ref_pwr_dbm:+.2f} dB")
            gain_A[n] = best_g
            logger.info(f"[GAIN-A][El {n:02d}] selected_gain={best_g}, power={best_p:.2f} dBm, error={best_p - ref_pwr_dbm:+.2f} dB")

        # ---- Method-B: Formula-based K → gain index (로그만 남김) ----
        logger.info("[GAIN][Method-B] Formula-based K to gain index (clamped to 4..10)")
        gain_B = [7]*32
        for n in range(32):
            if n == 17:
                gain_B[n] = 7
                continue
            Gamma = gamma_list[n]
            Delta0 = (delta0_deg_list[n] or 0.0) * math.pi / 180.0
            if Gamma is None or not math.isfinite(Gamma):
                K = 1.0; case_str = "unknown"
            elif Gamma <= 1.0:
                denom = math.sqrt(max(1.0 + 2.0*Gamma*math.cos(Delta0) + Gamma*Gamma, 1e-15))
                K = Gamma / denom; case_str = "outside"
            else:
                ginv = 1.0 / max(Gamma, 1e-15)
                denom = math.sqrt(max(1.0 + 2.0*ginv*math.cos(Delta0) + ginv*ginv, 1e-15))
                K = ginv / denom; case_str = "inside"
            delta_db = 20.0 * math.log10(max(K, 1e-12))
            g_idx = 7 + int(round(delta_db)); g_idx = max(4, min(10, g_idx))
            gain_B[n] = g_idx
            logger.info(f"[GAIN-B][El {n:02d}] case={case_str}, Γ={Gamma if Gamma is not None else float('nan'):.2f}, "
                        f"Δ0={delta0_deg_list[n]:.2f}, K={K:.3f}, delta_db={delta_db:+.2f} dB -> gain_idx={g_idx}")

        # ---- 최종 적용: 요청대로 Method-A를 실제 적용 ----
        logger.info("[APPLY] Apply final IREV phase (per-element) and final gain (Method-A) to all elements")
        gs.config_TX_FE_all_off()
        for n in range(32):
            phase_final = best_phase_idx[n] if best_phase_idx[n] is not None else 0
            gain_final  = gain_A[n]          if gain_A[n]          is not None else 7
            element_on_withPhase(beam, pol, phase_final, gain_final, n)

        time.sleep(0.2)
        final_pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
        logger.info(f"[FINAL] TxP Avg Mean Power (proxy EIRP) = {final_pwr_dbm:.2f} dBm")

        # 요약 로그
        for i in range(32):
            if i == 17: continue
            logger.info(f"[SUMMARY][El {i:02d}] phi_base={base_phase_idx[i]}, phi_final={best_phase_idx[i]}, "
                        f"mu={mu_list[i]:.2f}, Gamma={gamma_list[i]:.2f}, Delta0={delta0_deg_list[i]:.2f}, "
                        f"X_idx={X_idx_list[i]}, offset_pi={offset_flag[i]}, gainA={gain_A[i]}")

        # 경과 시간
        dt_ns = time.perf_counter_ns() - t0
        print(f"elapsed: {dt_ns/1e6:.3f} ms")

        # 요약 CSV 저장 (phase/gain index 테이블)
        open(os.path.splitext(CSV_PATH)[0] + "_settings_irev.csv","w").write(
            "element,phase_idx,gain_idx\n" + "\n".join(f"{i},{best_phase_idx[i]},{gain_A[i]}" for i in range(32))
        )



    # ===================================================  MAX Calibration (Coarse 45° -> Fine 5.625°) + Gain Alignment  ================
    elif phase_cal_method == 'maxcal':
        t0 = time.perf_counter_ns()                                                         ##########################Time 측정 시작
        
        COARSE_STEP = 8           # 45° = 8 index
        FINE_HALF_WINDOW = 4     # ±4 index ≈ ±22.5°
        SETTLE_TIME_S = 0.1

        def wrap_range(center_idx, half_window, modulo=64):
            return [ (center_idx + k) % modulo for k in range(-half_window, half_window + 1) ]

        def sweep_indices_and_measure(element, indices):
            """대상 element의 phase를 indices 순서대로 바꾸며 |E_total| 측정.
               측정 지점은 result[phase][element]에 기록하고, (best_idx, best_pwr) 반환."""
            best_idx = None
            best_pwr = float("-inf")
            for idx in indices:
                element_on_withPhase(beam, pol, idx, 7, element)   # 대상 소자만 위상 변경
                time.sleep(SETTLE_TIME_S)
                pk_pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)

                # RAW 매트릭스 기록 (행=phase, 열=element). 미측정 phase는 0으로 남음.
                result[idx][element] = pk_pwr_dbm

                if pk_pwr_dbm > best_pwr:
                    best_pwr = pk_pwr_dbm
                    best_idx = idx
                logger.info(f"[El {element:02d}] phase {idx:02d} -> {pk_pwr_dbm:.2f} dBm")
            return best_idx, best_pwr

        # 0) 모든 엘리먼트 ON (phase=0, gain=7) : 합성 전력 기반으로 탐색
        logger.info("Turn ON all elements with phase=0, gain=7 (reference include)")
        for el in range(32):
            element_on_withPhase(beam, pol, 0, 7, el)
        time.sleep(0.2)

        # 위상 정렬 결과 테이블
        best_phase_idx = [0]*32
        best_power_dbm = [float("-inf")]*32

        # 1) 위상 정렬 (참조 17 스킵)
        for element in range(32):
            if element == 17:
                logger.info("Reference element(17) skip (ON state)")
                continue

            logger.info(f"[Element {element}] Coarse sweep(45°) start")
            coarse_indices = list(range(0, 64, COARSE_STEP))  # 0,8,16,...,56
            coarse_best_idx, coarse_best_pwr = sweep_indices_and_measure(element, coarse_indices)
            logger.info(f"[Element {element}] Coarse max at idx={coarse_best_idx}, pwr={coarse_best_pwr:.2f} dBm")

            # Fine 윈도우 (원형 래핑)
            fine_indices = wrap_range(coarse_best_idx, FINE_HALF_WINDOW, 64)
            logger.info(f"[Element {element}] Fine sweep start - center={coarse_best_idx}, size={len(fine_indices)}")
            fine_best_idx, fine_best_pwr = sweep_indices_and_measure(element, fine_indices)
            logger.info(f"[Element {element}] Fine max at idx={fine_best_idx}, pwr={fine_best_pwr:.2f} dBm")

            # 보정 적용: 최대 전력 위상값으로 고정 (X = -Δ0 와 동치)
            best_phase_idx[element] = fine_best_idx
            best_power_dbm[element] = fine_best_pwr
            element_on_withPhase(beam, pol, fine_best_idx, 7, element)
            logger.info(f"[Element {element}] APPLY: phase <- {fine_best_idx} (align complete)")

        # 2) 요약 출력
        for i, (idx, pwr) in enumerate(zip(best_phase_idx, best_power_dbm)):
            if math.isfinite(pwr):
                print(f"#{i:02d}: phase_idx={idx}, power={pwr:.2f} dBm")
            else:
                print(f"#{i:02d}: phase_idx={idx}, power=N/A")

        # 3) RAW CSV 저장 (phase sweep)
        CSV_PATH = r"C:\Users\Dosan\Desktop\Sejin\00. Sejin Archive\gain_index_sweep_log_maxcal.csv"
        save_matrix_csv(result, CSV_PATH, include_phase_col=True)

        # ------------------------------- Gain Alignment -------------------------------
        logger.info("==== Gain Alignment start (Ref=17 Matching based on single power) ====")

        # 3-1) 참조(17) 최종 phase 결정: 위 단계에서 17을 건드리지 않았으므로 0(또는 기존) 사용
        #      만약 PPT/운용상 참조도 정렬해야 한다면, 동일한 MAX 과정을 17에도 적용해서 best_phase_idx[17]을 구해도 됨.
        if best_phase_idx[17] == 0:
            ref_phase_idx = 0
        else:
            ref_phase_idx = best_phase_idx[17]

        # 3-2) 참조 단독 파워 측정 (gain=7 고정)
        gs.config_TX_FE_all_off()
        element_on_withPhase(beam, pol, ref_phase_idx, 7, 17)       # 모든 element phase는 선택된 결과 phase, gain 7로 고정
        time.sleep(SETTLE_TIME_S)
        ref_pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
        logger.info(f"[REF el17] phase={ref_phase_idx}, gain=7 -> {ref_pwr_dbm:.2f} dBm")

        # 3-3) 각 엘리먼트 gain 4..10 스윕 → 참조 파워와 가장 근접한 gain 선택
        GAIN_SWEEP_RANGE = range(4, 11)  # 4~10 inclusive
        matched_gain = [None]*32
        matched_pwr  = [None]*32
        gain_err_db  = [None]*32

        for element in range(32):
            if element == 17:
                matched_gain[element] = 7
                matched_pwr[element]  = ref_pwr_dbm
                gain_err_db[element]  = 0.0
                logger.info("Gain Alignment: Reference 17 is set as the standard")
                continue

            el_phase = best_phase_idx[element] if best_phase_idx[element] != 0 else 0
            best_g, best_p, min_err = None, None, float("inf")

            logger.info(f"[El {element:02d}] Gain sweep start (phase={el_phase}, target={ref_pwr_dbm:.2f} dBm)")
            for g in GAIN_SWEEP_RANGE:
                gs.config_TX_FE_all_off()
                element_on_withPhase(beam, pol, el_phase, g, element)
                time.sleep(SETTLE_TIME_S)
                pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)

                err = abs(pwr_dbm - ref_pwr_dbm)
                logger.info(f"[El {element:02d}] gain={g:2d} -> {pwr_dbm:.2f} dBm (Δ={pwr_dbm - ref_pwr_dbm:+.2f} dB)")
                if err < min_err:
                    min_err = err
                    best_g  = g
                    best_p  = pwr_dbm

            # 최적 gain 적용 (단독)
            matched_gain[element] = best_g
            matched_pwr[element]  = best_p
            gain_err_db[element]  = (best_p - ref_pwr_dbm) if best_p is not None else None

            gs.config_TX_FE_all_off()
            element_on_withPhase(beam, pol, el_phase, best_g, element)
            logger.info(f"[El {element:02d}] BEST gain={best_g}, phase={el_phase} -> {best_p:.2f} dBm (Δ={best_p - ref_pwr_dbm:+.2f} dB)")

        # 3-4) 요약 출력
        for i, (g, p, d) in enumerate(zip(matched_gain, matched_pwr, gain_err_db)):
            if p is None or not math.isfinite(p):
                print(f"#{i:02d}: gain={g}, power=N/A,  Δ=N/A")
            else:
                print(f"#{i:02d}: gain={g}, power={p:.2f} dBm, Δ={d:+.2f} dB")

        # 3-5) 최종 적용: 전 요소 “최종 phase/gain”으로 ON (합성 빔 확인용)
        gs.config_TX_FE_all_off()
        for el in range(32):
            g_final = matched_gain[el] if matched_gain[el] is not None else 7
            p_final = best_phase_idx[el] if best_phase_idx[el] is not None else 0
            element_on_withPhase(beam, pol, p_final, g_final, el)
        time.sleep(0.2)

        # 3-6) 최종 Max EIRP(프록시) 측정
        final_eirp_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
        logger.info(f"[FINAL] Max EIRP proxy (TxP Avg Mean Power): {final_eirp_dbm:.2f} dBm")

        # 4) 요약 CSV 저장 (phase/gain index 테이블)
        import os
        open(os.path.splitext(CSV_PATH)[0] + "_settings_maxcal.csv","w").write(
            "element,phase_idx,gain_idx\n" + "\n".join(f"{i},{best_phase_idx[i]},{matched_gain[i]}" for i in range(32))
        )

        dt_ns = time.perf_counter_ns() - t0                                                              ################################측정 끝
        print(f"elapsed: {dt_ns/1e6:.3f} ms")


        

finally:
    # >>> GPT (NI-REF): 레퍼런스 방식으로 장비 정리
    try:
        inst.rfsg.set_pwr(pwr=-50)
        inst.rfsg.mod_off()
    except:
        pass
    try:
        inst.rfsg.close()
    except:
        pass
    try:
        inst.rfmx.close()
    except:
        pass
    inst = 0