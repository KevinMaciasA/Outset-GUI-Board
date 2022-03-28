import os, sys, datetime, time, shutil, zipfile, traceback, urllib2
from subprocess import Popen, PIPE

GUI_MEDIA_LOCAL_DIR = R'C:\GUIMedia'
LOCAL_TEMP_DIR = GUI_MEDIA_LOCAL_DIR + os.sep + "Temp"
TEMP_MEDIA_NAME = LOCAL_TEMP_DIR + os.sep + 'download_temp.zip'
TEMP_UNZIP_NAME = LOCAL_TEMP_DIR + os.sep + 'temp_push'
GUI_BOARD_IP = "10.134.246.252"
MEDIA_MANIFEST_NAME = "MediaVersion.txt"

def do_gui_media_update():
    sys.excepthook = handle_exception
    ensure_temp_dir() 
    ensure_adb_connected() 
    version, url = get_media_required() 
    check_media_already_installed(version)
    download_media(version, url)
    install_media(version)
    print('All done!')


def get_media_required():
    print('Getting media requirements...')
    filename = pull_current_gui_apk()
    if(filename == None):
        return (0, "")
    contents = extract_gui_media_csv(filename)
    lines = contents.split('\n')
    fields = lines[1].split(',')
    version = int(fields[0])
    url = fields[1].strip().replace('"', '')
    print('Media: version=%d, URL=%s' % (version, url))
    return version, url

def ensure_temp_dir():
    if not os.path.isdir(LOCAL_TEMP_DIR):
        print('Creating: %s' % LOCAL_TEMP_DIR)
        os.makedirs(LOCAL_TEMP_DIR)

def ensure_adb_connected():
    print('Connecting to GUI board...')
    hit_device = False

    response = adb('devices').split('\n')

    for one_line in response:
        if not 'List of devices' in one_line:
            if 'device' in one_line:
                hit_device = True
                return ("connected")

    if not hit_device:
        adb('kill-server')
        response = adb('connect %s' % GUI_BOARD_IP)

        if not 'connected to' in response:
            return("unable to connect over adb - is device connected and network set up properly?")

        # Sleep a bit here to let the certificate negotiation happen.
        time.sleep(3)

def pull_current_gui_apk():
    contents = adb('shell pm path sequoia.gui.demo').split('\n')
    apk_name = None
    for one_line in contents:
        if one_line.find('package:') > -1:
            apk_name = one_line.strip()
            apk_name = apk_name[apk_name.find(':') + 1:]
            break

    if not apk_name:
        return None

    output_filename = '%s%sSequoiaGUI.apk' % (LOCAL_TEMP_DIR, os.sep)
    adb('pull %s %s' % (apk_name, output_filename))
    return output_filename

def extract_gui_media_csv(filename):
    zip = zipfile.ZipFile(filename)
    f = zip.open('res/raw/guimedia.csv')
    contents = f.read()
    f.close()
    return contents

def download_media(version, url):
    #version = 8
    target_name = GUI_MEDIA_LOCAL_DIR + os.sep + str(version) + '.zip'
    if os.path.isfile(target_name):
#        if isForced:
        os.remove(target_name)
#        else:
#            return('Already have that media on this computer, skipping download step')

    if os.path.isfile(TEMP_MEDIA_NAME):
        os.remove(TEMP_MEDIA_NAME)

    response = urllib2.urlopen(url)
    total_size = int(response.info().getheader('Content-Length').strip())
    bytes_so_far = 0
    data = []
    out_file = open(TEMP_MEDIA_NAME, "wb") 

    while True:
        chunk = response.read(8192)
        bytes_so_far += len(chunk)

        if not chunk:
            break

        out_file.write(chunk)

        percent = int((float(bytes_so_far) / total_size) * 100)
        #sys.stdout.write('Downloading: %d%%\r' % percent)

    out_file.flush()
    out_file.close()

    # Sanity check it before we accept what it is.
    zip = zipfile.ZipFile(TEMP_MEDIA_NAME)
    ret = zip.testzip()
    zip.close()

    if ret is not None:
        return 1, 'Media download corrupt'

    #rename (source, new) 
    # Looks good, rename it and we're all happy!
    os.rename(TEMP_MEDIA_NAME, target_name)
    return 0, 'Ok'

