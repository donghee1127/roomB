'''Imports'''
import os
from mvboard.GumStick import GumStick
from time import sleep
from enum import Enum
import time, math
import logging
from types import SimpleNamespace
from typing import List
import csv, datetime
import pandas as pd

logger = logging.getLogger()
logger.setLevel(logging.INFO)

'''User inputs'''
Center_f = {"Low": 27.0e9, "Mid": 28.0e9, "High": 29.0e9}

##############################################################################################
################################ Parameter Setting ###########################################
##############################################################################################

gumstick_port = 0  # 1 for H1 Breakout board, 0 for H3 Breakoutboard
panel = 'donor'
txrx = 'tx'
beam = 'b1'
rf_freq = Center_f["Low"]  # Select carrier
beam_index = 0
beam_mode = '30x15'  # beam_mode is '30x15' , '30x30' , '60x15'
Tri_band = 1  # Single_band GS = 0
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

print("Donor or Relay:", panel)
print("T/Rx Mode:", txrx)
print("band:", band)
print("Beam:", beam)
print("Center Frequency:", rf_freq)
print("Initial Beam Index:", beam_index)
print("Initial Beam Mode:", beam_mode)
print("Triband(1), Single band(0):", Tri_band)

def init_RFIC():
    # Init PMU
    gs.init()
    # gs.digital_test()

    # Init vcxo pll
    gs.init_vcxo_pll()
    sleep(1)

    # Set rf
    print('** Intializing RFICs **')
    for fe_num, fe in enumerate(gs.fe):
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
    gs.init_pll(pll='3554')
    bg_code = gs.pll[0].model.run_BG_cal_rtl(dbg_prt=True)
    print(f'IF_PLL : BG_code - {bg_code}')
    print(gs.fe[0].model.__class__)
    print(gs.mix[0].model.__class__)

def set_txrx(txrx='tx', beam='b1', band='mid'):
    if_port_val = 'a' if txrx == 'rx' else 'b'
    lo_mult = 1.5 if rf_freq < 32e9 else 2
    gs.set_pll_freq(pll="3554", ref_in_MHz=ref_in_MHz, freq_out_MHz=pll_freq_MHz,
                    mult_val=lo_mult, vco_freq_cutoff=4990)
    sleep(0.2)
    # gs.pll_logen_cal(pll="3554", tssi_out_lim=1200) #sypark
    gs.pll_logen_cal(pll="3554", tssi_out_lim=900, prnt=True)

    gs.set_target(gs.mix[0])
    mv2853 = gs.mix[0].model
    if txrx == "tx":
        mv2853.initialize_TX(beam=beam, if_sw=if_port_val, band=band, prnt=True)
    else:
        mv2853.initialize_RX(beam=beam, if_sw=if_port_val, band=band, prnt=True)
    mv2853.set_band(mode=txrx, rf_band=band, if_freq=if_freq, logen=lo_freq,
                    beam='both', lo_cal_lim=550, freq_cutoff=18.5e9)
    mv2853.set_txif_attn(attn=12)
    mv2853.set_PA_bias(13, 13, 13, 2, 9, beam='both')

    for fe in gs.fe:
        gs.set_target(fe)
        if txrx == "tx":
            fe.model.initialize_tx(path="all_off", prnt=True)
        else:
            fe.model.initialize_rx(path="all_off", prnt=True)
        fe.model.set_band_TX(band=band) if txrx == "tx" else fe.model.set_band_RX(band=band)
        fe.model.dreg.hv_swap.val = 0x09
        fe.model.set_PA_bias(13, 13, 13, 1, 9)

def flash_load_cal_section(start_addr, end_addr):
    if (start_addr % 256 != 0) or (end_addr % 256 != 0):
        raise Exception("start/end address has to be start/end of a page, cannot load section from middle of a page..")
    else:
        start_page = start_addr // 256
        no_of_pages = (end_addr - start_addr) // 256
    for page_no in list(range(start_page, start_page + no_of_pages)):
        gs.run_load_beam_book_from_flash(page_no, 85)

def convert_to_int(list_data):
    val = 0
    for i in range(len(list_data)):
        val += (list_data[i] << (8 * (len(list_data) - 1 - i)))
        print(list_data[i] << (8 * (len(list_data) - 1 - i)))
        print(val)
    return val

def flash_load_cal_data(panel='donor', band='mid', loc=[0, 1, 3]):
    gs.comms.reset_mirror()
    print("-----------------------------------------------------")
    print("Donor or Relay\t\t\t:\t", panel)
    print("-----------------------------------------------------")

    '''loc format -> phasecal, beambook, extended gain lut, baseband gain lut'''
    band_dict = {'low': 0xc00, 'mid': 0xb00, 'high': 0xa00}
    list_data = gs.flash_ctrl.read_page(band_dict[band])
    cal_st = convert_to_int(list_data[16:20])
    cal_end = convert_to_int(list_data[20:24])
    bbk_st = convert_to_int(list_data[28:32])
    bbk_end = convert_to_int(list_data[32:36])
    ext_st = convert_to_int(list_data[40:44])
    ext_end = convert_to_int(list_data[44:48])
    bbiq_st = convert_to_int(list_data[52:56])
    bbiq_end = convert_to_int(list_data[56:60])
    cal_array = {'start_addr_ary': [cal_st, bbk_st, ext_st, bbiq_st],
                 'end_addr_ary': [cal_end, bbk_end, ext_end, bbiq_end]}

    for i in loc:
        start_addr = cal_array["start_addr_ary"][i]
        end_addr = cal_array["end_addr_ary"][i] + 1
        flash_load_cal_section(start_addr, end_addr)
    print(cal_array['start_addr_ary'])
    print(cal_array['end_addr_ary'])
    gs.comms.reset_mirror()

