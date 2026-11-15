"""Send private server settings to the board over USB without echoing secrets."""
import argparse
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM3')
    parser.add_argument('--restore-official', action='store_true')
    args = parser.parse_args()
    payload = {'cmd':'server','reset':True} if args.restore_official else json.loads((ROOT/'private/provision.json').read_text())
    if not args.restore_official:
        payload['utc'] = int(time.time())
    import serial
    with serial.Serial(args.port,115200,timeout=.25,write_timeout=3) as port:
        time.sleep(2)
        port.reset_input_buffer()
        data = (json.dumps(payload)+'\n').encode()
        for offset in range(0,len(data),64):
            port.write(data[offset:offset+64])
            port.flush()
            time.sleep(.08)
        end=time.monotonic()+25
        acknowledged=False
        while time.monotonic()<end:
            line=port.readline().decode(errors='replace').strip()
            if 'VOICE ' in line and not any(word in line.lower() for word in ['token','password','authorization']):
                print(line,flush=True)
            if 'local server settings saved' in line or 'official service restored' in line:
                acknowledged=True
        if not acknowledged:
            raise RuntimeError('Board did not acknowledge configuration')
        print('Configuration acknowledged; USB monitor closed.')

if __name__=='__main__':
    main()
