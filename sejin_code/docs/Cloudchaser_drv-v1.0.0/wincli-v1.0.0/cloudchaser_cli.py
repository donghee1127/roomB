import cmd
import ctypes
import sys

class CloudchaserDrv():

    MX_MAX_ADDRESS = 8332

    def __init__(self, dll_path:str='.\\'):
        self.lib = ctypes.WinDLL (dll_path + 'Cloudchaser.dll')
        self.lib.spi_initialize.argtypes = (ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32)
        self.lib.spi_initialize.restype = ctypes.c_int
        self.lib.spi_close.argtypes = ()
        self.lib.spi_reset.argtypes = ()
        self.lib.spi_upd.argtypes = ()
        self.lib.spi_load_address.argtypes = (ctypes.c_uint32, ctypes.c_uint32)
        self.lib.spi_load_address.restype = ctypes.c_int
        self.lib.spi_write.argtypes = (ctypes.c_uint32, ctypes.c_uint32)
        self.lib.spi_read.argtypes = (ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32))
        self.lib.spi_read.restype = ctypes.c_int
        self.lib.spi_write_extended.argtypes = (ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32)
        self.lib.spi_read_extended.argtypes = (ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32)
        self.lib.spi_adc_capture.argtypes = (ctypes.c_uint32,)
        self.lib.spi_clk.argtypes = (ctypes.c_uint32,)

    def spi_init(self, spi_speed):
        self.lib.spi_initialize(ctypes.c_uint32(spi_speed), ctypes.c_uint32(4), ctypes.c_uint32(1))

    def spi_close(self):
        self.lib.spi_close()

    def spi_reset(self):
        self.lib.spi_reset()

    def spi_beam_upd(self):
        self.lib.spi_upd()

    def spi_load_address(self, chip_id, address):
        if address < CloudchaserDrv.MX_MAX_ADDRESS:
            self.lib.spi_load_address(ctypes.c_uint32(chip_id), ctypes.c_uint32(address))

    def spi_write(self, chip_id, address, data):
        if address < CloudchaserDrv.MX_MAX_ADDRESS:
            self.lib.spi_load_address(ctypes.c_uint32(chip_id), ctypes.c_uint32(address))
        self.lib.spi_write(ctypes.c_uint32(chip_id), ctypes.c_uint32(data))

    def spi_read(self, chip_id, address):
        if address < CloudchaserDrv.MX_MAX_ADDRESS:
            self.lib.spi_load_address(ctypes.c_uint32(chip_id), ctypes.c_uint32(address))
        data = ctypes.c_uint32()
        self.lib.spi_read(ctypes.c_uint32(chip_id), ctypes.byref(data))
        return data.value

    def spi_write_ex(self, chip_id, address, data):
        if address < CloudchaserDrv.MX_MAX_ADDRESS:
            self.lib.spi_load_address(ctypes.c_uint32(chip_id), ctypes.c_uint32(address))
        send_data = (ctypes.c_ulong * len(data))(*data)
        send_data_array = ctypes.cast(send_data, ctypes.POINTER(ctypes.c_ulong))
        self.lib.spi_write_extended(ctypes.c_uint32(chip_id), send_data_array, ctypes.c_uint32(len(data)))

		
    def spi_read_ex(self, chip_id, address, length):
        if address < CloudchaserDrv.MX_MAX_ADDRESS:
            self.lib.spi_load_address(ctypes.c_uint32(chip_id), ctypes.c_uint32(address))
        receive_data = (ctypes.c_ulong * length)()
        receive_data_array = ctypes.cast(receive_data, ctypes.POINTER(ctypes.c_ulong))
        self.lib.spi_read_extended(ctypes.c_uint32(chip_id), receive_data_array, ctypes.c_uint32(length))
        data = []
        for n in range(length):
            data.append(receive_data_array[n])
        return data
    
    def spi_adc_capture(self, chip_id):
        self.lib.spi_adc_capture(ctypes.c_uint32(chip_id))

    def spi_clk(self, n):
        self.lib.spi_clk(ctypes.c_uint32(n))