def atten(n):
    if txrx == 'tx':
        # TX Gain (> 48dB)_Mixer 8/ FE 13
        tx_gain = {15: [18, 17], 14: [18, 17], 13: [18, 16], 12: [18, 15], 11: [18, 14], 10: [18, 13], 9: [18, 12], 8: [18, 11], 7: [18, 10], 6: [18, 9],
                   5: [18, 8], 4: [17, 8], 3: [16, 8], 2: [15, 8], 1: [14, 8], 0: [13, 8], -1: [13, 7], -2: [13, 6], -3: [13, 5], -4: [12, 5],
                   -5: [11, 5], -6: [10, 5], -7: [9, 5], -8: [8, 5], -9: [7, 5], -10: [7, 4], -11: [7, 3], -12: [6, 3], -13: [5, 3], -14: [4, 3],
                   -15: [3, 3], -16: [3, 2], -17: [2, 2], -18: [2, 1], -19: [1, 1], -20: [1, 0]}
        gs.set_gain_index_MIX_TX_RAM(index=tx_gain[n][1], b1=1, b2=1)
        gs.set_gain_index_FE_TX_RAM(index=tx_gain[n][0], b1=1, b2=1)
    else:
        # RX Gain (> 42dB)_Mixer 6/ FE 15
        rx_gain = {15: [15, 21], 14: [15, 20], 13: [15, 19], 12: [15, 18], 11: [15, 17], 10: [15, 16], 9: [15, 15], 8: [15, 14], 7: [15, 13], 6: [15, 12],
                   5: [15, 11], 4: [15, 10], 3: [15, 9], 2: [15, 8], 1: [15, 7], 0: [15, 6], -1: [15, 5], -2: [15, 4], -3: [14, 6], -4: [14, 5],
                   -5: [14, 4], -6: [13, 6], -7: [13, 5], -8: [13, 4], -9: [12, 6], -10: [12, 5], -11: [12, 4], -12: [11, 6], -13: [11, 5], -14: [11, 4],
                   -15: [10, 6], -16: [10, 5], -17: [10, 4], -18: [9, 6], -19: [9, 5], -20: [9, 4], -21: [8, 6], -22: [8, 5], -23: [8, 4], -24: [7, 6], -25: [7, 5],
                   -26: [7, 4], -27: [6, 6], -28: [6, 5], -29: [6, 4], -30: [5, 6]}
        gs.set_gain_index_MIX_RX_RAM(index=rx_gain[n][1], b1=1, b2=1)
        gs.set_gain_index_FE_RX_RAM(index=rx_gain[n][0])

def set_bm_idx(mode='tx', beam='b1', pol='h', idx=0):
    getattr(gs, 'set_beambook_index_%s' % mode)(gs.fe, beam=beam, pol=pol, index=idx)

def set_beam_mode(beam_mode='30x15', beam='b1', pol='h', txrx='tx'):
    txrx == "tx" if gs.enable_beambooks_tx() else gs.enable_beambooks_rx()
    if beam_mode == '30x15':
        set_bm_idx(txrx, beam, pol, 0)
        for ii in range(8):
            chip = gs.fe[ii].model
            chip.reg.bias_tc1_mag.val = 129
            chip.reg.bias_tc1_slope.val = 58
        for fe in gs.fe:
            fe.model.set_PA_bias(13, 13, 13, 1, 9)
        gs.config_TX_FE_all_off() if txrx == 'tx' else gs.config_RX_FE_all_off()
        gs.enable_selected_pol(chips=[gs.fe[0], gs.fe[1], gs.fe[2], gs.fe[3],
                                      gs.fe[4], gs.fe[5], gs.fe[6], gs.fe[7]],
                               beam=beam, pol=pol, txrx=txrx)
    elif beam_mode == '60x15':
        set_bm_idx(txrx, beam, pol, 0)
        for ii in range(8):
            chip = gs.fe[ii].model
            chip.reg.bias_tc1_mag.val = 129
            chip.reg.bias_tc1_slope.val = 58
        for fe in gs.fe:
            fe.model.set_PA_bias(13, 13, 13, 1, 9)
        gs.config_TX_FE_all_off() if txrx == 'tx' else gs.config_RX_FE_all_off()
        gs.enable_selected_pol(chips=[gs.fe[0], gs.fe[1], gs.fe[2], gs.fe[3]],
                               beam=beam, pol=pol, txrx=txrx)
    elif beam_mode == '30x30':
        set_bm_idx(txrx, beam, pol, 0)
        for ii in range(8):
            chip = gs.fe[ii].model
            chip.reg.bias_tc1_mag.val = 129
            chip.reg.bias_tc1_slope.val = 58
        for fe in gs.fe:
            fe.model.set_PA_bias(13, 13, 13, 1, 9)
        gs.config_TX_FE_all_off() if txrx == 'tx' else gs.config_RX_FE_all_off()
        gs.enable_selected_pol(chips=[gs.fe[0], gs.fe[1], gs.fe[4], gs.fe[5]],
                               beam=beam, pol=pol, txrx=txrx)
    else:
        print('Error, Please resetting beam mode')

def set_beam_index(beam_index=0):
    gs.enable_beambooks_tx() if txrx == 'tx' else gs.enable_beambooks_rx()
    if txrx == 'tx':
        gs.set_beambook_index_tx(gs.fe, beam, pol, beam_index)
    else:
        gs.set_beambook_index_rx(gs.fe, beam, pol, beam_index)

def config_FE_all_off(txrx='tx'):
    if txrx == 'rx':
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
    mv2853.dreg.agc_mode.val = mix_en

    for fe in gs.fe:
        gs.set_target(fe)
        fe.model.dreg.agc_ctrl3.val = fe_en

def read_init_temp_after_boot():
    # Enable PMU
    gs.init()

    for fe_num, fe in enumerate(gs.fe):
        gs.comms.reset_mirror()
        fe.model.load_from_dataset('init')
        bg_code = fe.model.run_BG_cal_rtl(prnt=True)

    gs.read_avgtemp()

    # Disable PMU
    gs.comms.write_reg(10, 0x0)

