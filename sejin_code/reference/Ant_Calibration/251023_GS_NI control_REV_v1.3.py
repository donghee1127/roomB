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

    REV_MODE="two_pass",
    FINE_HALF_WIN=16,

    IREV_ATTEN_DB=2.0,
    IREV_MIN_PROBE_HALFWIN=8,
    IREV_VERIFY_AFTER_APPLY=True,

    MAX_COARSE_STEP=8,
    MAX_FINE_HALF_WIN=4,

    # ==== REV (paper) parameters ====
    REV_POINTS=8,                # 기본 4점. 균일 분할 K점 지원
    REV_VERIFY_PASSES=0,         # 검증 패스 반복 횟수
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
phase_cal_method = 'maxcal'  # 'original' | 'rev' | 'maxcal'

# ===============================  Calibration Core (Use User Gains during Phase Cal)  =================================
# ✅ 사용자 지정 32개 Gain Index (길이 32)
#137번
USER_GAIN_IDX = [
    4,4,5,7, 6,4,5,6,
    5,4,6,9, 6,5,6,6,
    4,4,4,4, 4,4,4,6,
    5,6,4,4, 9,7,4,4
]

'''#139번
USER_GAIN_IDX = [
    7,6,4,4, 10,7,4,4,
    4,4,8,10, 5,4,6,8,
    4,4,4,5, 4,4,4,4,
    6,4,7,7, 6,6,4,10
]
'''
'''#44번
USER_GAIN_IDX = [
    6,4,5,9, 6,6,9,6,
    7,4,8,9, 6,5,10,9,
    10,7,8,8, 6,8,10,10,
    7,6,4,4, 6,7,4,10
]
'''
def _clamp_gain(g):
    try: gi = int(g)
    except: gi = 7
    # 필요시 범위 강제 (예: 4~10) -> 주석 해제
    # gi = max(4, min(10, gi))
    return gi

assert len(USER_GAIN_IDX) == 32, "USER_GAIN_IDX는 32개 값이어야 합니다."

# 공통 유틸 (측정/스윕/정리)
def idx2rad(i, ph=CAL.PHASE_STEPS):
    return (i % ph) * CAL.PHASE_STEP_RAD

def rad2idx(rad, ph=CAL.PHASE_STEPS):
    return int(round((rad % (2*math.pi)) / CAL.PHASE_STEP_RAD)) % ph

def k_indices(start_idx, k, ph=CAL.PHASE_STEPS):
    return [wrap_idx(start_idx + round(t * ph / k)) for t in range(k)]

def measure_element(beam, pol, phase_idx, el, gain_idx=None):
    """gain_idx가 None이면 해당 el의 USER_GAIN_IDX를 사용"""
    g = _clamp_gain(USER_GAIN_IDX[el] if gain_idx is None else gain_idx)
    element_on_withPhase(beam, pol, phase_idx, g, el)
    time.sleep(CAL.SETTLE_TIME_S)
    p_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
    return p_dbm

def sweep_phase_indices(element, indices, log_prefix=""):
    """스윕 동안에도 항상 USER_GAIN_IDX[element] 사용"""
    best_idx, best_pwr = None, float("-inf")
    for idx in indices:
        p_dbm = measure_element(beam, pol, idx, element, gain_idx=None)  # None -> 사용자 지정 gain
        result[idx][element] = p_dbm
        if p_dbm > best_pwr:
            best_idx, best_pwr = idx, p_dbm
        logger.info(f"{log_prefix}[El {element:02d}] phase {idx:02d} -> {p_dbm:.2f} dBm")
    return best_idx, best_pwr

