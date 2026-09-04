'''Imports'''
from mvboard.GumStick import GumStick
from time import sleep
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
rf_freq = Center_f["Mid"] # Select carrier
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
    print("el: {},\tpath: {},\tswap_path: {},\tps_idx: {}".format(el, log_path, phy_path, phase))
        

################################   GS Initial  ######################################################
gs = GumStick(n = gumstick_port) # G/S Open
init_RFIC() # Init PMU / Init vcxo pll / Set rf / Set mixer / Set pll
gs.digital_test()
set_txrx(txrx=txrx , beam = beam, band = band) # Set txrx
#flash_load_cal_data(panel=panel, band=band, loc = [0,1,3]) # Load beambook -> beambook 로드하지 않고 수동으로 Cal 진행
gs.config_TX_FE_all_off() # Tx fe off
gs.config_RX_FE_all_off() # Rx fe off
gs.pll_recal('3554') # PLL Recal
time.sleep(1)
atten(0) # Attenuation
set_beam_mode('30x15', beam, pol, txrx) # Set beam mode
set_beam_index(0) # set beam index
gs.read_avgtemp() # Read AvgTemp
######################################################################################################


################################   계측 장비 설정 (NI PXIe-5831)  #####################################
import csv
from typing import Optional, List

# =========================
# 사용자 설정 (NI 자원명)
# =========================
# >>> GPT (NI): 실제 장비 슬롯/리소스 이름으로 변경하세요.
NI_RFSG_RESOURCE = "mmWave_VST"   # PXIe-5831의 RFSG 기능 리소스
NI_RFSA_RESOURCE = "mmWave_VST"   # PXIe-5831의 RFSA/SpecAn 기능 리소스 (동일 모듈이면 같은 슬롯 사용 가능)

# SG 고정 파워 설정 및 안정화
SG_FIXED_POWER_DBM     = -20.0     # 요구사항: IF에서 -20 dBm CW 송출
SETTLE_TIME_S          = 0.20
EXTRA_WAIT_AFTER_SG_S  = 3.0

# CSV 경로
CSV_PATH = r"C:\Users\Dosan\gain_index_sweep_log.csv"

# >>> GPT (NI): 패키지 임포트
from nirfsg import Session as RfsgSession          # NI-RFSG Python API
from nirfmxspecan import Session as RfmxSpecAn     # NI-RFmx SpecAn Python API

# ------------------------------------------------------------------------------------------
# >>> GPT (NI): NI-RFSG/SpecAn 유틸
# ------------------------------------------------------------------------------------------
class NIRFSGController:
    def __init__(self, resource: str):
        self.sess: Optional[RfsgSession] = None
        self.resource = resource

    def open(self):
        # reset=False로 열고 필요시 init 옵션 추가 가능
        self.sess = RfsgSession(self.resource, reset=False)
        self.sess.rf.out_enabled = False

    def close(self):
        try:
            if self.sess:
                self.sess.close()
        except:
            pass
        self.sess = None

    def setup_cw(self, freq_hz: float, power_dbm: float):
        assert self.sess is not None
        logger.info(f"RFSG CW 설정: Freq={freq_hz/1e9:.3f} GHz, Power={power_dbm} dBm")
        s = self.sess
        s.abort()
        s.ref_clock.source = "OnboardClock"   # 필요시 PXI_Clk10 등으로 변경
        s.signal_path.selected_path = ""      # 기본 경로
        s.output.enabled = False
        s.rf.frequency = freq_hz
        s.rf.power_level = power_dbm
        s.initiate()
        s.output.enabled = True