def get_chip_fe(beam='b1', pol='h', ant_idx=0):
    fe_list = [3, 4, 1, 2, 2, 1, 4, 3]
    chip_num = 4 + (ant_idx // 8) - 2 * (ant_idx & 2)
    fe = fe_list[ant_idx % 8]
    beam_swap = True if chip_num < 4 else False
    if beam == 'b1':
        beam_comp = 'b2'
    else:
        beam_comp = 'b1'
    log_path = f'{beam}_{fe}{pol}'
    phy_path = f'{beam_comp}_{fe}{pol}' if beam_swap else log_path
    return chip_num, fe, log_path, phy_path

def Element_On(beam='b1', pol='h', el=0):
    chip_num, fe, log_path, phy_path = get_chip_fe(beam=beam, pol=pol, ant_idx=el)
    gs.config_FE_TX(chips=[gs.fe[chip_num]], fe=log_path)

def Set_PS_Index_at_freq(path='b1_1h', phase_idx=0, g_default=7, fe_num=0):
    gs.fe[fe_num].model.set_PS_Index_at_freq(selection=path, index=phase_idx, N=64,
                                             freq=rf_freq, g_index=g_default, txrx=txrx, return_IQ=False)

def element_on_withPhase(beam='b1', pol='h', phase=0, g_default=10, el=0):
    chip_num, fe, log_path, phy_path = get_chip_fe(beam=beam, pol=pol, ant_idx=el)
    gs.config_FE_TX(chips=[gs.fe[chip_num]], fe=log_path)
    Set_PS_Index_at_freq(path=phy_path, phase_idx=phase, g_default=g_default, fe_num=chip_num)
    print("el: {},\tpath: {},\tswap_path: {},\tps_idx: {},\tg_idx: {}".format(el, log_path, phy_path, phase, g_default))

def apply_phase_gain(beam='b1', pol='h', csv_path=""):
    """
    CSV columns required: element, phase_idx, gain_idx
    Defaults: beam='b1', pol='h', skip element #17
    """
    beam, pol = beam, pol

    df = pd.read_csv(csv_path)[['element', 'phase_idx', 'gain_idx']].sort_values('element')
    gs.config_TX_FE_all_off()  # Tx fe off
    for _, r in df.iterrows():
        e = int(r['element'])
        phase_idx = int(r['phase_idx']) & 0x3F   # 0..63
        gain_idx  = int(r['gain_idx'])          # (필요시 범위 클램프 추가)
        element_on_withPhase(beam, pol, phase_idx, gain_idx, e)
        print(f"Set E{e:02d}: phase={phase_idx}, gain={gain_idx}")

# 사용 예:
# apply_phase_gain(r"C:\path\to\gain_index_sweep_log_original_settings.csv")


###############################################   GS Initial  ######################################################
gs = GumStick(n=gumstick_port)  # G/S Open
init_RFIC()  # Init PMU / Init vcxo pll / Set rf / Set mixer / Set pll
if panel == 'donor':
    gs.digital_test()  # use only Donor type
set_txrx(txrx=txrx, beam=beam, band=band)  # Set txrx
# flash_load_cal_data(panel=panel, band=band, loc = [0,1,3]) # Load beambook -> beambook 로드 안하면 결과 왜 이상한지?
gs.config_TX_FE_all_off()  # Tx fe off
gs.config_RX_FE_all_off()  # Rx fe off
gs.pll_recal('3554')  # PLL Recal
time.sleep(1)
gs.read_avgtemp()  # Read AvgTemp
gs.config_TX_FE_all_off()  # Tx fe off

#apply_phase_gain(beam, pol, r"C:\Users\Dosan\Desktop\Sejin\00. Sejin Archive\gain_index_sweep_log_original_settings.csv")
#gain_index_sweep_log_original_settings
#gain_index_sweep_log_rev_settings_rev
#gain_index_sweep_log_irev_settings_irev
#gain_index_sweep_log_maxcal_settings_maxcal
#all_zero_default_gain

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
port_map = {'tx': {'b1': {'rfsg': 'if0', 'rfsa': 'rf0/port0', 'if_sw': 'b', 'ant_port': 'port1'},
                   'b2': {'rfsg': 'if1', 'rfsa': 'rf0/port1', 'if_sw': 'b', 'ant_port': 'port2'}},
            'rx': {'b1': {'rfsg': 'rf0/port0', 'rfsa': 'if0', 'if_sw': 'a', 'ant_port': 'port1'},
                   'b2': {'rfsg': 'rf0/port1', 'rfsa': 'if1', 'if_sw': 'a', 'ant_port': 'port2'}}}

demod_state = {'tx': {'rfsg': {'64qam': {'cw': r"C:\repos_git\waveforms\SG_CotinousWaveform.tdms",
                                         'mod_1cc': r"C:\repos_git\waveforms\SG_NR_FR2_Uplink_BW_100MHz_scs_120kHz_QAM64_ATE.tdms"}},
                      'rfsa': {'64qam': {'cw': r"C:\repos_git\waveforms\SA_ContinousWaveform.tdms",
                                         'mod_1cc': r"C:\repos_git\waveforms\SA_NR_FR2_Uplink_BW_100MHz_scs_120kHz_QAM64_ATE.tdms"}}},
              'rx': {'rfsg': {'64qam': {'cw': r"C:\repos_git\waveforms\SG_CotinousWaveform.tdms",
                                         'mod_1cc': r"C:\repos_git\waveforms\SG_NR_FR2_Uplink_BW_100MHz_scs_120kHz_QAM64_ATE.tdms"}},
                     'rfsa': {'64qam': {'cw': r"C:\repos_git\waveforms\SA_ContinousWaveform.tdms",
                                         'mod_1cc': r"C:\repos_git\waveforms\SA_NR_FR2_Uplink_BW_100MHz_scs_120kHz_QAM64_ATE.tdms"}}}}

class Mode(Enum):
    nr_single = 0
    nr_multi = 1
    spec_an = 2
    txp = 3

class Test(Enum):
    evm_chp = 'evm_chp'
    aclr = 'aclr'
    spectrum = 'spectrum'
    txp = 'txp'
    temp_sweep = 'temp_sweep'

mode = Mode.spec_an
meas = Test.spectrum

def config_generator(txrx='tx', beam='b1', qam='64qam', cc=1, freq=5e9, pwr=-20, ext_atten=0, lo_offset="auto"):
    port_map_filtered = port_map[txrx][beam]
    logging.info(" Tester.config_generator: SG Port :{}, cc :{}, Freq :{} Hz, Pwr :{} dBm, Atten :{} dB".format(
        port_map_filtered['rfsg'], cc, freq, pwr, ext_atten))

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
    logging.info(" Tester.config_analyzer: SA Port :{}, cc :{}, Freq :{} Hz, Ref :{} dBm, Atten :{} dB".format(
        port_map_filtered['rfsa'], cc, freq, ref_level, ext_atten))

    if (mode == Mode.nr_single) or (mode == Mode.nr_multi):
        sa_path = demod_state[txrx]['rfsa'][qam]['mod_{}cc'.format(cc)]
        inst.rfmx.set_mode(mode="nr")
        inst.rfmx.load_state(path=sa_path)
    elif (mode == Mode.spec_an) or (mode == Mode.txp):
        sa_path = demod_state[txrx]['rfsa'][qam]['cw']
        inst.rfmx.set_mode(mode="spec_an")
        inst.rfmx.load_state(path=sa_path)
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

# ===============================  Calibration Common Config & Helpers  ===============================
# (공통) 교정 환경 설정: 모든 분기에서 동일 변수 사용
CAL = SimpleNamespace(
    PHASE_BITS=6,
    PHASE_STEPS=64,
    PHASE_STEP_RAD=2.0 * math.pi / 64.0,  # 5.625°
    SETTLE_TIME_S=0.10,
    EXTRA_WAIT_AFTER_SG_S=3.0,
    SG_FIXED_POWER_DBM=-20.0,

    AVG_N=1,
    USE_ACCUM=True,

    FINE_HALF_WIN=16,

    IREV_ATTEN_DB=2.0,
    IREV_MIN_PROBE_HALFWIN=8,
    IREV_VERIFY_AFTER_APPLY=False,

    MAX_COARSE_STEP=8,
    MAX_FINE_HALF_WIN=4,

    # ==== REV (paper) parameters ====
    REV_POINTS=4,                # 기본 4점. 균일 분할 K점 지원
    REV_VERIFY_PASSES=1,         # 검증 패스 반복 횟수
    REV_APPLY_MODE="batch",      # "batch" | "sequential" (초기 pass)
    CSV_DIR=r"C:\Users\Dosan\Desktop\Sejin\00. Sejin Archive"
)

def wrap_idx(i, m=CAL.PHASE_STEPS):
    return (i + m) % m

def ang_wrap_rad(a):
    while a >= math.pi:
        a -= 2*math.pi
    while a < -math.pi:
        a += 2*math.pi
    return a

def dbm_to_mw(p_dbm):
    return 10.0 ** (p_dbm / 10.0)

def mw_to_v(p_mw):
    return math.sqrt(max(p_mw * 1e-3, 0.0))

def measure_power_avg():
    """(공통) AVG_N번 측정해 선형 평균(mW) → dBm"""
    if CAL.AVG_N <= 1:
        return meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)[0]
    ps = []
    for _ in range(CAL.AVG_N):
        p_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
        ps.append(dbm_to_mw(p_dbm))
    p_avg_mw = sum(ps) / max(len(ps), 1)
    return 10.0 * math.log10(max(p_avg_mw, 1e-15))