def apply_user_gains_and_save(phase_idx_arr, csv_basename, settings_suffix):
    """
    phase 캘 종료 후: 사용자 지정 USER_GAIN_IDX와 조합해 전 요소 적용 → 최종 파워 측정 → settings CSV 저장
    """
    gs.config_TX_FE_all_off()
    for el in range(32):
        ph = (phase_idx_arr[el] if phase_idx_arr[el] is not None else 0) & 0x3F
        g  = _clamp_gain(USER_GAIN_IDX[el])
        element_on_withPhase(beam, pol, ph, g, el)
    time.sleep(0.2)

    final_total_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
    logger.info(f"[FINAL] Apply phase(cal) + USER_GAIN_IDX → TxP Avg Mean Power (proxy EIRP) = {final_total_dbm:.2f} dBm")

    open(os.path.splitext(csv_basename)[0] + settings_suffix, "w").write(
        "element,phase_idx,gain_idx\n" + "\n".join(
            f"{i},{(phase_idx_arr[i] if phase_idx_arr[i] is not None else 0)},{_clamp_gain(USER_GAIN_IDX[i])}"
            for i in range(32)
        )
    )
    return final_total_dbm

# 1) 참조 엘리먼트 시동: phase=0, **gain도 사용자 지정값으로**
element_on_withPhase(beam, pol, 0, _clamp_gain(USER_GAIN_IDX[17]), 17)

# 2) NI 장비 구성
config_generator(txrx=txrx, beam=beam, qam='64qam', cc=1, freq=if_freq, pwr=CAL.SG_FIXED_POWER_DBM, ext_atten=0)
time.sleep(CAL.EXTRA_WAIT_AFTER_SG_S)
config_analyzer(txrx=txrx, beam=beam, qam='64qam', cc=1, freq=rf_freq, ref_level=0, ext_atten=0)
meas_settings(meas=Test.txp, txrx=txrx, cc=1)

# 3) 결과 매트릭스
result = init_result_matrix(phases=CAL.PHASE_STEPS, elements=32)

try:
    # ===================== ORIGINAL =====================
    if phase_cal_method == 'original':
        t0 = time.perf_counter_ns()
        phase_idx_arr = [None]*32
        peak_pwr_arr  = [float("-inf")]*32

        for el in range(32):
            if el == 17:
                logger.info("Reference Element(17) skip and fill all 0")  # 기존 정책 유지
                continue

            # sweep 전: ref(17) ON (사용자 gain)
            gs.config_TX_FE_all_off()
            element_on_withPhase(beam, pol, 0, _clamp_gain(USER_GAIN_IDX[17]), 17)

            logger.info(f"[Element {el:02d}] Phase sweep start (use USER_GAIN_IDX[{el}]={_clamp_gain(USER_GAIN_IDX[el])})")
            idxs = list(range(CAL.PHASE_STEPS))
            best_idx, best_pwr = sweep_phase_indices(el, idxs, log_prefix="[ORIG] ")
            phase_idx_arr[el], peak_pwr_arr[el] = best_idx, best_pwr

            # 스윕 후 해당 el 적용도 사용자 gain으로
            element_on_withPhase(beam, pol, best_idx, _clamp_gain(USER_GAIN_IDX[el]), el)
            print(f'max power: {best_pwr:.2f} max index: {best_idx}')

        for i, (idx, pwr) in enumerate(zip(phase_idx_arr, peak_pwr_arr)):
            print(f"#{i:02d}: {idx}(index), {(pwr if math.isfinite(pwr) else float('nan')):.2f}(dBm)" if math.isfinite(pwr) else f"#{i:02d}: {idx}(index), N/A(dBm)")

        CSV_PATH = save_cal_matrix(result, "gain_index_sweep_log_original.csv", include_phase_col=True)

        # ✅ Gain Alignment 없이 사용자 지정 gain으로 최종 적용/저장
        final_total_dbm = apply_user_gains_and_save(phase_idx_arr, CSV_PATH, "_settings.csv")
        dt_ns = time.perf_counter_ns() - t0
        print(f"elapsed: {dt_ns/1e6:.3f} ms")

