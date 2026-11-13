"""Windows RFCOMM transport for the owner's MW-light. Uses the captured iLight SPP protocol."""
import ctypes
import select
import socket
import time
import os

class BluetoothAddress(ctypes.Structure):
    _pack_=1
    _fields_=[('family',ctypes.c_ushort),('address',ctypes.c_ulonglong),('service',ctypes.c_ubyte*16),('port',ctypes.c_ulong)]

def connect(timeout=20):
    dll=ctypes.WinDLL('Ws2_32.dll')
    dll.connect.argtypes=[ctypes.c_size_t,ctypes.c_void_p,ctypes.c_int]
    sock=socket.socket(32,1,3)
    sock.setblocking(False)
    addr=BluetoothAddress()
    addr.family=32
    address=os.environ.get('MW_LIGHT_ADDRESS', '').replace(':','').replace('-','')
    if len(address)!=12 or any(x not in '0123456789abcdefABCDEF' for x in address):
        sock.close()
        raise ValueError('Set MW_LIGHT_ADDRESS to your lamp Bluetooth Classic address')
    addr.address=int(address,16)
    addr.port=2
    try:
        result=dll.connect(sock.fileno(),ctypes.byref(addr),ctypes.sizeof(addr))
        error=dll.WSAGetLastError() if result else 0
        if error==10035:
            _,ready,bad=select.select([],[sock],[sock],timeout)
            error=sock.getsockopt(socket.SOL_SOCKET,socket.SO_ERROR) if ready or bad else 10060
        if error: raise OSError(error,'MW-light RFCOMM connection failed')
        sock.settimeout(5)
        return sock
    except BaseException:
        sock.close()
        raise

class Lamp:
    def __enter__(self):
        self.socket=connect()
        self.buffer=b''
        self.socket.sendall(b'01234567')
        self.exchange(bytes.fromhex('01fe0000510210000000008000000080'),0x02)
        return self
    def __exit__(self,*args): self.socket.close()
    def exchange(self,packet,command):
        self.socket.sendall(packet)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            while len(self.buffer)>=16:
                start=self.buffer.find(b'\x01\xfe\x00\x00')
                if start<0: self.buffer=b'';break
                self.buffer=self.buffer[start:]
                if len(self.buffer)<16:break
                size=int.from_bytes(self.buffer[6:8],'little')
                if not 16<=size<=4096:raise ValueError('Invalid lamp response length')
                if len(self.buffer)<size:break
                frame,self.buffer=self.buffer[:size],self.buffer[size:]
                if frame[4]==0x41 and frame[5]==command:return frame
            chunk=self.socket.recv(4096)
            if not chunk: raise ConnectionError('Lamp disconnected')
            self.buffer+=chunk
        raise TimeoutError('No matching lamp response')
    def is_on(self):
        frame=self.exchange(bytes.fromhex('01fe00005181180000000000000000000d0801020200000e'),0x81)
        body=frame[16:]
        if body[:5]!=bytes.fromhex('0d08010202') or body[5] not in (1,2):
            raise ValueError('Unrecognized white light state: '+frame.hex())
        return body[5]==1
    def power(self,on):
        value='01' if on else '02'
        frame=self.exchange(bytes.fromhex('01fe00005181180000000000000000000d07010301'+value+'0e00'),0x81)
        if frame[16:22]!=bytes.fromhex('0d08010401'+value):
            raise ValueError('Unexpected power acknowledgment: '+frame.hex())
    def toggle(self):
        on=not self.is_on()
        self.power(on)
        return on

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['status','on','off','toggle'])
    a=p.parse_args()
    with Lamp() as lamp:
        if a.action=='status':print('ON' if lamp.is_on() else 'OFF')
        elif a.action=='toggle':print('ON' if lamp.toggle() else 'OFF')
        else:lamp.power(a.action=='on');print(a.action.upper())