def fine_indices(center, half_win):
    return [wrap_idx(center + k) for k in range(-half_win, half_win + 1)]

def save_cal_matrix(matrix: List[List[float]], name: str, include_phase_col: bool = True):
    path = os.path.join(CAL.CSV_DIR, name)
    save_matrix_csv(matrix, path, include_phase_col=include_phase_col)
    return path

# ===============================  Phase Cal Select  =================================
phase_cal_method = 'rev'  # 'original' 'rev' 'maxcal'

# ===============================  Phase Cal  =================================
# 1) 참조 엘리먼트 고정 설정 (gain 7, phase 0)
element_on_withPhase(beam, pol, 0, 7, 17)

# 2) NI 장비 구성 (레퍼런스 함수 사용)
config_generator(txrx=txrx, beam=beam, qam='64qam', cc=1, freq=if_freq, pwr=CAL.SG_FIXED_POWER_DBM, ext_atten=0)
time.sleep(CAL.EXTRA_WAIT_AFTER_SG_S)
config_analyzer(txrx=txrx, beam=beam, qam='64qam', cc=1, freq=rf_freq, ref_level=0, ext_atten=0)
meas_settings(meas=Test.txp, txrx=txrx, cc=1)

# 3) 결과 매트릭스 준비 (행=phase, 열=element; 17은 0으로 유지)
result = init_result_matrix(phases=CAL.PHASE_STEPS, elements=32)