# ===================== REV (paper Γ, Δ0, outside only) =====================
    elif phase_cal_method == 'rev':

        """
        REV: 모든 측정/적용에서 해당 el의 USER_GAIN_IDX 사용 (pre-flip, K점, verify, apply 모두)
        """
        t0 = time.perf_counter_ns()
        PH = CAL.PHASE_STEPS
        K  = int(getattr(CAL, "REV_POINTS", 4))
        VERIFY_PASSES = int(getattr(CAL, "REV_VERIFY_PASSES", 1))
        APPLY_MODE = getattr(CAL, "REV_APPLY_MODE", "batch")  # "batch" | "sequential"

        # --- 사인 회귀 준비(있으면 scipy, 없으면 a*sin+b*cos 선형적합 사용)
        try:
            import numpy as _np
            try:
                from scipy.optimize import curve_fit as _curve_fit
            except Exception:
                _curve_fit = None
        except Exception:
            _np = None
            _curve_fit = None

        def _sine_fit_max_angle_deg(angles_deg, y_dbm):
            """
            angles_deg: [0, 90, 180, 270] 같은 degree 리스트 (start 기준 상대각)
            y_dbm     : 각 각도에서의 측정 파워(dBm) 리스트
            return    : max_angle_deg in [0,360)
            """
            import math
            if _np is not None and _curve_fit is not None:
                angles_deg = _np.asarray(angles_deg, dtype=float)
                y_dbm      = _np.asarray(y_dbm, dtype=float)
                def sine_func(x, A, phi, C):
                    return A * _np.sin(_np.deg2rad(x) + phi) + C
                p0_A  = max(1.0, 0.5*(float(_np.max(y_dbm))-float(_np.min(y_dbm))))
                p0    = [p0_A, 0.0, float(_np.mean(y_dbm))]
                params, _ = _curve_fit(sine_func, angles_deg, y_dbm, p0=p0, maxfev=10000)
                A_fit, phi_fit, C_fit = [float(x) for x in params]
                x_fit = _np.linspace(0.0, 360.0, 2001)
                y_fit = sine_func(x_fit, A_fit, phi_fit, C_fit)
                max_idx = int(_np.argmax(y_fit))
                return float(x_fit[max_idx]) % 360.0

            # scipy 없으면 y = a*sinθ + b*cosθ + c 최소제곱 적합
            import math, numpy as _np2
            ang_rad = [math.radians(a) for a in angles_deg]
            S  = sum(math.sin(t) for t in ang_rad)
            Cc = sum(math.cos(t) for t in ang_rad)
            SS = sum(math.sin(t)**2 for t in ang_rad)
            CC = sum(math.cos(t)**2 for t in ang_rad)
            SC = sum(math.sin(t)*math.cos(t) for t in ang_rad)
            Y  = sum(y_dbm)
            YS = sum(y*math.sin(t) for y,t in zip(y_dbm, ang_rad))
            YC = sum(y*math.cos(t) for y,t in zip(y_dbm, ang_rad))
            M = _np2.array([[SS, SC, S],
                            [SC, CC, Cc],
                            [S,  Cc, len(ang_rad)]], dtype=float)
            v = _np2.array([YS, YC, Y], dtype=float)
            try:
                a, b, c = _np2.linalg.solve(M, v)
            except Exception:
                a = 0.0; b = 0.0
            phi = math.atan2(b, a)              # rad
            max_angle = (90.0 - math.degrees(phi)) % 360.0
            return max_angle

        def fit_C_R_Delta0(indices, elem):
            """
            기존처럼 C, R은 'mW 선형합'으로 계산.
            단, Δ0는 4포인트(dBm) 사인회귀로 얻은 '최대점 각도'의 부호를 뒤집어 사용(모델 일치).
            """
            Kloc = len(indices)
            sumP = 0.0; sumPc = 0.0; sumPs = 0.0
            samples_dbm = []
            rel_angles_deg = []  # 0,90,180,270 (start 기준)
            for k, idx in enumerate(indices):
                p_dbm = measure_element(beam, pol, idx, elem, gain_idx=None)  # 사용자 gain
                p_mw  = dbm_to_mw(p_dbm)
                th    = idx2rad(idx)
                sumP  += p_mw
                sumPc += p_mw * math.cos(th)
                sumPs += p_mw * math.sin(th)
                samples_dbm.append((idx, p_dbm))

            # C, R 계산 (선형파워)
            C = sumP / max(Kloc, 1)
            U = (2.0 / Kloc) * sumPc
            V = (2.0 / Kloc) * sumPs
            R = math.hypot(U, V)

            # --- Δ0 계산만 사인 회귀 방식(측정 dBm, start 기준 0/90/180/270)
            # k_indices가 균등 분포(64 분해능 가정)라고 가정
            rel_angles_deg = [0.0, 90.0, 180.0, 270.0] if Kloc == 4 else [360.0*i/Kloc for i in range(Kloc)]
            y_dbm_only     = [p for (_, p) in samples_dbm]
            max_angle_deg  = _sine_fit_max_angle_deg(rel_angles_deg, y_dbm_only)
            # 모델 P(φ)=C+R cos(φ+Δ0)의 최대는 φ* = -Δ0 이므로, Δ0 = -max_angle
            Delta0 = - math.radians(max_angle_deg)
            # wrap to (-pi, pi]
            Delta0 = (Delta0 + math.pi) % (2*math.pi) - math.pi
            logger.info(
                f"[REV-FIT] el={elem:02d} K={Kloc} " +
                " ".join([f"(idx={i:02d}, {p:.2f} dBm)" for (i, p) in samples_dbm])
            )
            logger.info(f"[REV-FIT][RES] el={elem:02d} C={C:.6g} mW, R={R:.6g} mW, "
                        f"Δ0(from sin-fit)={Delta0*180/math.pi:.2f}° (max={max_angle_deg:.2f}°)")
            return C, R, Delta0

        def _wrap_pi(x):
            return (x + math.pi) % (2*math.pi) - math.pi

        def compute_gamma_and_X(C, R, Delta0):
            Pmax = C + R
            Pmin = max(C - R, 1e-15)
            Emax = math.sqrt(Pmax)
            Emin = math.sqrt(Pmin)
            Gamma = (Emax + Emin) / max(Emax - Emin, 1e-15)
            # 원점 기준 각도(X_arg) → 논문식
            X = math.atan2(math.sin(Delta0), math.cos(Delta0) + 1/Gamma)
            return Gamma, X, Emax, Emin

        # A) 1-bit Pre-flip (각 el의 사용자 gain으로 0/180 비교)
        logger.info("[REV] Phase-A: 1-bit Pre-flip (record only, use USER_GAIN_IDX)")
        preflip_start = [0]*32
        for el in range(32):
            element_on_withPhase(beam, pol, preflip_start[el], _clamp_gain(USER_GAIN_IDX[el]), el)
        pre_flip = True
        if pre_flip is True:
            for el in range(32):
                p0_dbm   = measure_element(beam, pol, 0,  el, gain_idx=None)
                p180_dbm = measure_element(beam, pol, 31, el, gain_idx=None)
                s = 0 if p0_dbm >= p180_dbm else 31
                preflip_start[el] = s
                logger.info(f"[REV-PREFLIP] el={el:02d} choose start={s} (P0={p0_dbm:.2f} dBm, P180={p180_dbm:.2f} dBm)")
                element_on_withPhase(beam, pol, 0, _clamp_gain(USER_GAIN_IDX[el]), el)

        # B) Δ0(사인회귀), Γ -> X -> new_idx
        logger.info("[REV] Phase-B: K-point measurement & compute X (use USER_GAIN_IDX)")
        phase_idx_arr = [0]*32
        X_deg_arr, Delta0_deg_arr, Gamma_arr, Emax_arr, Emin_arr = [0.0]*32, [0.0]*32, [float("nan")]*32, [0.0]*32, [0.0]*32

        def pass_compute_and_maybe_apply(curr_start_idx, apply_now):
            for el in range(32):
                start_idx = curr_start_idx[el]
                idxs = k_indices(start_idx, K, PH)  # 균등 4점(0/90/180/270) 가정
                C, R, Delta0 = fit_C_R_Delta0(idxs, el)
                Gamma, X, Emax, Emin = compute_gamma_and_X(C, R, Delta0)
                X_idx  = rad2idx(X, PH)
                new_idx = wrap_idx(start_idx - X_idx, PH)

                phase_idx_arr[el]  = new_idx
                X_deg_arr[el]      = X * 180.0 / math.pi
                Delta0_deg_arr[el] = Delta0 * 180.0 / math.pi
                Gamma_arr[el]      = Gamma
                Emax_arr[el]       = Emax
                Emin_arr[el]       = Emin

                logger.info(f"[REV-X] el={el:02d} start={start_idx:02d} Δ0={Delta0_deg_arr[el]:.2f}° Γ={Gamma:.4g} "
                            f"Emax={Emax_arr[el]:.6f} Emin={Emin_arr[el]:.6f} X={X_deg_arr[el]:.2f}° -> new={new_idx:02d}")
                element_on_withPhase(beam, pol, preflip_start[el], _clamp_gain(USER_GAIN_IDX[el]), el)
                if apply_now:
                    element_on_withPhase(beam, pol, new_idx, _clamp_gain(USER_GAIN_IDX[el]), el)
                    time.sleep(CAL.SETTLE_TIME_S)

        if APPLY_MODE.lower() == "sequential":
            pass_compute_and_maybe_apply(preflip_start[:], apply_now=True)
        else:
            for el in range(32):
                element_on_withPhase(beam, pol, preflip_start[el], _clamp_gain(USER_GAIN_IDX[el]), el)
            pass_compute_and_maybe_apply(preflip_start[:], apply_now=False)
            logger.info("[REV] Apply pass-0 (batch, use USER_GAIN_IDX)")
            for el in range(32):
                element_on_withPhase(beam, pol, phase_idx_arr[el], _clamp_gain(USER_GAIN_IDX[el]), el)
            time.sleep(0.2)

        for vp in range(VERIFY_PASSES):
            logger.info(f"[REV] Verify pass {vp+1}/{VERIFY_PASSES}")
            pass_compute_and_maybe_apply(phase_idx_arr[:], apply_now=True)

        CSV_PATH = save_cal_matrix(result, "gain_index_sweep_log_rev.csv", include_phase_col=True)

        # ✅ 최종: 사용자 지정 gain으로 적용/측정/저장
        final_total_dbm = apply_user_gains_and_save(phase_idx_arr, CSV_PATH, "_settings_rev.csv")

        dt_ns = time.perf_counter_ns() - t0
        print(f"elapsed: {dt_ns/1e6:.3f} ms")