class NIRFmxSpecAnController:
    def __init__(self, resource: str, selector_string: str = ""):
        self.resource = resource
        self.selector = selector_string or ""
        self.sess: Optional[RfmxSpecAn] = None

    def open(self):
        # instrument_mode="SG"가 아니라 SpecAn 모드
        self.sess = RfmxSpecAn(self.resource, "")
        # 디폴트 트레이스/트리거 설정 등은 측정 전 단계에서 구성

    def close(self):
        try:
            if self.sess:
                self.sess.close()
        except:
            pass
        self.sess = None

    def setup_spectrum(self, center_hz: float, span_hz: float = 1e6, rbw_hz: float = 100e3, ref_level_dbm: float = 10.0):
        """스펙트럼 측정 구성 (피크 파워 탐색용)"""
        assert self.sess is not None
        sa = self.sess
        sa.reset()
        sa.configure_frequency(self.selector, center_hz)
        sa.configure_reference_level(self.selector, ref_level_dbm)
        sa.spectrum.configure_span(self.selector, span_hz)
        sa.spectrum.configure_rbw_filter(self.selector, True, rbw_hz, 0.0)
        sa.spectrum.configure_measurement(self.selector, True)
        # Average 등 옵션(필요시)
        sa.spectrum.configure_number_of_spectral_lines(self.selector, 801)  # 해상도 적당히
        sa.spectrum.configure_detector(self.selector, "RMS")

    def fetch_peak_power_dbm(self, timeout_s: float = 5.0) -> float:
        """스윕 실행 후 피크 전력(dBm) 반환"""
        assert self.sess is not None
        sa = self.sess
        sa.spectrum.select_measurement(self.selector, "SPECTRUM")
        sa.spectrum.initiate(self.selector, "")
        # 파형/스펙트럼 가져오기
        x_data, y_data = sa.spectrum.fetch_spectrum(self.selector, timeout_s)
        # y_data 가 dBm 스케일 (RFmx SpecAn 기본 단위: dBm)
        if y_data is None or len(y_data) == 0:
            return float("nan")
        return float(max(y_data))

# ------------------------------------------------------------------------------------------
# >>> GPT (NI): CSV 헬퍼 (행=phase, 열=element; 17번은 0 유지)
# ------------------------------------------------------------------------------------------
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
    logger.info(f"CSV 저장 완료: {csv_path}")

# ==================================================================================================
# =====================================  Phase Cal_Original (NI)  ==================================
# ==================================================================================================

# 1) 참조 엘리먼트 고정 설정 (gain 10, phase 0)
element_on_withPhase('b1', 'h', 0, 10, 17)  # 17번 reference

# >>> GPT (NI): NI 장비 연결/초기화
rfsg = NIRFSGController(NI_RFSG_RESOURCE)
specan = NIRFmxSpecAnController(NI_RFSA_RESOURCE)
rfsg.open()
specan.open()
try:
    # 2) SG: IF 5 GHz, -20 dBm CW 송출
    rfsg.setup_cw(if_freq, SG_FIXED_POWER_DBM)
    time.sleep(EXTRA_WAIT_AFTER_SG_S)

    # 3) SA: RF 중심에서 스펙트럼 설정 (1 MHz span, RBW 100 kHz, RMS 검파)
    specan.setup_spectrum(center_hz=rf_freq, span_hz=1e6, rbw_hz=100e3, ref_level_dbm=10.0)

    # 4) 결과 매트릭스 준비
    result = init_result_matrix(phases=64, elements=32)

    # 5) 엘리먼트 루프 (0..31), 단 17번은 스킵
    for element in range(32):
        if element == 17:
            logger.info("참조 엘리먼트(17) 스킵 및 0으로 채움")
            continue

        gs.config_TX_FE_all_off()
        Element_On('b1', 'h', element)
        logger.info(f"[Element {element}] ON 및 Phase sweep 시작")

        # 6) phase 0~63 sweep → 피크 전력(dBm) 측정
        for phase in range(64):
            element_on_withPhase('b1', 'h', phase, 10, element)
            time.sleep(SETTLE_TIME_S)
            pwr_dbm = specan.fetch_peak_power_dbm(timeout_s=5.0)
            result[phase][element] = pwr_dbm
            logger.info(f"[El {element:02d}] phase {phase:02d} -> {pwr_dbm:.2f} dBm")

        # 7) element 초기화
        element_on_withPhase('b1', 'h', 0, 10, element)

    # 8) CSV 저장 (행=phase, 열=element)
    save_matrix_csv(result, CSV_PATH, include_phase_col=True)

finally:
    # NI 장비 세션 정리
    rfsg.close()
    specan.close()
