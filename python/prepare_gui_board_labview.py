import SimpleHTTPServer, SocketServer, sys, threading, socket, time
from subprocess import Popen, PIPE

# Stuff that might change.

PROBE_UDP_PORT = 7777
TEMP_HTTP_PORT = 8000
TELNET_PORT = 23
MY_IP_ADDR = "10.134.246.249"
BOARD_ADDRESS = "10.134.246.252"

# Stuff that shouldn't change depending on config.

ROOT_PROMPT = "root@freescale "
UPDATE_IMAGE_FILE = "gui_os_install.tar.bz2"

def do_update_process():
    # Wait to hear board boot.
    # udp_probe_listen()

    # Wait for board to boot. 

    # Paw at telnet until it's up, retrying while board boots.
    tries_left = 20
    while tries_left > 0:
        tries_left = tries_left - 1
        try:
            telnet_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            telnet_socket.settimeout(3)
            telnet_socket.connect((BOARD_ADDRESS, TELNET_PORT))
            break
        except socket.timeout as e:
            print('Connect failed, tries left = %d...' % tries_left)

    if tries_left == 0:
        print("Unable to connect to board")
        sys.exit(1)

    # Now the mayhem begins: pull the zip and run the scripts to flash to native storage.
    print('Connected, logging in')
    telnet_socket.settimeout(None)
    telnet_socket.send("\n")
    time.sleep(1)
    telnet_socket.send("root\n")
    response = read_til_text(telnet_socket, ROOT_PROMPT)
    telnet_socket.send("cd /hdplus\n")
    response = read_til_text(telnet_socket, ROOT_PROMPT)

    # Verify the board is really a GUI board.  If it's an MI board,
    # then it will have an rtl8192cu and that will be visible in dmesg.
    telnet_socket.send('dmesg | grep rtl8192cu' + '\n')
    response = read_til_text(telnet_socket, ROOT_PROMPT)
    if 'registered new interface driver rtl8192cu' in response:
        print('\n!!! rtl8192cu wifi USB adapter detected on board - is this really a GUI board?\n\nStopping flash process.')
        telnet_socket.send('reboot\n')
        time.sleep(5)
        sys.exit(1)

    # Ok, start up the HTTP server now that we know the board is a good candidate.
    thread = threading.Thread(target=web_server_thread)
    thread.start()
    time.sleep(2)

    print('Downloading image, may take a few minutes...')
    get_command = 'wget -O /hdplus/%s http://%s:%d/%s' % (UPDATE_IMAGE_FILE, MY_IP_ADDR, TEMP_HTTP_PORT, UPDATE_IMAGE_FILE)
    telnet_socket.send(get_command + "\n")
    response = read_til_text(telnet_socket, ROOT_PROMPT)
    print('Transfer done, response:\n%s' % response)

    print('\nExtracting image..')
    telnet_socket.send('tar -xf %s\n' % UPDATE_IMAGE_FILE)
    response = read_til_text(telnet_socket, ROOT_PROMPT)
    print('Extraction done\n')

    telnet_socket.send("cd scripts\n")
    response = read_til_text(telnet_socket, ROOT_PROMPT)

    print('\nFlashing image to storage, this may take a few minutes; do not panic.')
    telnet_socket.send('./mksd-android.sh /dev/mmcblk0\n')
    response = read_til_text(telnet_socket, ROOT_PROMPT)
    print('------------------------------------\n%s\n------------------------------------' % response)

    # Reboot the device, it will finish up everything it needs to do on its own.
    print('All done, rebooting!')
    print('')
    print('Watch display and make sure Tablo logo appears after a few minutes.')
    telnet_socket.send('reboot\n')
    time.sleep(5)

# Listen on our special UDP port until we hear a probe
# from a GUI board.  If we get it, send back the "Program"
# command to kick it into Linux and continue script
# execution.

def udp_probe_listen():
    address = ('', PROBE_UDP_PORT)
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind(address)

    recv_data, addr = server_socket.recvfrom(2048)
    print(recv_data, addr)

    while True:
        print('Listening for UDP probe from board, reboot it now')
        recv_data, addr = server_socket.recvfrom(2048)
        print('Received packet, length: %d' % len(recv_data))
        if len(recv_data) == 1 and recv_data == "O" and addr[0] == BOARD_ADDRESS:
            print('Sending response to probe, board should boot into programming mode')
            server_socket.sendto("Program", addr)
            break

# Slurp in the output of this socket until we see something that
# means we should stop.

def read_til_text(socket, match_text):
    response = ""
    while True:
        chunk = socket.recv(1)

        if chunk == '':
            print('Unexpected socket read failure, this is bad')
            sys.exit(1)

        response = response + chunk
        if response.find(match_text) > -1:
            return response

# Simple thread to hang a tiny HTTP server long enough to handle
# a single request from the board to pull the OS image down.

def web_server_thread():
    Handler = SimpleHTTPServer.SimpleHTTPRequestHandler
    httpd = SocketServer.TCPServer(("", TEMP_HTTP_PORT), Handler)
    httpd.handle_request()

def get_process_output(command, wait=True, no_print=False, die_on_failed=True):
    if die_on_failed:
        print('-- %s' % command)

    process = Popen(command.split(' '), stdout=PIPE, stderr=PIPE)

    if wait:
        (output, err) = process.communicate()
        exit_code = process.wait()

        if die_on_failed and not exit_code == 0:
            print('unexpected exit code %d from command: %s' % (exit_code, command))
            print('output: [%s]' % output)
            print('err: [%s]' % err)
            sys.exit(0)

        return output
    else:
        return ""    

if __name__ == '__main__':
    do_update_process()