# ===================== MAXCAL (Δ0 로 보정: 사인 회귀 방식) =====================
    elif phase_cal_method == 'maxcal':
        """
        REV: 모든 측정/적용에서 해당 el의 USER_GAIN_IDX 사용 (pre-flip, K점, verify, apply 모두)
        """
        t0 = time.perf_counter_ns()
        PH = CAL.PHASE_STEPS                     # 64
        K  = int(getattr(CAL, "REV_POINTS", 4))  # 4 포인트 (0,90,180,270)
        VERIFY_PASSES = int(getattr(CAL, "REV_VERIFY_PASSES", 1))
        APPLY_MODE = getattr(CAL, "REV_APPLY_MODE", "batch")  # "batch" | "sequential"

        # --- 사인 회귀 준비 (scipy 있으면 사용, 없으면 간단 회귀 사용)
        try:
            import numpy as _np
            try:
                from scipy.optimize import curve_fit as _curve_fit
            except Exception:
                _curve_fit = None
        except Exception:
            _np = None
            _curve_fit = None

        def _sine_fit_max_angle_deg(angles_deg, y_dbm):
            """
            angles_deg: [0, 90, 180, 270] 같은 degree 리스트
            y_dbm     : 각 각도에서의 측정 파워(dBm) 리스트
            return    : (max_angle_deg, A, phi_rad, C)  # max_angle_deg in [0,360)
            """
            import math
            # scipy가 있으면 네가 준 방식 그대로
            if _np is not None and _curve_fit is not None:
                angles_deg = _np.asarray(angles_deg, dtype=float)
                y_dbm      = _np.asarray(y_dbm, dtype=float)

                def sine_func(x, A, phi, C):
                    return A * _np.sin(_np.deg2rad(x) + phi) + C

                p0_A  = max(1.0, 0.5 * (float(_np.max(y_dbm)) - float(_np.min(y_dbm))))
                p0    = [p0_A, 0.0, float(_np.mean(y_dbm))]
                params, _ = _curve_fit(sine_func, angles_deg, y_dbm, p0=p0, maxfev=10000)
                A_fit, phi_fit, C_fit = [float(x) for x in params]

                x_fit = _np.linspace(0.0, 360.0, 2001)
                y_fit = sine_func(x_fit, A_fit, phi_fit, C_fit)
                max_idx = int(_np.argmax(y_fit))
                max_angle = float(x_fit[max_idx]) % 360.0
                return max_angle, A_fit, phi_fit, C_fit

            # scipy 없으면 y = a*sinθ + b*cosθ + c 로 최소제곱 적합
            # A*sin(θ+φ) + C 와 동치. φ = atan2(b, a), 최대는 θ* = 90° - φ(°).
            angles_rad = [math.radians(a) for a in angles_deg]
            S = sum(math.sin(t) for t in angles_rad)
            Cc = sum(math.cos(t) for t in angles_rad)
            SS = sum(math.sin(t)**2 for t in angles_rad)
            CC = sum(math.cos(t)**2 for t in angles_rad)
            SC = sum(math.sin(t)*math.cos(t) for t in angles_rad)
            Y  = sum(y_dbm)
            YS = sum(y*math.sin(t) for y,t in zip(y_dbm, angles_rad))
            YC = sum(y*math.cos(t) for y,t in zip(y_dbm, angles_rad))
            # 선형계 행렬 [ [SS, SC, S], [SC, CC, Cc], [S, Cc, len] ] * [a,b,c]^T = [YS, YC, Y]^T
            # 3x3 풀기
            import numpy as _np2
            M = _np2.array([[SS, SC, S],
                            [SC, CC, Cc],
                            [S,  Cc, len(angles_rad)]], dtype=float)
            v = _np2.array([YS, YC, Y], dtype=float)
            try:
                a, b, c = _np2.linalg.solve(M, v)
            except Exception:
                # fallback: 평균/직접 추정
                a = 0.0; b = 0.0; c = Y/len(angles_rad)
            A_fit = math.hypot(a, b)
            phi   = math.atan2(b, a)  # rad
            max_angle = (90.0 - math.degrees(phi)) % 360.0
            return max_angle, A_fit, phi, c

        def fit_max_from_four_points(indices, elem):
            """
            indices: [start, start+16, start+32, start+48] (64분해능 가정)
            elem   : element index
            return : (Delta0_rad, samples_dbm_list, max_angle_deg)
            """
            samples_dbm = []
            for i, idx in enumerate(indices):
                p_dbm = measure_element(beam, pol, idx, elem, gain_idx=None)  # 사용자 gain
                samples_dbm.append((idx, p_dbm))
            # 상대각: 0, 90, 180, 270
            angles_deg = [0.0, 90.0, 180.0, 270.0]
            y_dbm      = [p for (_, p) in samples_dbm]
            max_ang_deg, A_fit, phi_fit, C_fit = _sine_fit_max_angle_deg(angles_deg, y_dbm)

            logger.info(f"[SINE-FIT] el={elem:02d} " +
                        " ".join([f"(idx={i:02d}, {p:.2f} dBm)" for (i,p) in samples_dbm]))
            logger.info(f"[SINE-FIT][RES] el={elem:02d} A={A_fit:.3f}, phi={phi_fit:.3f} rad, C={C_fit:.3f} dBm, Δ0(max)={max_ang_deg:.2f}°")
            Delta0_rad = math.radians(max_ang_deg)  # 0..2π
            return Delta0_rad, samples_dbm, max_ang_deg

        # --- 실측 전력 한 번 재는 헬퍼(±1 스텝 미세탐색용)
        def _measure_power_at(idx, el):
            element_on_withPhase(beam, pol, idx, _clamp_gain(USER_GAIN_IDX[el]), el)
            time.sleep(CAL.SETTLE_TIME_S)
            p_dbm, _ = meas_results(meas=Test.txp, cc=1, logEn=False, include_delta=False)
            return p_dbm

        # A) 0으로 초기화
        logger.info("[Max] Phase-A: initial 0 (use USER_GAIN_IDX)")
        preflip_start = [0]*32
        for el in range(32):
            element_on_withPhase(beam, pol, preflip_start[el], _clamp_gain(USER_GAIN_IDX[el]), el)

        # B) 4점(0/90/180/270) 측정 -> 사인 회귀 -> Δ0(max) -> new_idx
        logger.info("[Max] Phase-B: 4-point sine fit & compute Δ0(max) (use USER_GAIN_IDX)")
        phase_idx_arr = [0]*32
        Delta0_deg_arr = [0.0]*32

        def pass_compute_and_maybe_apply(curr_start_idx, apply_now):
            for el in range(32):
                start_idx = curr_start_idx[el]
                # 64분해능 가정: 90° = +16 step
                idxs = [wrap_idx(start_idx + d, PH) for d in (0, PH//4, PH//2, 3*PH//4)]
                Delta0_rad, samples_dbm, Delta0_deg = fit_max_from_four_points(idxs, el)

                # 인덱스 이동량 = Δ0(도) / 360 * PH   (현재 start에서 최대점으로 '플러스' 방향 이동)
                Delta0_idx = int(round(Delta0_deg / 360.0 * PH))
                base_idx   = wrap_idx(start_idx + Delta0_idx, PH)

                # --- ±1 스텝 미세탐색(실측)으로 안정화
                candidates = [wrap_idx(base_idx + d, PH) for d in (-1, 0, +1)]
                best_idx, best_p = None, float("-inf")
                for k in candidates:
                    p_dbm = _measure_power_at(k, el)
                    if p_dbm > best_p:
                        best_p, best_idx = p_dbm, k

                # 배치 모드면 계산 중 건드린 위상을 원상복구(다음 el 보호)
                if not apply_now:
                    element_on_withPhase(beam, pol, preflip_start[el], _clamp_gain(USER_GAIN_IDX[el]), el)

                phase_idx_arr[el]  = best_idx
                Delta0_deg_arr[el] = Delta0_deg
                logger.info(f"[REV-X] el={el:02d} start={start_idx:02d} Δ0(max)={Delta0_deg:6.2f}° "
                            f"-> base={base_idx:02d} -> new(best)={best_idx:02d} (±1 searched)")

                if apply_now:
                    element_on_withPhase(beam, pol, best_idx, _clamp_gain(USER_GAIN_IDX[el]), el)
                    time.sleep(CAL.SETTLE_TIME_S)

        if APPLY_MODE.lower() == "sequential":
            pass_compute_and_maybe_apply(preflip_start[:], apply_now=True)
        else:
            for el in range(32):
                element_on_withPhase(beam, pol, preflip_start[el], _clamp_gain(USER_GAIN_IDX[el]), el)
            pass_compute_and_maybe_apply(preflip_start[:], apply_now=False)
            logger.info("[REV] Apply pass-0 (batch, use USER_GAIN_IDX)")
            for el in range(32):
                element_on_withPhase(beam, pol, phase_idx_arr[el], _clamp_gain(USER_GAIN_IDX[el]), el)
            time.sleep(0.2)

        for vp in range(VERIFY_PASSES):
            logger.info(f"[REV] Verify pass {vp+1}/{VERIFY_PASSES}")
            pass_compute_and_maybe_apply(phase_idx_arr[:], apply_now=True)

        CSV_PATH = save_cal_matrix(result, "gain_index_sweep_log_maxcal.csv", include_phase_col=True)

        # ✅ 최종: 사용자 지정 gain으로 적용/측정/저장
        final_total_dbm = apply_user_gains_and_save(phase_idx_arr, CSV_PATH, "_settings_maxcal.csv")

        dt_ns = time.perf_counter_ns() - t0
        print(f"elapsed: {dt_ns/1e6:.3f} ms")


finally:
    try:
        inst.rfsg.set_pwr(pwr=-50); inst.rfsg.mod_off()
    except: pass
    try:
        inst.rfsg.close()
    except: pass
    try:
        inst.rfmx.close()
    except: pass
    inst = 0