class CloudchaserCli(cmd.Cmd):
    prompt = '$ '
    intro = 'Cloudchaser CLI.'

    Cloudchaser_drv = None
    

    def _get_int(self, int_str):
        try:
            int_value = int(int_str)
        except ValueError:
            int_value = int(int_str, 16)
        return int_value
    
    def _make_data_list(self, data_str):
        data = []
        for element in data_str:
            try:
                data.append(int(element))
            except:
                data.append(int(element, 16))
        return data

    def do_spi_init(self, args):
        try:
            CloudchaserCli.Cloudchaser_drv = CloudchaserDrv()
            CloudchaserCli.Cloudchaser_drv.spi_init(int(args))
            self.silent = 0
            self.printout_sink = sys.stdout
            self.print_args = {'file':self.printout_sink, 'flush':True}
        except Exception as error:
            print('ERROR in spi_init: {}'.format(error), file=self.printout_sink)

    def do_spi_close(self, args):
        CloudchaserCli.Cloudchaser_drv.spi_close()

    def do_spi_reset(self, args):
        CloudchaserCli.Cloudchaser_drv.spi_reset()

    def do_spi_upd(self, args):
        CloudchaserCli.Cloudchaser_drv.spi_upd()

    def do_spi_load_address(self, args):
        try:
            args = args.split()
            CloudchaserCli.Cloudchaser_drv.spi_load_address(int(args[0]), int(args[1]))
        except Exception as error:
            print('ERROR in spi_load_address: {}'.format(error), file=self.printout_sink)

    def do_spi_write(self, args):
        try:
            args = args.split()
            chip_id = self._get_int(args[0])
            args.pop(0)
            address = self._get_int(args[0])
            args.pop(0)
            data = self._get_int(args[0])
            CloudchaserCli.Cloudchaser_drv.spi_write(chip_id, address, data)
        except Exception as error:
            print('ERROR in spi_write: {}'.format(error), file=self.printout_sink)

    def do_spi_read(self, args):
        try:
            args = args.split()
            chip_id = self._get_int(args[0])
            args.pop(0)
            address = self._get_int(args[0])
            value = CloudchaserCli.Cloudchaser_drv.spi_read(chip_id, address)
            if not self.silent:
                print('0x{:04x}'.format(value), file=self.printout_sink)
            return value
        except Exception as error:
            print('ERROR in spi_read: {}'.format(error), file=self.printout_sink)

    def do_spi_write_ex(self, args):
        try:
            args = args.split()
            chip_id = self._get_int(args[0])
            args.pop(0)
            address = self._get_int(args[0])
            args.pop(0)
            data = self._make_data_list(args)
            CloudchaserCli.Cloudchaser_drv.spi_write_ex(chip_id, address, data)
        except Exception as error:
            print('ERROR in spi_write_ex: {}'.format(error), file=self.printout_sink)

    def do_spi_read_ex(self, args):
        try:
            args = args.split()
            chip_id = self._get_int(args[0])
            args.pop(0)
            address = self._get_int(args[0])
            args.pop(0)
            length = self._get_int(args[0])
            res = CloudchaserCli.Cloudchaser_drv.spi_read_ex(chip_id, address, length)
            if not self.silent:
                for n in res:
                    print('0x{:04x} '.format(n), end='', file=self.printout_sink)
                print(file=self.printout_sink)
            return res
        except Exception as error:
            print('ERROR in spi_read_ex: {}'.format(error))

    def do_spi_adc_capture(self, args):
        try:
            args = args.split()
            chip_id = self._get_int(args[0])
            CloudchaserCli.Cloudchaser_drv.spi_adc_capture(chip_id)
        except Exception as error:
            print('ERROR in spi_adc_capture: {}'.format(error), file=self.printout_sink)

    def do_spi_chk(self, args):
        res = None
        try:
            args = args.split()
            chip_id = self._get_int(args[0])
            args.pop(0)
            address = self._get_int(args[0])
            args.pop(0)
            expected_val = self._get_int(args[0])
            actual_val = CloudchaserCli.Cloudchaser_drv.spi_read(chip_id, address)
            if actual_val == expected_val:
                if not self.silent:
                    print('Read from address 0x{:04x} matched 0x{:04x}'.format(address, expected_val), file=self.printout_sink)
                res = 'PASS'
            else:
                if not self.silent:
                    print('Read from address 0x{:04x} did not match! (Expected: 0x{:04x}, Received: 0x{:04x})'.format(address, expected_val, actual_val), file=self.printout_sink)
                res = 'FAIL'
        except Exception as error:
            print('ERROR in spi_chk: {}'.format(error), file=self.printout_sink)

        return res

    def do_spi_chk_ex(self, args):
        res = None
        try:
            args = args.split()
            chip_id = self._get_int(args[0])
            args.pop(0)
            address = self._get_int(args[0])
            args.pop(0)
            length = len(args)
            expected_val = self._make_data_list(args)
            actual_val = CloudchaserCli.Cloudchaser_drv.spi_read_ex(chip_id, address, length)
            if actual_val == expected_val:
                if not self.silent:
                    print('Read {} registers from address 0x{:04x} matched {}'.format(length, address, expected_val), file=self.printout_sink)
                res = 'PASS'
            else:
                if not self.silent:
                    print('Read {} registers from address 0x{:04x} did not match! (Expected: {}, Received: {})'.format(length, address, expected_val, actual_val), file=self.printout_sink)
                res = 'FAIL'
        except Exception as error:
            print('ERROR in spi_chk_ex: {}'.format(error), file=self.printout_sink)

        return res

    def do_spi_clk(self, args):
        try:
            args = args.split()
            n = self._get_int(args[0])
            CloudchaserCli.Cloudchaser_drv.spi_clk(n)
        except Exception as error:
            print('ERROR in spi_clk: {}'.format(error), file=self.printout_sink)

    def do_printout(self, args):
        args = args.split()
        if args[0].upper() == 'OFF':
            self.silent = 1
        elif args[0].upper() == 'ON':
            self.silent = 0
            self.printout_sink = sys.stdout
        elif args[0].upper() == 'F':
            self.silent = 0
            filename = args[1]
            self.log_file = open(filename, 'a')
            self.printout_sink = self.log_file
        self.print_args = {'file':self.printout_sink, 'flush':True}

    def do_quit(self, args):
        return 'stop'

    def do_exit(self, args):
        return 'stop'

    def postcmd(self, stop, line):
        if stop == 'stop':
            return True

    def do_run_script(self, args):
        with open(args, 'r') as f:
            lines = f.readlines()
            res = []
            for line in lines:
                l = line.lstrip().rstrip()
                if l != '':
                    res.append(self.onecmd(l))
        return res