try:
    # ===================== 기존 Doosan Phase Cal (Original) ===================================================================================================================
    if phase_cal_method == 'original':  # phase sweep cal
        t0 = time.perf_counter_ns()
        best_phase_idx = [0]*32
        best_power_dbm = [float("-inf")]*32

        for element in range(32):
            if element == 17:
                logger.info("Reference Element(17) skip and fill all 0")
                continue

            gs.config_TX_FE_all_off()                 # sweep 시작 전 모든 element turn off
            element_on_withPhase(beam, pol, 0, 7, 17) # Reference element 17번만 ON

            logger.info(f"[Element {element}] ON, Phase sweep start")
            max_pwr = float("-inf"); max_idx = 0
            for phase in range(CAL.PHASE_STEPS):
                element_on_withPhase(beam, pol, phase, 7, element)
                time.sleep(CAL.SETTLE_TIME_S)
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
                print(f"#{i:02d}: {idx}(index), N/A(dBm)")

        # ---- Gain sweep cal ----
        GAIN_SWEEP_RANGE = range(4, 11)  # 4~10 inclusive
        matched_gain = [None]*32
        matched_pwr = [None]*32
        gain_err_db = [None]*32  # (elem_power - ref_power)

        gs.config_TX_FE_all_off()
        ref_phase = best_phase_idx[17] if len(best_phase_idx) > 17 else 0
        element_on_withPhase(beam, pol, ref_phase, 7, 17)
        time.sleep(CAL.SETTLE_TIME_S)
        ref_pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
        logger.info(f"[REF el17] phase={ref_phase}, gain=7 -> {ref_pwr_dbm:.2f} dBm")

        gs.config_TX_FE_all_off()

        for element in range(32):
            if element == 17:
                logger.info("Skip element 17 (reference)")
                matched_gain[element] = 7
                matched_pwr[element] = ref_pwr_dbm
                gain_err_db[element] = 0.0
                continue

            el_phase = best_phase_idx[element] if element < len(best_phase_idx) else 0
            best_g = None; best_pwr = None; min_err = float("inf")

            logger.info(f"[El {element:02d}] Gain sweep start (phase={el_phase}, target={ref_pwr_dbm:.2f} dBm)")
            for g in GAIN_SWEEP_RANGE:
                gs.config_TX_FE_all_off()
                element_on_withPhase(beam, pol, el_phase, g, element)
                time.sleep(CAL.SETTLE_TIME_S)
                pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)

                err = abs(pwr_dbm - ref_pwr_dbm)
                logger.info(f"[El {element:02d}] gain={g:2d} -> {pwr_dbm:.2f} dBm (Δ={pwr_dbm - ref_pwr_dbm:+.2f} dB)")
                if err < min_err:
                    min_err = err
                    best_g = g
                    best_pwr = pwr_dbm

            matched_gain[element] = best_g
            matched_pwr[element] = best_pwr
            gain_err_db[element] = (best_pwr - ref_pwr_dbm) if best_pwr is not None else None

            gs.config_TX_FE_all_off()
            element_on_withPhase(beam, pol, el_phase, best_g, element)
            logger.info(f"[El {element:02d}] BEST gain={best_g}, phase={el_phase} -> {best_pwr:.2f} dBm (Δ={best_pwr - ref_pwr_dbm:+.2f} dB)")

        dt_ns = time.perf_counter_ns() - t0
        for i, (g, p, d) in enumerate(zip(matched_gain, matched_pwr, gain_err_db)):
            if p is None or not math.isfinite(p):
                print(f"#{i:02d}: gain={g}, power=N/A,  Δ=N/A")
            else:
                print(f"#{i:02d}: gain={g}, power={p:.2f} dBm, Δ={d:+.2f} dB")
        print(f"elapsed: {dt_ns/1e6:.3f} ms")

        logger.info("[APPLY] Apply final original phase (per-element) and final gain to all elements")
        gs.config_TX_FE_all_off()
        for n in range(32):
            phase_final = best_phase_idx[n] if best_phase_idx[n] is not None else 0
            gain_final = matched_gain[n] if matched_gain[n] is not None else 7
            element_on_withPhase(beam, pol, phase_final, gain_final, n)

        time.sleep(0.2)
        final_pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
        logger.info(f"[FINAL] TxP Avg Mean Power (proxy EIRP) = {final_pwr_dbm:.2f} dBm")

        CSV_PATH = save_cal_matrix(result, "gain_index_sweep_log_original.csv", include_phase_col=True)
        open(os.path.splitext(CSV_PATH)[0] + "_settings.csv", "w").write(
            "element,phase_idx,gain_idx\n" + "\n".join(f"{i},{best_phase_idx[i]},{matched_gain[i]}" for i in range(32))
        )


    # =====================  1-bit REV (paper Γ, Δ0, outside only)  ==================================================================================================================
    elif phase_cal_method == 'rev':
        """
        논문식(Γ, Δ0) outside-only + 1-bit pre-flip + K점(기본 4점, 균일 샘플) + dBm->mW
        + 검증 패스(REV_VERIFY_PASSES) + 최종 전체 파워 측정 + CSV 저장(rev 접미사)
        Gain 캘은 original 방식 그대로 수행.
        """
        t0 = time.perf_counter_ns()

        PH = CAL.PHASE_STEPS
        STEP_RAD = CAL.PHASE_STEP_RAD
        DEFAULT_GAIN_IDX = 7
        K = int(getattr(CAL, "REV_POINTS", 4))
        VERIFY_PASSES = int(getattr(CAL, "REV_VERIFY_PASSES", 1))
        APPLY_MODE = getattr(CAL, "REV_APPLY_MODE", "batch")  # "batch" | "sequential"

        def idx2rad(i): return (i % PH) * STEP_RAD
        def rad2idx(rad): return int(round((rad % (2*math.pi)) / STEP_RAD)) % PH

        # --- K점 균일 분할 인덱스 생성 (시작점 start_idx 기준) ---
        def k_indices(start_idx, K):
            return [wrap_idx(start_idx + round(k * PH / K)) for k in range(K)]

        # --- K점(선형 파워)으로 C,U,V -> Δ0, R, C ---
        def fit_C_R_Delta0(indices, elem):
            # C = mean(P), U = (2/K) Σ P cosθ, V = (2/K) Σ P sinθ  (P는 mW)
            Kloc = len(indices)
            sumP = 0.0; sumPc = 0.0; sumPs = 0.0
            samples_dbm = []

            for idx in indices:
                element_on_withPhase(beam, pol, idx, DEFAULT_GAIN_IDX, elem)
                time.sleep(CAL.SETTLE_TIME_S)
                p_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
                p_mw = dbm_to_mw(p_dbm)
                th = idx2rad(idx)
                sumP  += p_mw
                sumPc += p_mw * math.cos(th)
                sumPs += p_mw * math.sin(th)
                samples_dbm.append((idx, p_dbm))

            C = sumP / max(Kloc, 1)
            U = (2.0 / Kloc) * sumPc
            V = (2.0 / Kloc) * sumPs
            R = math.hypot(U, V)
            # cos(Δ0+φ) = cosΔ0 cosφ - sinΔ0 sinφ  =>  U = R cosΔ0 ,  V = - R sinΔ0
            Delta0 = math.atan2(-V, U)

            # 로그
            logger.info(f"[REV-FIT] el={elem:02d} K={Kloc} " +
                        " ".join([f"(idx={i:02d}, {p:.2f} dBm)" for (i,p) in samples_dbm]))
            logger.info(f"[REV-FIT][RES] el={elem:02d} C={C:.6g} mW, R={R:.6g} mW, Δ0={Delta0*180/math.pi:.2f}°")
            return C, R, Delta0

        # --- Δ0, C, R -> Γ(전계), X(논문 outside 식) ---
        def compute_gamma_and_X(C, R, Delta0):
            Pmax = C + R
            Pmin = max(C - R, 1e-15)
            Emax = math.sqrt(Pmax)
            Emin = math.sqrt(Pmin)
            Gamma = (Emax + Emin) / max(Emax - Emin, 1e-15)
            X = math.atan2(math.sin(Delta0), math.cos(Delta0) + Gamma)
            return Gamma, X

        # ---------------- A) 1-bit Pre-flip (0/180 중 큰 쪽 선택: 저장만) ----------------
        logger.info("[REV] Phase-A: 1-bit Pre-flip (record only)")

        preflip_start = [0]*32
        for el in range(32):
            # idx 0 측정
            element_on_withPhase(beam, pol, 0, DEFAULT_GAIN_IDX, el)
            time.sleep(CAL.SETTLE_TIME_S)
            p0_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
            # idx 31(≈180°) 측정
            element_on_withPhase(beam, pol, 31, DEFAULT_GAIN_IDX, el)
            time.sleep(CAL.SETTLE_TIME_S)
            p180_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
            # 원상복구는 굳이 필요 없음(어차피 저장만), 시작점 기록
            s = 0 if p0_dbm >= p180_dbm else 31
            preflip_start[el] = s
            logger.info(f"[REV-PREFLIP] el={el:02d} choose start={s} (P0={p0_dbm:.2f} dBm, P180={p180_dbm:.2f} dBm)")

        # ---------------- B) 1st pass: K점 계측 -> Δ0, Γ -> X -> index 계산 ----------------
        logger.info("[REV] Phase-B: K-point measurement & compute X (paper formula, outside only)")
        rev_phase_idx = [0]*32
        rev_X_deg = [0.0]*32
        rev_Delta0_deg = [0.0]*32
        rev_Gamma = [float("nan")]*32

        def pass_compute_and_maybe_apply(current_idx_arr, apply_now):
            """현재 적용 상태/시작점을 기준으로 각 el에 대해 X 계산 (그리고 apply_now면 즉시 적용)"""
            for el in range(32):
                start_idx = current_idx_arr[el]
                idxs = k_indices(start_idx, K)

                C, R, Delta0 = fit_C_R_Delta0(idxs, el)     # C[mW], R[mW], Δ0[rad]
                Gamma, X = compute_gamma_and_X(C, R, Delta0)

                # 논문식 outside 전용 X 적용: new = start - X
                X_idx = rad2idx(X)
                new_idx = wrap_idx(start_idx - X_idx)

                rev_phase_idx[el] = new_idx
                rev_X_deg[el] = X * 180.0 / math.pi
                rev_Delta0_deg[el] = Delta0 * 180.0 / math.pi
                rev_Gamma[el] = Gamma

                logger.info(f"[REV-X] el={el:02d} start={start_idx:02d} Δ0={rev_Delta0_deg[el]:.2f}° Γ={Gamma:.4g} "
                            f"X={rev_X_deg[el]:.2f}° -> new={new_idx:02d}")

                if apply_now:
                    element_on_withPhase(beam, pol, new_idx, DEFAULT_GAIN_IDX, el)
                    time.sleep(CAL.SETTLE_TIME_S)

        # 1st pass: 계산만 또는 즉시 적용
        if APPLY_MODE.lower() == "sequential":
            # sequential: 계산 즉시 적용
            pass_compute_and_maybe_apply(preflip_start[:], apply_now=True)
        else:
            # batch: 먼저 전부 계산 후 일괄 적용
            pass_compute_and_maybe_apply(preflip_start[:], apply_now=False)
            # 일괄 적용
            logger.info("[REV] Apply pass-0 (batch)")
            for el in range(32):
                element_on_withPhase(beam, pol, rev_phase_idx[el], DEFAULT_GAIN_IDX, el)
            time.sleep(0.2)

        # ---------------- C) Verify passes: 동일 논문식으로 반복 (작게 수렴) ----------------
        for vp in range(VERIFY_PASSES):
            logger.info(f"[REV] Verify pass {vp+1}/{VERIFY_PASSES}")
            pass_compute_and_maybe_apply(rev_phase_idx[:], apply_now=True)

        # ---------------- D) Phase-only 결과 저장(기본 result 매트릭스는 유지) ----------------
        # 호환을 위해 빈 매트릭스라도 rev 이름으로 저장
        CSV_PATH = save_cal_matrix(result, "gain_index_sweep_log_rev.csv", include_phase_col=True)

        # Per-element 상세 로그 CSV (Δ0, Γ, X 포함)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        detailed_path = os.path.join(CAL.CSV_DIR, f"rev_phase_detail_{ts}.csv")
        with open(detailed_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["element", "start_idx", "final_phase_idx", "Delta0_deg", "Gamma", "X_deg", "K_points", "verify_passes"])
            for el in range(32):
                w.writerow([el, preflip_start[el], rev_phase_idx[el],
                            f"{rev_Delta0_deg[el]:.6f}", f"{rev_Gamma[el]:.6g}",
                            f"{rev_X_deg[el]:.6f}", K, VERIFY_PASSES])
        logger.info(f"[REV] Phase detail CSV saved: {detailed_path}")

        dt_ns = time.perf_counter_ns() - t0
        print(f"elapsed: {dt_ns/1e6:.3f} ms")
        # ---------------- E) Gain Alignment (original 방식 동일) ----------------
        logger.info("==== Gain Alignment start (Ref=17 Matching based on single power) ====")

        ref_phase_idx = rev_phase_idx[17] if rev_phase_idx[17] != 0 else 0
        gs.config_TX_FE_all_off()
        element_on_withPhase(beam, pol, ref_phase_idx, 7, 17)
        time.sleep(CAL.SETTLE_TIME_S)
        ref_pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
        logger.info(f"[REF el17] phase={ref_phase_idx}, gain=7 -> {ref_pwr_dbm:.2f} dBm")

        GAIN_SWEEP_RANGE = range(4, 11)  # 4~10 inclusive
        matched_gain = [None]*32
        matched_pwr = [None]*32
        gain_err_db = [None]*32

        for element in range(32):
            if element == 17:
                matched_gain[element] = 7
                matched_pwr[element] = ref_pwr_dbm
                gain_err_db[element] = 0.0
                logger.info("Gain Alignment: Reference 17 is set as the standard")
                continue

            el_phase = rev_phase_idx[element] if rev_phase_idx[element] != 0 else 0
            best_g, best_p, min_err = None, None, float("inf")

            logger.info(f"[El {element:02d}] Gain sweep start (phase={el_phase}, target={ref_pwr_dbm:.2f} dBm)")
            for g in GAIN_SWEEP_RANGE:
                gs.config_TX_FE_all_off()
                element_on_withPhase(beam, pol, el_phase, g, element)
                time.sleep(CAL.SETTLE_TIME_S)
                pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)

                err = abs(pwr_dbm - ref_pwr_dbm)
                logger.info(f"[El {element:02d}] gain={g:2d} -> {pwr_dbm:.2f} dBm (Δ={pwr_dbm - ref_pwr_dbm:+.2f} dB)")
                if err < min_err:
                    min_err = err
                    best_g = g
                    best_p = pwr_dbm

            matched_gain[element] = best_g
            matched_pwr[element] = best_p
            gain_err_db[element] = (best_p - ref_pwr_dbm) if best_p is not None else None

            gs.config_TX_FE_all_off()
            element_on_withPhase(beam, pol, el_phase, best_g, element)
            logger.info(f"[El {element:02d}] BEST gain={best_g}, phase={el_phase} -> {best_p:.2f} dBm (Δ={best_p - ref_pwr_dbm:+.2f} dB)")

        for i, (g, p, d) in enumerate(zip(matched_gain, matched_pwr, gain_err_db)):
            if p is None or not math.isfinite(p):
                print(f"#{i:02d}: gain={g}, power=N/A,  Δ=N/A")
            else:
                print(f"#{i:02d}: gain={g}, power={p:.2f} dBm, Δ={d:+.2f} dB")

        # ---------------- F) 최종 보정(phase+gain) 전부 적용 & 전체 파워 측정 ----------------
        gs.config_TX_FE_all_off()
        for el in range(32):
            g_final = matched_gain[el] if matched_gain[el] is not None else 7
            p_final = rev_phase_idx[el] if rev_phase_idx[el] is not None else 0
            element_on_withPhase(beam, pol, p_final, g_final, el)
        time.sleep(0.2)

        final_eirp_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
        logger.info(f"[FINAL][REV] TxP Avg Mean Power (proxy EIRP): {final_eirp_dbm:.2f} dBm")

        # Aggregate CSV (최종 전체 파워 포함)
        aggregate_path = os.path.join(CAL.CSV_DIR, f"gain_index_sweep_log_rev_aggregate.csv")
        with open(aggregate_path, "a", newline="") as f:
            w = csv.writer(f)
            if f.tell() == 0:
                w.writerow(["timestamp", "points_K", "verify_passes", "final_total_power_dBm"])
            w.writerow([datetime.datetime.now().isoformat(timespec="seconds"), K, VERIFY_PASSES, f"{final_eirp_dbm:.2f}"])
        logger.info(f"[SAVE] Aggregate CSV (final total power) appended: {aggregate_path}")

        # Settings CSV (original 형식과 동일하되 이름만 rev)
        open(os.path.splitext(CSV_PATH)[0] + "_settings_rev.csv", "w").write(
            "element,phase_idx,gain_idx\n" + "\n".join(
                f"{i},{rev_phase_idx[i]},{7 if i==17 else (matched_gain[i] if matched_gain[i] is not None else 7)}"
                for i in range(32)
            )
        )

        dt_ns = time.perf_counter_ns() - t0
        print(f"elapsed: {dt_ns/1e6:.3f} ms")


    # ===================================================  MAX Calibration (Coarse 45° -> Fine 5.625°) + Gain Alignment  =============================================================
    elif phase_cal_method == 'maxcal':
        t0 = time.perf_counter_ns()

        def wrap_range(center_idx, half_window, modulo=CAL.PHASE_STEPS):
            return [(center_idx + k) % modulo for k in range(-half_window, half_window + 1)]

        def sweep_indices_and_measure(element, indices):
            best_idx = None
            best_pwr = float("-inf")
            for idx in indices:
                element_on_withPhase(beam, pol, idx, 7, element)
                time.sleep(CAL.SETTLE_TIME_S)
                pk_pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
                result[idx][element] = pk_pwr_dbm
                if pk_pwr_dbm > best_pwr:
                    best_pwr = pk_pwr_dbm
                    best_idx = idx
                logger.info(f"[El {element:02d}] phase {idx:02d} -> {pk_pwr_dbm:.2f} dBm")
            return best_idx, best_pwr

        logger.info("Turn ON all elements with phase=0, gain=7 (reference include)")
        for el in range(32):
            element_on_withPhase(beam, pol, 0, 7, el)
        time.sleep(0.2)

        best_phase_idx = [0]*32
        best_power_dbm = [float("-inf")]*32

        for element in range(32):
            logger.info(f"[Element {element}] Coarse sweep(45°) start")
            coarse_indices = list(range(0, CAL.PHASE_STEPS, CAL.MAX_COARSE_STEP))  # 0,8,16,...,56
            coarse_best_idx, coarse_best_pwr = sweep_indices_and_measure(element, coarse_indices)
            logger.info(f"[Element {element}] Coarse max at idx={coarse_best_idx}, pwr={coarse_best_pwr:.2f} dBm")

            fine_indices_list = wrap_range(coarse_best_idx, CAL.MAX_FINE_HALF_WIN, CAL.PHASE_STEPS)
            logger.info(f"[Element {element}] Fine sweep start - center={coarse_best_idx}, size={len(fine_indices_list)}")
            fine_best_idx, fine_best_pwr = sweep_indices_and_measure(element, fine_indices_list)
            logger.info(f"[Element {element}] Fine max at idx={fine_best_idx}, pwr={fine_best_pwr:.2f} dBm")

            best_phase_idx[element] = fine_best_idx
            best_power_dbm[element] = fine_best_pwr
            #element_on_withPhase(beam, pol, fine_best_idx, 7, element)
            #logger.info(f"[Element {element}] APPLY: phase <- {fine_best_idx} (align complete)")

        for i, (idx, pwr) in enumerate(zip(best_phase_idx, best_power_dbm)):
            if math.isfinite(pwr):
                print(f"#{i:02d}: phase_idx={idx}, power={pwr:.2f} dBm")
            else:
                print(f"#{i:02d}: phase_idx={idx}, power=N/A")

        CSV_PATH = save_cal_matrix(result, "gain_index_sweep_log_maxcal.csv", include_phase_col=True)

        # ------------------------------- Gain Alignment -------------------------------
        logger.info("==== Gain Alignment start (Ref=17 Matching based on single power) ====")

        ref_phase_idx = best_phase_idx[17] if best_phase_idx[17] != 0 else 0
        gs.config_TX_FE_all_off()
        element_on_withPhase(beam, pol, ref_phase_idx, 7, 17)
        time.sleep(CAL.SETTLE_TIME_S)
        ref_pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
        logger.info(f"[REF el17] phase={ref_phase_idx}, gain=7 -> {ref_pwr_dbm:.2f} dBm")

        GAIN_SWEEP_RANGE = range(4, 11)  # 4~10 inclusive
        matched_gain = [None]*32
        matched_pwr = [None]*32
        gain_err_db = [None]*32

        for element in range(32):
            if element == 17:
                matched_gain[element] = 7
                matched_pwr[element] = ref_pwr_dbm
                gain_err_db[element] = 0.0
                logger.info("Gain Alignment: Reference 17 is set as the standard")
                continue

            el_phase = best_phase_idx[element] if best_phase_idx[element] != 0 else 0
            best_g, best_p, min_err = None, None, float("inf")

            logger.info(f"[El {element:02d}] Gain sweep start (phase={el_phase}, target={ref_pwr_dbm:.2f} dBm)")
            for g in GAIN_SWEEP_RANGE:
                gs.config_TX_FE_all_off()
                element_on_withPhase(beam, pol, el_phase, g, element)
                time.sleep(CAL.SETTLE_TIME_S)
                pwr_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)

                err = abs(pwr_dbm - ref_pwr_dbm)
                logger.info(f"[El {element:02d}] gain={g:2d} -> {pwr_dbm:.2f} dBm (Δ={pwr_dbm - ref_pwr_dbm:+.2f} dB)")
                if err < min_err:
                    min_err = err
                    best_g = g
                    best_p = pwr_dbm

            matched_gain[element] = best_g
            matched_pwr[element] = best_p
            gain_err_db[element] = (best_p - ref_pwr_dbm) if best_p is not None else None

            gs.config_TX_FE_all_off()
            element_on_withPhase(beam, pol, el_phase, best_g, element)
            logger.info(f"[El {element:02d}] BEST gain={best_g}, phase={el_phase} -> {best_p:.2f} dBm (Δ={best_p - ref_pwr_dbm:+.2f} dB)")

        for i, (g, p, d) in enumerate(zip(matched_gain, matched_pwr, gain_err_db)):
            if p is None or not math.isfinite(p):
                print(f"#{i:02d}: gain={g}, power=N/A,  Δ=N/A")
            else:
                print(f"#{i:02d}: gain={g}, power={p:.2f} dBm, Δ={d:+.2f} dB")

        gs.config_TX_FE_all_off()
        for el in range(32):
            g_final = matched_gain[el] if matched_gain[el] is not None else 7
            p_final = best_phase_idx[el] if best_phase_idx[el] is not None else 0
            element_on_withPhase(beam, pol, p_final, g_final, el)
        time.sleep(0.2)

        final_eirp_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
        logger.info(f"[FINAL] Max EIRP proxy (TxP Avg Mean Power): {final_eirp_dbm:.2f} dBm")

        open(os.path.splitext(CSV_PATH)[0] + "_settings_maxcal.csv", "w").write(
            "element,phase_idx,gain_idx\n" + "\n".join(f"{i},{best_phase_idx[i]},{matched_gain[i]}" for i in range(32))
        )

        dt_ns = time.perf_counter_ns() - t0
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