def check_media_already_installed(version):
    manifest_name = '/sdcard/media/%d/%s' % (version, MEDIA_MANIFEST_NAME)
    contents = adb('shell ls %s' % manifest_name, accept_error_one=True)
    for one_line in contents.split('\n'):
        if one_line.find(MEDIA_MANIFEST_NAME) > -1 and one_line.lower().find("no such file") == -1:
            print('GUI board already has correct media installed, bailing out')
            print('')
            print('(tip: to force media installation anyway, re-run with "force" option: python update_gui_media.com force)')
            return 1
    return 0

def install_media(version):
    target_name = GUI_MEDIA_LOCAL_DIR + os.sep + str(version) + '.zip'
    adb('shell rm -r -f /sdcard/media')            
    adb('shell mkdir /sdcard/media')
    adb('shell mkdir /sdcard/media/temp')
    push_zip_contents(target_name, '/sdcard/media/temp')
    adb('shell mv /sdcard/media/temp /sdcard/media/%d' % version)

def push_zip_contents(src_zip, remote_dir):
    zip = zipfile.ZipFile(src_zip)
    contents = zip.namelist()
    for one_file in contents:
        if one_file.endswith('/'):
            target_dir = remote_dir + '/' + one_file   # Don't use os.sep: we're making a path on the GUI board, not local!
            adb('shell mkdir %s' % target_dir, noisy=False)
        else:
            base_name = one_file[one_file.rfind('/') + 1:]
            dir_name = one_file[0:one_file.rfind('/') + 1]
            target_name = remote_dir + '/' + dir_name + base_name
            push_one_file(zip, one_file, target_name)

    zip.close()

def push_one_file(zip, file_in_zip_name, target_name):
    print("Pushing: %s" % file_in_zip_name)

    # Clean out the last file we unzipped, if there is one.
    if os.path.isfile(TEMP_UNZIP_NAME):
        os.remove(TEMP_UNZIP_NAME)

    # Extract it to temp file:
    in_file = zip.open(file_in_zip_name)
    out_file = open(TEMP_UNZIP_NAME, 'wb')

    while True:
        chunk = in_file.read(8192)

        if not chunk:
            break

        out_file.write(chunk)

    in_file.close()
    out_file.close()

    # Push it over to board.
    adb('push %s %s' % (TEMP_UNZIP_NAME, target_name), noisy=False)

    # Remove temp file.
    os.remove(TEMP_UNZIP_NAME)


###########################################################################################################################            

def adb(command, wait=True, accept_error_one=False, noisy=True):
    command = 'adb ' + command

    if noisy:
        print('-- %s' % command)

    process = Popen(command.split(' '), stdout=PIPE, stderr=PIPE)

    if wait:
        (output, err) = process.communicate()
        exit_code = process.wait()

        if exit_code > 0 and not (exit_code == 1 and accept_error_one):
            return('unexpected exit code %d from command: %s' % (exit_code, command))
            print('output: [%s]' % output)
            print('err: [%s]' % err)

        return output
    else:
        return ""

def die(what):
    print('*** %s' % what)        
    stack_items = traceback.format_stack()
    # Skip the last one, since it'll just show this dumb loop.
    for i in range(0, len(stack_items) - 1):
        print(stack_items[i].strip())
    sys.exit(1)

def handle_exception(exc_type, exc_value, exc_traceback):
    print('*** Unhandled exception!')
    print('')
    print("".join(traceback.format_exception(exc_type, exc_value, exc_traceback)))
    sys.exit(1)

if __name__ == '__main__':
    do_gui_media_update(force_mode=False)