def connect(cli, spi_speed=15000000):
    cli.onecmd('spi_init {}'.format(spi_speed))

def run_scripts(cli, *filenames):
    res = {}
    for filename in filenames:
        res[filename] = cli.onecmd('run_script {}'.format(filename))
    return res

def get_args():
    import argparse
    parser = argparse.ArgumentParser(description='Command line options.')
    parser.add_argument('-s', '--speed', dest='spi_speed', metavar='SPI speed', default=15000000,
                         help='Specify SPI clock frequency in Hz')
    parser.add_argument('-f', '--file', dest='filenames', metavar='Script file name(s)', default=None, nargs='+', type=str,
                         help='Specify script file name(s)')

    return parser.parse_args()

if __name__ == '__main__':
    args = get_args()
    Cloudchaser_cli = CloudchaserCli()
    Cloudchaser_cli.onecmd('spi_init {}'.format(args.spi_speed))
    if args.filenames != None:
        test_result = 'PASS'
        for filename in args.filenames:
            with open(filename, 'r') as f:
                print()
                print('***** Executing {} *****'.format(filename))
                lines = f.readlines()
                for line in lines:
                    l = line.lstrip().rstrip()
                    if l != '':
                        res = Cloudchaser_cli.onecmd(l)
                        if res == 'FAIL':
                            test_result = 'FAIL'
                        if l == 'exit' or l == 'quit':
                            exit(test_result)

    Cloudchaser_cli.cmdloop()






