#!/usr/bin/env python

from pathlib import Path
from argparse import ArgumentParser
from tabulate import tabulate

from .newportxps import NewportXPS

HELP_MESSAGE = """xps: simple interaction with NewportXPS controllers
    xps -h                            shows this message.
    xps [ADDR] status                 print status and configuration for XPS
    xps [ADDR] groups                 print list of groups
    xps [ADDR] reboot                 reboot xps
    xps [ADDR] initialize    [GROUP]  initialize group by name
    xps [ADDR] initialize_all         initialize all group
    xps [ADDR] home          [GROUP]  home group by name
    xps [ADDR] home_all               home all groups
    xps [ADDR] get_system_ini [FILE]  download system.ini to file
    xps [ADDR] put_system_ini [FILE]  upload   system.ini from file
    xps [ADDR] get_stages_ini [FILE]  download stages.ini to file
    xps [ADDR] put_stages_ini [FILE]  upload   stages.ini from file

 ADDR:  name or ip address for the controller
 FILE:  name of file to save or read
 GROUP: name of group to initialize or home
"""

def xps_main():
    parser = ArgumentParser(prog='xps', description='NewportXPS controllers',
                            add_help=False)
    parser.add_argument('-h', '--help', dest='help', action='store_true',
                        default=False, help='show help')
    parser.add_argument('options', nargs='*')
    args = parser.parse_args()

    if args.help or len(args.options) == 0:
        print(HELP_MESSAGE)
        return

    ipaddr = args.options.pop(0)
    command = args.options.pop(0)
    _argu  = ''
    if len(args.options) > 0:
        _argu = args.options.pop(0)

    try:
        this_xps = NewportXPS(ipaddr)
    except XPSException:
        print(f"cannot connect to NewportXPS at {ipaddr=}")
        return
    except Exception:
        print(f"unknown error connecting to NewportXPS at {ipaddr=}")
        return

    if command == 'status':
        print(this_xps.status_report())
    elif command == 'groups':
        headers =('Group Name', 'Positioners', 'Type')
        dat = []
        for gn, gd in this_xps.groups.items():
            dat.append((gn, ', '.join(gd['positioners']), gd['category']))
        print(tabulate(dat, headers))
    elif command == 'initialize_all':
        this_xps.initialize_allgroups()
    elif command == 'initialize':
        if len(_argu) < 1:
            print("xps initialize needs a group name, or use `xps initialize_all`")
            return
        groupname = _argu
        if groupname not in this_xps.groups.keys():
            print(f"xps initialize needs a valid group name, one of {', '.join(this_xps.groups.keys())}")
            return
        this_xps.initialize_group(groupname)
    elif command == 'home_all':
        this_xps.homee_allgroups()
    elif command == 'home':
        if len(_argu) < 1:
            print("xps home needs a group name, or use `xps home_all`")
            return
        groupname = _argu
        if groupname not in this_xps.groups.keys():
            print(f"xps home needs a valid group name, one of {', '.join(this_xps.groups.keys())}")
            return
        this_xps.home_group(groupname)

    elif command == 'reboot':
        print(f"rebooting {ipaddr}")
        this_xps.reboot()

    elif command == 'get_system_ini':
        filename = _argu
        if len(filename) < 1:
            filename = f'system_{ipaddr}.ini'
        this_xps.save_systemini(filename)
        print(f"saved system.ini to {filename}")

    elif command == 'get_stages_ini':
        filename = _argu
        if len(filename) < 1:
            filename = f'stages_{ipaddr}.ini'
        this_xps.save_stagesini(filename)
        print(f"saved stages.ini to {filename}")

    elif command == 'put_system_ini':
        filename = _argu
        if len(filename) < 1:
            print("xps put_system_ini needs system.ini file")
            return
        text = open(filneme, 'r').read()
        this_xps.upload_systemini(text)
        print(f"uploaded text from {filename} as system.ini")

    elif command == 'put_stages_ini':
        filename = _argu
        if len(filename) < 1:
            print("xps put_stages_ini needs stages.ini file")
            return
        text = open(filneme, 'r').read()
        this_xps.upload_stagesini(text)
        print(f"uploaded text from {filename} as stages.ini")



if __name__ == '__main__':
    xps_main()
