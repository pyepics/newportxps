 #!/usr/bin/env python

import posixpath
import sys
import time
import socket
from copy import deepcopy
from configparser import  ConfigParser
import numpy as np

from .debugtime import debugtime
from .utils import clean_text
from .XPS_C8_drivers import XPS, XPSException
from .ftp_wrapper import SFTPWrapper, FTPWrapper

IDLE, ARMING, ARMED, RUNNING, COMPLETE, WRITING, READING = \
      'IDLE', 'ARMING', 'ARMED', 'RUNNING', 'COMPLETE', 'WRITING', 'READING'

def withConnectedXPS(fcn):
    """decorator to ensure a NewportXPS is connected before a method is called"""
    def wrapper(self, *args, **kwargs):
        if self._sid is None or len(self.groups) < 1 or len(self.stages) < 1:
            self.connect()
        return fcn(self, *args, **kwargs)
    wrapper.__doc__ = fcn.__doc__
    wrapper.__name__ = fcn.__name__
    wrapper.__dict__.update(fcn.__dict__)

    return wrapper


class NewportXPS:
    gather_header = '# XPS Gathering Data\n#--------------'
    def __init__(self, host, group=None,
                 username='Administrator', password='Administrator',
                 port=5001, timeout=10, extra_triggers=0,
                 outputs=('CurrentPosition', 'SetpointPosition')):

        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self.extra_triggers = extra_triggers

        self.gather_outputs = tuple(outputs)
        self.trajectories = {}
        self.traj_state = IDLE
        self.traj_group = None
        self.traj_file = None
        self.traj_positioners = None

        self.nsegments = -1
        self.stages = {}
        self.groups = {}
        self.firmware_version = None

        self.ftpconn = None
        self.ftpargs = dict(host=self.host,
                            username=self.username,
                            password=self.password)
        self._sid = None
        self._xps = XPS()
        self.connect()
        if group is not None:
            self.set_trajectory_group(group)

    def __repr__(self):
        return f"NewportXPS(host='{self.host}', port={self.port})"

    @withConnectedXPS
    def status_report(self):
        """return printable status report"""
        err, uptime = self._xps.ElapsedTimeGet(self._sid)
        self.check_error(err, msg="Elapsed Time")
        boottime = time.time() - uptime
        hostn = socket.getfqdn(self.host)
        out = [f"# XPS host:         {self.host} ({hostn})",
               f"# Firmware:         {self.firmware_version}",
               f"# Current Time:     {time.ctime()}",
               f"# Last Reboot:      {time.ctime(boottime)}",
               f"# Trajectory Group: {self.traj_group}",
               ]

        out.append("# Groups and Stages")
        hstat = self.get_hardware_status()
        perrs = self.get_positioner_errors()

        for groupname, status in self.get_group_status().items():
            this = self.groups[groupname]
            out.append(f"{groupname} ({this['category']}), Status: {status}")
            for pos in this['positioners']:
                stagename = f"{groupname}.{pos}"
                stage = self.stages[stagename]
                out.extend([f"# {stagename} ({stage['stagetype']})",
                            f"      Hardware Status: {hstat[stagename]}",
                            f"      Positioner Errors: {perrs[stagename]}"])
        return "\n".join(out)


    def connect(self):
        self._sid = self._xps.TCP_ConnectToServer(self.host,
                                                  self.port, self.timeout)
        try:
            self._xps.Login(self._sid, self.username, self.password)
        except:
            raise XPSException(f'Login failed for {self.host}')

        err, val = self._xps.FirmwareVersionGet(self._sid)
        self.firmware_version = val
        self.ftphome = ''

        if any([m in self.firmware_version for m in ['XPS-D', 'HXP-D']]):
            err, val = self._xps.Send(self._sid, 'InstallerVersionGet(char *)')
            self.firmware_version = val
            self.ftpconn = SFTPWrapper(**self.ftpargs)
        else:
            self.ftpconn = FTPWrapper(**self.ftpargs)
            if 'XPS-C' in self.firmware_version:
                self.ftphome = '/Admin'
        self.read_systemini()


    def check_error(self, err, msg='', with_raise=True):
        if err != 0:
            err = f"{err}"
            desc = self._xps.errorcodes.get(err, 'unknown error')
            print(f"XPSError: message={msg}, error={err}, description={desc}")
            if with_raise:
                raise XPSException(f"{msg} {desc} [Error {err}]")

    def save_systemini(self, fname='system.ini'):
        """
        save system.ini to disk
        Parameters:
        fname  (string): name of file to save to ['system.ini']
        """
        self.ftpconn.connect(**self.ftpargs)
        self.ftpconn.cwd(posixpath.join(self.ftphome, 'Config'))
        self.ftpconn.save('system.ini', fname)
        self.ftpconn.close()

    def save_stagesini(self, fname='stages.ini'):
        """save stages.ini to disk

        Parameters:
           fname  (string): name of file to save to ['stages.ini']
        """
        self.ftpconn.connect(**self.ftpargs)
        self.ftpconn.cwd(posixpath.join(self.ftphome, 'Config'))
        self.ftpconn.save('stages.ini', fname)
        self.ftpconn.close()

    def read_systemini(self):
        """read group info from system.ini
        this is part of the connection process
        """
        self.ftpconn.connect(**self.ftpargs)
        self.ftpconn.cwd(posixpath.join(self.ftphome, 'Config'))
        lines = self.ftpconn.getlines('system.ini')
        self.ftpconn.close()
        initext = '\n'.join([line.strip() for line in lines])

        pvtgroups = []
        self.stages= {}
        self.groups = {}
        sconf = ConfigParser()
        sconf.read_string(initext)

        # read and populate lists of groups first
        for gtype, glist in sconf.items('GROUPS'): # ].items():
            if len(glist) > 0:
                for gname in glist.split(','):
                    gname = gname.strip()
                    self.groups[gname] = {}
                    self.groups[gname]['category'] = gtype.strip()
                    self.groups[gname]['positioners'] = []
                    if gtype.lower().startswith('multiple'):
                        pvtgroups.append(gname)

        for section in sconf.sections():
            if section in ('DEFAULT', 'GENERAL', 'GROUPS'):
                continue
            items = sconf.options(section)
            if section in self.groups:  # this is a Group Section!
                poslist = sconf.get(section, 'positionerinuse')
                posnames = [a.strip() for a in poslist.split(',')]
                self.groups[section]['positioners'] = posnames
            elif 'plugnumber' in items: # this is a stage
                self.stages[section] = {'stagetype': sconf.get(section, 'stagename')}

        if len(pvtgroups) == 1:
            self.set_trajectory_group(pvtgroups[0])

        for sname in self.stages:
            ret = self._xps.PositionerMaximumVelocityAndAccelerationGet(self._sid, sname)
            try:
                self.stages[sname]['max_velo']  = ret[1]
                self.stages[sname]['max_accel'] = ret[2]/3.0
            except:
                print(f"could not set max velo/accel for {name}")
            ret = self._xps.PositionerUserTravelLimitsGet(self._sid, sname)
            try:
                self.stages[sname]['low_limit']  = ret[1]
                self.stages[sname]['high_limit'] = ret[2]
            except:
                print(f"could not set limits for {sname}")

        return self.groups

    def download_trajectory(self, filename):
        """download text of trajectory file

        Arguments:
        ----------
           filename (str):  name of trajectory file
           text  (str):   full text of trajectory file
        """
        self.ftpconn.connect(**self.ftpargs)
        self.ftpconn.cwd(posixpath.join(self.ftphome, 'Public', 'Trajectories'))
        self.ftpconn.save(filename, filename)
        self.ftpconn.close()

    def upload_trajectory(self, filename,  text):
        """upload text of trajectory file

        Arguments:
        ----------
           filename (str):  name of trajectory file
           text  (str):   full text of trajectory file
        """
        self.ftpconn.connect(**self.ftpargs)
        self.ftpconn.cwd(posixpath.join(self.ftphome, 'Public', 'Trajectories'))
        self.ftpconn.put(clean_text(text), filename)
        self.ftpconn.close()

    def list_scripts(self):
        """list all existent scripts files
        """
        remotefiles = ""
        self.ftpconn.connect(**self.ftpargs)
        self.ftpconn.cwd(posixpath.join(self.ftphome, 'Public', 'Scripts'))
        remotefiles = self.ftpconn.list()
        self.ftpconn.close()

        return remotefiles

    def read_script(self, filename):
        """read script content

        Arguments:
        ----------
           filename (str):  name of script file
        """
        filecontent = ""
        self.ftpconn.connect(**self.ftpargs)
        self.ftpconn.cwd(posixpath.join(self.ftphome, 'Public', 'Scripts'))
        filecontent = self.ftpconn.getlines(filename)
        self.ftpconn.close()

        return filecontent

    def download_script(self, filename):
        """download script file

        Arguments:
        ----------
           filename (str):  name of script file
        """
        self.ftpconn.connect(**self.ftpargs)
        self.ftpconn.cwd(posixpath.join(self.ftphome, 'Public', 'Scripts'))
        self.ftpconn.save(filename, filename)
        self.ftpconn.close()

    def upload_script(self, filename, text):
        """upload script file

        Arguments:
        ----------
           filename (str):  name of script file
           text  (str):   full text of script file
        """
        self.ftpconn.connect(**self.ftpargs)
        self.ftpconn.cwd(posixpath.join(self.ftphome, 'Public', 'Scripts'))
        self.ftpconn.put(clean_text(text), filename)
        self.ftpconn.close()

    def delete_script(self, filename):
        """delete script file

        Arguments:
        ----------
           filename (str):  name of script file
        """
        self.ftpconn.connect(**self.ftpargs)
        self.ftpconn.cwd(posixpath.join(self.ftphome, 'Public', 'Scripts'))
        self.ftpconn.delete(filename)
        self.ftpconn.close()

    def upload_systemini(self, text):
        """upload text of system.ini

        Arguments:
        ----------
           text  (str):   full text of system.ini
        """
        self.ftpconn.connect(**self.ftpargs)
        self.ftpconn.cwd(posixpath.join(self.ftphome, 'Config'))
        self.ftpconn.put(clean_text(text), 'system.ini')
        self.ftpconn.close()

    def upload_stagesini(self, text):
        """upload text of stages.ini

        Arguments:
        ----------
           text  (str):   full text of stages.ini

        Notes:
        ------
          you may have to read the stages.ini file with:
          >>> fh = open('mystages.ini', 'r', encoding='ISO8859')
          >>> text = fh.read()
          >>> xps.upload_stageini(text)

        """
        self.ftpconn.connect(**self.ftpargs)
        self.ftpconn.cwd(posixpath.join(self.ftphome, 'Config'))
        self.ftpconn.put(clean_text(text), 'stages.ini')
        self.ftpconn.close()

    @withConnectedXPS
    def set_tuning(self, stage, kp=None, ki=None, kd=None, ks=None,
                   inttime=None, dfilter=None, closedloopstatus=1,
                   gkp=None, gki=None, gkd=None, kform=None, ffgain=None):
        """set tuning parameters for a stage:
        closedloopstatus, kp, ki, kd, ks, inttime, dfilter,
        gkp, gki, gkd, kform, ffgain
        """
        if stage not in self.stages:
            print(f"Stage '{stage}' not found: ")
            return
        params = self._xps.PositionerCorrectorPIDFFVelocityGet(self._sid, stage)
        if params[0] != 0 or len(params) != 13:
            print(f"error getting tuning parameters for {stage}")
            return

        params = params[1:]
        params[0] = closedloopstatus
        if kp is not None:
            params[1] = kp
        if ki is not None:
            params[2] = ki
        if kd is not None:
            params[3] = kd
        if ks is not None:
            params[4] = ks
        if inttime is not None:
            params[5] = inttime
        if dfilter is not None:
            params[6] = dfilter
        if gkp is not None:
            params[7] = gkp
        if gki is not None:
            params[8] = gki
        if gkd is not None:
            params[9] = gkd
        if kform is not None:
            params[10] = kform
        if ffgain is not None:
            params[11] = ffgain
        self._xps.PositionerCorrectorPIDFFVelocitySet(self._sid, stage, *params)

    @withConnectedXPS
    def get_tuning(self, stage):
        """get tuning parameters for a stage:
        closedloopstatus, kp, ki, kd, ks, inttime, dfilter,
        gkp, gki, gkd, kform, ffgain
        """
        if stage not in self.stages:
            print(f"Stage '{stage}' not found: ")
            return
        params = self._xps.PositionerCorrectorPIDFFVelocityGet(self._sid, stage)
        if params[0] != 0 or len(params) != 13:
            print(f"error getting tuning parameters for {stage}")
            return

        params = params[1:]
        out = {}
        for i, name in enumerate(('closedloopstatus', 'kp', 'ki', 'kd', 'ks',
                                  'inttime', 'dfilter', 'gkp', 'gki', 'gkd',
                                  'kform', 'ffgain')):
            out[name] = params[i]
        return(out)

    @withConnectedXPS
    def set_trajectory_group(self, group, reenable=False):
        """set group name for upcoming trajectories"""
        valid = False
        if group in self.groups:
            if self.groups[group]['category'].lower().startswith('multiple'):
                valid = True

        if not valid:
            pvtgroups = []
            for gname, group in self.groups.items():
                if group['category'].lower().startswith('multiple'):
                    pvtgroups.append(gname)
            pvtgroups = ', '.join(pvtgroups)
            msg = f"'{group}' cannot be a trajectory group, must be one of {pvtgroups}"
            raise XPSException(msg)

        self.traj_group = group
        self.traj_positioners = self.groups[group]['positioners']

        if reenable:
            try:
                self.disable_group(self.traj_group)
            except XPSException:
                pass

            time.sleep(0.1)
            try:
                self.enable_group(self.traj_group)
            except XPSException:
                print(f"Warning: could not enable trajectory group '{self.traj_group}'")
                return

        for i in range(64):
            self._xps.EventExtendedRemove(self._sid, i)

        # build template for linear trajectory file:
        trajline1 = ['%(ramptime)f']
        trajline2 = ['%(scantime)f']
        trajline3 = ['%(ramptime)f']
        for p in self.traj_positioners:
            trajline1.append('%%(%s_ramp)f' % p)
            trajline1.append('%%(%s_velo)f' % p)
            trajline2.append('%%(%s_dist)f' % p)
            trajline2.append('%%(%s_velo)f' % p)
            trajline3.append('%%(%s_ramp)f' % p)
            trajline3.append('%8.6f' % 0.0)
        trajline1 = (','.join(trajline1)).strip()
        trajline2 = (','.join(trajline2)).strip()
        trajline3 = (','.join(trajline3)).strip()
        self.linear_template = '\n'.join(['', trajline1, trajline2, trajline3])
        self.linear_template = '\n'.join(['', trajline1, trajline2, trajline3, ''])


    @withConnectedXPS
    def _group_act(self, method, group=None, action='doing something',
                   with_raise=True):
        """wrapper for many group actions"""
        method = getattr(self._xps, method)
        if group is None:
            for group in self.groups:
                err, ret = method(self._sid, group)
                self.check_error(err, msg=f"{action} group '{group}'",
                                 with_raise=with_raise)
        elif group in self.groups:
            err, ret = method(self._sid, group)
            self.check_error(err, msg=f"%{action} group '{group}'",
                             with_raise=with_raise)
        else:
            raise ValueError("Group '{group}' not found")

    def kill_group(self, group=None):
        """
        initialize groups, optionally homing each.

        Parameters:
            with_encoder (bool): whethter to initialize with encoder [True]
            home (bool): whether to home all groups [False]
        """

        method = 'GroupKill'
        self._group_act(method, group=group, action='killing')

    def initialize_allgroups(self, with_encoder=True, home=False):
        """
        initialize all groups, no homing
        """
        for g in self.groups:
            try:
                self.initialize_group(group=g)
            except XPSException:
                print(f"Warning: could not initialize '{g}' (already initialized?)")


    def home_allgroups(self, with_encoder=True, home=False):
        """
        home all groups
        """
        for g in self.groups:
            self.home_group(group=g)


    def initialize_group(self, group=None, with_encoder=True, home=False,
                         with_raise=True):
        """
        initialize groups, optionally homing each.

        Parameters:
            with_encoder (bool): whethter to initialize with encoder [True]
            home (bool): whether to home all groups [False]
        """
        method = 'GroupInitialize'
        if with_encoder:
            method  = 'GroupInitializeWithEncoderCalibration'
        self._group_act(method, group=group, action='initializing',
                        with_raise=with_raise)
        if home:
            self.home_group(group=group, with_raise=with_raise)

    def home_group(self, group=None, with_raise=True):
        """
        home group

        Parameters:
            group (None or string): name of group to home [None]

        Notes:
            if group is `None`, all groups will be homed.
        """
        self._group_act('GroupHomeSearch', group=group, action='homing',
                        with_raise=with_raise)

    def enable_group(self, group=None):
        """enable group

        Parameters:
            group (None or string): name of group to enable [None]

        Notes:
            if group is `None`, all groups will be enabled.
        """
        self._group_act('GroupMotionEnable', group=group, action='enabling')


    def disable_group(self, group=None):
        """disable group

        Parameters:
            group (None or string): name of group to enable [None]

        Notes:
            if group is `None`, all groups will be enabled.
        """
        self._group_act('GroupMotionDisable', group=group, action='disabling')

    @withConnectedXPS
    def get_group_status(self):
        """
        get dictionary of status for each group
        """
        out = {}
        for group in self.groups:
            err, stat = self._xps.GroupStatusGet(self._sid, group)
            self.check_error(err, msg=f"GroupStatus '{group}'")

            err, val = self._xps.GroupStatusStringGet(self._sid, stat)
            self.check_error(err, msg=f"GroupStatusString '{stat}'")

            out[group] = val
        return out

    @withConnectedXPS
    def get_hardware_status(self):
        """
        get dictionary of hardware status for each stage
        """
        out = {}
        for stage in self.stages:
            if stage in ('', None):
                continue
            err, stat = self._xps.PositionerHardwareStatusGet(self._sid, stage)
            self.check_error(err, msg=f"Pos HardwareStatus '{stage}'")

            err, val = self._xps.PositionerHardwareStatusStringGet(self._sid, stat)
            self.check_error(err, msg=f"Pos HardwareStatusString '{stat}'")
            out[stage] = val
        return out

    @withConnectedXPS
    def get_positioner_errors(self):
        """
        get dictionary of positioner errors for each stage
        """
        out = {}
        for stage in self.stages:
            if stage in ('', None):
                continue
            err, stat = self._xps.PositionerErrorGet(self._sid, stage)
            self.check_error(err, msg=f"Pos Error '{stage}'")

            err, val = self._xps.PositionerErrorStringGet(self._sid, stat)
            self.check_error(err, msg=f"Pos ErrorString '{stat}'")

            if len(val) < 1:
                val = 'OK'
            out[stage] = val
        return out

    @withConnectedXPS
    def set_velocity(self, stage, velo, accl=None,
                    min_jerktime=None, max_jerktime=None):
        """
        set velocity for stage
        """
        if stage not in self.stages:
            raise XPSException(f"Stage '{stage}' not found")

        ret, v_cur, a_cur, jt0_cur, jt1_cur = \
             self._xps.PositionerSGammaParametersGet(self._sid, stage)
        if accl is None:
            accl = a_cur
        if min_jerktime is None:
            min_jerktime = jt0_cur
        if max_jerktime is None:
            max_jerktime = jt1_cur
        self._xps.PositionerSGammaParametersSet(self._sid, stage, velo, accl,
                                                min_jerktime, max_jerktime)

    @withConnectedXPS
    def abort_group(self, group=None):
        """abort group move"""
        if group is None or group not in self.groups:
            group = self.traj_group
        if group is None:
            print("Do have a group to move")
            return
        ret = self._xps.GroupMoveAbort(self._sid, group)
        print('abort group ', group, ret)


    @withConnectedXPS
    def move_group(self, group=None, **kws):
        """move group to supplied position
        """
        if group is None or group not in self.groups:
            group = self.traj_group
        if group is None:
            print("Do have a group to move")
            return
        posnames = [p.lower() for p in self.groups[group]['positioners']]
        ret = self._xps.GroupPositionCurrentGet(self._sid, group, len(posnames))

        kwargs = {}
        for k, v in kws.items():
            kwargs[k.lower()] = v

        vals = []
        for i, p in enumerate(posnames):
            if p in kwargs:
                vals.append(kwargs[p])
            else:
                vals.append(ret[i+1])
        self._xps.GroupMoveAbsolute(self._sid, group, vals)

    @withConnectedXPS
    def execute_script(self, script, task, arguments):
        """
        Execute a TCL script

        Parameters:
           script (string): name of script file
           task (string): task name to be identified
           arguments (string): script arguments
        """
        self._xps.TCLScriptExecute(self._sid, script, task, arguments)

    @withConnectedXPS
    def move_stage(self, stage, value, relative=False):
        """
        move stage to position, optionally relative

        Parameters:
           stage (string): name of stage -- must be in self.stages
           value (float): target position
           relative (bool): whether move is relative [False]
        """
        if stage not in self.stages:
            raise XPSException(f"Stage '{stage}' not found")

        move = self._xps.GroupMoveAbsolute
        if relative:
            move = self._xps.GroupMoveRelative

        err, ret = move(self._sid, stage, [value])
        self.check_error(err, msg=f"Moving stage '{stage}'")
        return ret

    @withConnectedXPS
    def get_stage_position(self, stage):
        """
        return current stage position

        Parameters:
           stage (string): name of stage -- must be in self.stages
        """
        if stage not in self.stages:
            raise XPSException(f"Stage '{stage}' not found")

        err, val = self._xps.GroupPositionCurrentGet(self._sid, stage, 1)
        self.check_error(err, msg=f"Get Stage Position '{stage}'")
        return val

    read_stage_position = get_stage_position

    @withConnectedXPS
    def reboot(self, reconnect=True, timeout=120.0):
        """
        reboot XPS, optionally waiting to reconnect

        Parameters:
            reconnect (bool): whether to wait for reconnection [True]
            timeout (float): how long to wait before giving up, in seconds [60]
        """
        self.ftpconn.close()
        self._xps.CloseAllOtherSockets(self._sid)
        self._xps.Reboot(self._sid)
        self._sid = -1
        self.groups = self.stages = self.stagetypes = None
        time.sleep(5.0)
        if reconnect:
            maxtime = time.time() + timeout
            while self._sid < 0:
                time.sleep(5.0)
                try:
                    self._sid = self._xps.TCP_ConnectToServer(self.host,
                                                              self.port,
                                                              self.timeout)
                except:
                    print("Connection Failed ", time.ctime(), sys.exc_info())

                if time.time() > maxtime:
                    break
            if self._sid >=0:
                self.connect()
            else:
                print("Could not reconnect to XPS.")


    @withConnectedXPS
    def define_line_trajectories(self, axis, group=None, pixeltime=0.01,
                                 scantime=None, start=0, stop=1, step=0.001,
                                 accel=None, upload=True, verbose=False):
        """defines 'forward' and 'backward' trajectories for a simple
        single element line scan using PVT Mode
        """
        if group is not None:
            self.set_trajectory_group(group)

        if self.traj_group is None:
            raise XPSException("No trajectory group defined")

        for axname in (axis, axis.upper(), axis.lower(), axis.title()):
            stage = f"{self.traj_group}.{axname}"
            if stage in self.stages:
                break

        # print(" Stage ", stage,  self.stages[stage])
        max_velo  = 0.75*self.stages[stage]['max_velo']
        max_accel = 0.5*self.stages[stage]['max_accel']

        if accel is None:
            accel = max_accel
        accel = min(accel, max_accel)

        scandir  = 1.0
        if start > stop:
            scandir = -1.0
        step = scandir*abs(step)

        npulses  = int((abs(stop - start) + abs(step)*1.1) / abs(step))
        if pixeltime is None and scantime is not None:
            scantime = float(abs(scantime))
            pixeltime= scantime / (npulses-1)
        scantime = pixeltime*npulses

        distance = (abs(stop - start) + abs(step))*1.0
        velocity = min(distance/scantime, max_velo)

        ramptime = max(2.e-5, abs(velocity/accel))
        rampdist = velocity*ramptime
        offset   = step/2.0 + scandir*rampdist

        trajbase = {'axes': [axis],
                    'type': 'line',
                    'pixeltime': pixeltime, 'uploaded': False,
                    'npulses': npulses+1, 'nsegments': 3}

        self.trajectories['foreward'] = {'start': [start-offset],
                                         'stop':  [stop +offset]}
        self.trajectories['foreward'].update(trajbase)

        self.trajectories['backward'] = {'start': [stop +offset],
                                         'stop':  [start-offset]}
        self.trajectories['backward'].update(trajbase)

        base = {'start': start, 'stop': stop, 'step': step,
                'velo': velocity, 'ramp': rampdist, 'dist': distance}
        fore = {'ramptime': ramptime, 'scantime': scantime}
        for attr in base:
            for ax in self.traj_positioners:
                val = 0.0
                if ax == axis:
                    val = base[attr]
                fore[f"{ax}_{attr}"] = val

        back = fore.copy()
        back[f"{axis}_start"] = fore[f"{axis}_stop"]
        back[f"{axis}_stop"]  = fore[f"{axis}_start"]
        for attr in ('velo', 'ramp', 'dist'):
            back[f"{axis}_{attr}"] *= -1.0

        if verbose:
            print(self.linear_template % fore)
            print(self.linear_template % back)

        ret = True
        if upload:
            ret = False
            try:
                self.upload_trajectory('foreward.trj',
                                       self.linear_template % fore)
                self.upload_trajectory('backward.trj',
                                       self.linear_template % back)
                self.trajectories['foreward']['uploaded'] = True
                self.trajectories['backward']['uploaded'] = True
                ret = True
            except:
                raise ValueError("error uploading trajectory")
        return ret

    @withConnectedXPS
    def define_array_trajectory(self, positions, dtime=1.0, max_accels=None,
                                upload=True, name='array', verbose=True):
        """define a PVT trajectory for the trajectory group from a dictionary of
        position arrays for each positioner in the trajectory group.

        Positioners that are not included in the positions dict will not be moved.

        Arguments
        ---------
        positions:  dict of {PosName: np.ndarray} for each positioner to move
        dtime:      float, time per segment
        max_accels: dict of {PosName: max_acceleration} to use.
        name:       name of trajectory (file will be f"{name}.trj")
        upload:     bool, whether to upload trajectory

        Returns:
        -------
        dict with information about trajcetory.  This will include values for
             pvt_buff:  full text of trajectory buffer
             type: 'array'
             start: dict of starting values (backed up from first point so that
                    positioner can be accelerated to the desired velocity for the
                    second trajectory segment)
             npulses: number of expected pulses.

        Notes:
        ------
        1. The np.ndarray for each positioner must be the same length, and will be
           used as midpoints between trigger events.
        2. For ndarrays of lenght N, the trajectory will have N+1 segments: one
           to ramp up to velocity to approach the first point, and the last to
           decelerate to zero velocity.

        """
        tgroup = self.traj_group
        if tgroup is None:
            raise XPSException("No trajectory group defined")

        all_axes = [a for a in self.groups[tgroup]['positioners']]

        pdat = {}
        input_ok = True
        npts = None
        for key, value in positions.items():
            pname = key[:]

            if key.startswith(tgroup):
                pname = key[len(tgroup)+1:]
            if pname not in all_axes:
                print(f"Unknown positioner given: {pname}")
                input_ok = False
            if npts is None:
                npts = len(value)
            elif npts != len(value):
                print(f"incorrect array length for {pname}")
                input_ok = False

            if isinstance(value, np.ndarray):
                positions[key] = value.astype(np.float64).tolist()
            else:
                positions[key] = [float(x) for x in value]

        if not input_ok:
            return

        npulses  = npts+1
        dtime = float(abs(dtime))
        times = np.ones(npulses+1)*dtime

        if max_accels is None:
            max_accels = {}
        pos, dpos = {}, {}
        velo = {}
        accel = {}
        start = {}
        for axes in all_axes:
            stage = f'{tgroup}.{axes}'
            maxv = self.stages[stage]['max_velo']
            maxa = self.stages[stage]['max_accel']
            if axes in max_accels:
                maxa = min(max_accels[axes], maxa)
            if axes in positions:
                upos = positions[axes]
                # mid are the trajectory trigger points, the
                # mid points between the desired positions
                mid = [3*upos[0]-2*upos[1], 2*upos[0] - upos[1]]
                mid.extend(upos)
                mid.extend([2*upos[-1]-upos[-2],
                            3*upos[-1]-2*upos[-2],
                            ])
                mid = np.array(mid)
                pos[axes] = 0.5*(mid[1:] + mid[:-1])

                # adjust first segment velocity to half max accel
                p0, p1, p2 = pos[axes][0], pos[axes][1], pos[axes][2]
                v0 = (p1-p0)/dtime
                v1 = (p2-p1)/dtime
                a0 = (v1-v0)/dtime
                start[axes] = p1 - (p1-p0)*dtime*max(v0, 0.5*maxv)/max(a0, 0.5*maxa)

                pos[axes] = np.diff(pos[axes] - start[axes])
                velo[axes] = np.gradient(pos[axes])/times
                velo[axes][-1] = 0.0
                accel[axes] = np.gradient(velo[axes])/times

                if (max(abs(velo[axes])) > maxv):
                    errmsg = f"max velocity {maxv} violated for {axes}"
                    raise ValueError(errmsg)
                if (max(abs(accel[axes])) > maxa):
                    errmsg = f"max acceleration {maxa} violated for {axes}"
                    raise ValueError(errmsg)
            else:
                start[axes] = None
                pos[axes] = np.zeros(npulses+1, dtype=np.float64)
                velo[axes] = np.zeros(npulses+1, dtype=np.float64)
                accel[axes] = np.zeros(npulses+1, dtype=np.float64)


        traj = {'axes': all_axes,
                'type': 'array',
                'start': start, 'pixeltime': dtime,
                'npulses': npulses+1, 'nsegments': npulses+1,
                'uploaded': False}

        buff = ['']

        for n in range(npulses+1):
            line = [f"{dtime:.8f}"]
            for axes in all_axes:
                p, v = pos[axes][n], velo[axes][n]
                line.extend([f"{p:.8f}", f"{v:.8f}"])
            buff.append(', '.join(line))

        buff  = '\n'.join(buff)
        traj['pvt_buffer'] = buff

        if upload:
            tfile = f"{name}.trj"
            traj['name'] = name
            try:
                self.upload_trajectory(tfile, buff)
                traj['uploaded'] = True
            except:
                traj['uploaded'] = False
        self.trajectories[name] = traj
        return traj


    @withConnectedXPS
    def move_to_trajectory_start(self, name):
        """
        move to the start position of a named trajectory
        """
        tgroup = self.traj_group
        if tgroup is None:
            raise XPSException("No trajectory group defined")

        traj = self.trajectories.get(name, None)
        if traj is None:
            raise XPSException(f"Cannot find trajectory named '{name}'")

        if traj['type'] == 'line':
            for pos, axes in zip(traj['start'], traj['axes']):
                self.move_stage(f'{tgroup}.{axes}', pos)

        elif traj['type'] == 'array':
            for axes, pos in traj['start'].items():
                if pos is not None:
                    self.move_stage(f'{tgroup}.{axes}', pos)



    @withConnectedXPS
    def arm_trajectory(self, name, verbose=False, move_to_start=True):
        """
        prepare to run a named (assumed uploaded) trajectory
        """
        if self.traj_group is None:
            print("Must set group name!")

        traj = self.trajectories.get(name, None)
        if traj is None:
            raise XPSException(f"Cannot find trajectory '{name}'")

        if not traj['uploaded']:
            raise XPSException(f"trajectory '{name}' has not been uploaded")


        self.traj_state = ARMING
        self.traj_file = f'{name}.trj'

        if move_to_start:
            self.move_to_trajectory_start(name)

        # move_kws = {}
        outputs = []
        for out in self.gather_outputs:
            for i, ax in enumerate(traj['axes']):
                outputs.append(f'{self.traj_group}.{ax}.{out}')

        end_segment = traj['nsegments']
        self.nsegments = end_segment

        o = " ".join(outputs)
        self.gather_titles = f"{self.gather_header}\n#{o}\n"
        err, ret = self._xps.GatheringReset(self._sid)
        self.check_error(err, msg="GatheringReset")
        if verbose:
            print(" GatheringReset returned ", ret)

        err, ret = self._xps.GatheringConfigurationSet(self._sid, outputs)
        self.check_error(err, msg="GatheringConfigSet")

        if verbose:
            print(" GatheringConfigurationSet outputs ", outputs)
            print(" GatheringConfigurationSet returned ", ret)
            print(" segments, pixeltime" , end_segment, traj['pixeltime'])

        err, ret = self._xps.MultipleAxesPVTPulseOutputSet(self._sid, self.traj_group,
                                                           2, end_segment,
                                                           traj['pixeltime'])
        self.check_error(err, msg="PVTPulseOutputSet", with_raise=False)
        if verbose:
            print(" PVTPulse  ", ret)
        err, ret = self._xps.MultipleAxesPVTVerification(self._sid,
                                                         self.traj_group,
                                                         self.traj_file)

        self.check_error(err, msg="PVTVerification", with_raise=False)
        if verbose:
            print(" PVTVerify  ", ret)
        self.traj_state = ARMED

    @withConnectedXPS
    def run_trajectory(self, name=None, save=True, clean=False,
                       output_file='Gather.dat', verbose=False):

        """run a trajectory in PVT mode

        The trajectory *must be in the ARMED state
        """

        if 'xps-d' in self.firmware_version.lower():
            self._xps.CleanTmpFolder(self._sid)

            if clean:
                self._xps.CleanCoreDumpFolder(self._sid)

        if name in self.trajectories and self.traj_state != ARMED:
            self.arm_trajectory(name, verbose=verbose)

        if self.traj_state != ARMED:
            raise XPSException("Must arm trajectory before running!")

        tgroup = self.traj_group
        buffer = ('Always', f'{tgroup}.PVT.TrajectoryPulse',)
        err, ret = self._xps.EventExtendedConfigurationTriggerSet(self._sid, buffer,
                                                                  ('0','0'), ('0','0'),
                                                                  ('0','0'), ('0','0'))
        self.check_error(err, msg="EventConfigTrigger")
        if verbose:
            print( " EventExtended Trigger Set ", ret)

        err, ret = self._xps.EventExtendedConfigurationActionSet(self._sid,
                                                            ('GatheringOneData',),
                                                            ('',), ('',),('',),('',))
        self.check_error(err, msg="EventConfigAction")
        if verbose:
            print( " EventExtended Action  Set ", ret)

        eventID, m = self._xps.EventExtendedStart(self._sid)
        self.traj_state = RUNNING

        if verbose:
            print( " EventExtended ExtendedStart ", eventID, m)

        err, ret = self._xps.MultipleAxesPVTExecution(self._sid,
                                                      self.traj_group,
                                                      self.traj_file, 1)
        self.check_error(err, msg="PVT Execute", with_raise=False)
        if verbose:
            print( " PVT Execute  ", ret)

        ret = self._xps.EventExtendedRemove(self._sid, eventID)
        ret = self._xps.GatheringStop(self._sid)

        self.traj_state = COMPLETE
        npulses = 0
        if save:
            self.read_and_save(output_file, verbose=verbose)
        self.traj_state = IDLE
        return npulses

    @withConnectedXPS
    def read_and_save(self, output_file, verbose=False):
        "read and save gathering file"
        self.ngathered = 0
        npulses, buff = self.read_gathering(set_idle_when_done=False,
                                            verbose=verbose)
        if npulses < 1:
            return
        self.save_gathering_file(output_file, buff,
                                 verbose=verbose,
                                 set_idle_when_done=False)
        self.ngathered = npulses

    @withConnectedXPS
    def read_gathering(self, set_idle_when_done=True, verbose=False,
                       debug_time=False):
        """
        read gathering data from XPS
        """
        verbose = verbose or debug_time
        if verbose:
            print("READ Gathering XPS ", self.host, self._sid,
                  self.nsegments, time.ctime())
        dt = debugtime()
        self.traj_state = READING
        npulses = -1
        t0 = time.time()
        while npulses < 1:
            try:
                ret, npulses, nx = self._xps.GatheringCurrentNumberGet(self._sid)
            except SyntaxError:
                print("#XPS Gathering Read failed, will try again")
                pass
            if time.time()-t0 > 5:
                print("Failed to get gathering size after 5 seconds: return 0 points")
                print("Gather Returned: ", ret, npulses, nx, self._xps, time.ctime())
                return (0, ' \n')
            if npulses < 1 or ret != 0:
                time.sleep(0.05)
        dt.add("gather num %d npulses=%d (%d)" % (ret, npulses, self.nsegments))
        counter = 0
        while npulses < 1 and counter < 5:
            counter += 1
            time.sleep(0.25)
            ret, npulses, nx = self._xps.GatheringCurrentNumberGet(self._sid)
            print( 'Had to do repeat XPS Gathering: ', ret, npulses, nx)
        dt.add("gather before multilinesget, npulses=%d" % (npulses))
        try:
            ret, buff = self._xps.GatheringDataMultipleLinesGet(self._sid, 0, npulses)
        except ValueError:
            print("Failed to read gathering: ", ret, buff)
            return (0, ' \n')
        dt.add("gather after multilinesget  %d" % ret)
        nchunks = -1
        if ret < 0:  # gathering too long: need to read in chunks
            nchunks = 3
            nx  = int((npulses-2) / nchunks)
            ret = 1
            while True:
                time.sleep(0.05)
                ret, xbuff = self._xps.GatheringDataMultipleLinesGet(self._sid, 0, nx)
                if ret == 0:
                    break
                nchunks = nchunks + 2
                nx      = int((npulses-2) / nchunks)
                if nchunks > 10:
                    print('looks like something is wrong with the XPS!')
                    break
            buff = [xbuff]
            for i in range(1, nchunks):
                ret, xbuff = self._xps.GatheringDataMultipleLinesGet(self._sid, i*nx, nx)
                buff.append(xbuff)
            ret, xbuff = self._xps.GatheringDataMultipleLinesGet(self._sid, nchunks*nx,
                                                                npulses-nchunks*nx)
            buff.append(xbuff)
            buff = ''.join(buff)
        dt.add("gather after got buffer  %d" % len(buff))
        obuff = buff[:]
        for x in ';\r\t':
            obuff = obuff.replace(x,' ')
        dt.add("gather cleaned buffer  %d" % len(obuff))
        if set_idle_when_done:
            self.traj_state = IDLE
        if verbose:
            dt.show()
        return npulses, obuff

    def save_gathering_file(self, fname, buff, verbose=False, set_idle_when_done=True):
        """save gathering buffer read from read_gathering() to text file"""
        self.traj_state = WRITING
        f = open(fname, 'w')
        f.write(self.gather_titles)
        f.write(buff)
        f.close()
        nlines = len(buff.split('\n')) - 1
        if verbose:
            print(f'Wrote {nlines} lines, {len(buff)} bytes to {fname}')
        if set_idle_when_done:
            self.traj_state = IDLE

    def define_line_trajectories_general(self, name='default',
                                         start_values=None,
                                         stop_values=None,
                                         accel_values=None,
                                         pulse_time=0.1, scan_time=10.0):
        """
        Clemens' code for line trajectories -- should probably be
        unified with define_line_trajectories(),
        """
        if start_values is None:
            start_values = np.zeros(len(self.traj_positioners))
        else:
            start_values = np.array(start_values)

        if stop_values is None:
            stop_values = np.zeros(len(self.traj_positioners))
        else:
            stop_values = np.array(stop_values)

        if len(stop_values.shape) > 2:
            stop_values = stop_values[0]
            print("Cannot yet do multi-segment lines -- only doing first section")


        if accel_values is None:
            accel_values = []
            for posname in self.traj_positioners:
                accel = self.stages[f"{self.traj_group}.{posname}"]['max_accel']
                accel_values.append(accel)
        accel_values = np.array(accel_values)

        distances = stop_values - start_values
        velocities = abs(distances / (scan_time))
        scan_time = float(abs(scan_time))

        ramp_time = 1.5 * max(abs(velocities / accel_values))
        ramp      = velocities * ramp_time
        print("ramp : ", ramp_time, ramp)

        ramp_attr = {'ramptime': ramp_time}
        down_attr = {'ramptime': ramp_time}

        for ind, positioner in enumerate(self.traj_positioners):
            ramp_attr[positioner + 'ramp'] = ramp[ind]
            ramp_attr[positioner + 'velo'] = velocities[ind]

            down_attr[positioner + 'ramp'] = ramp[ind]
            down_attr[positioner + 'zero'] = 0

        ramp_template = "%(ramptime)f"
        move_template = "%(scantime)f"
        down_template = "%(ramptime)f"

        for positioner in self.traj_positioners:
            ramp_template += ", %({0}ramp)f, %({0}velo)f".format(positioner)
            move_template += ", %({0}dist)f, %({0}velo)f".format(positioner)
            down_template += ", %({0}ramp)f, %({0}zero)f".format(positioner)

        ramp_str = ramp_template % ramp_attr
        down_str = down_template % down_attr
        move_strings = []

        attr = {'scantime': scan_time}
        for pos_ind, positioner in enumerate(self.traj_positioners):
            attr[positioner + 'dist'] = distances[pos_ind]
            attr[positioner + 'velo'] = velocities[pos_ind]
        move_strings.append(move_template % attr)

        #construct trajectory:
        trajectory_str = ramp_str + '\n'
        for move_string in move_strings:
            trajectory_str += move_string + '\n'
        trajectory_str += down_str + '\n'

        self.trajectories[name] = {'pulse_time': pulse_time,
                                   'step_number': len(distances)}

        for ind, positioner in enumerate(self.traj_positioners):
            self.trajectories[name][positioner + 'ramp'] = ramp[ind]

        try:
            self.upload_trajectory(name + '.trj', trajectory_str)
        except:
            print('Failed to upload trajectory file')

        return trajectory_str

    def run_line_trajectory_general(self, name='default', verbose=False, save=True,
                                    outfile='Gather.dat'):
        """run trajectory in PVT mode"""
        traj = self.trajectories.get(name, None)
        if traj is None:
            raise XPSException(f'Cannot find trajectory named {name}')

        traj_file = f'{name}.trj'
        dtime = traj['pulse_time']
        ramps = []
        for positioner in self.traj_positioners:
            ramps.append(-traj[positioner + 'ramp'])
        ramps = np.array(ramps)

        try:
            step_number = traj['step_number']
        except KeyError:
            step_number = 1

        self._xps.GroupMoveRelative(self._sid, self.traj_group, ramps)

        outputs = []
        for out in self.gather_outputs:
            for i, ax in enumerate(traj['axes']):
                outputs.append(f'{self.traj_group}.{ax}.{out}')
                # move_kws[ax] = float(traj['start'][i])

        o = " ".join(outputs)
        self.gather_titles = f"{self.gather_header}\n#{o}\n"
        self._xps.GatheringReset(self._sid)
        self._xps.GatheringConfigurationSet(self._sid, self.gather_outputs)

        err, ret = self._xps.MultipleAxesPVTPulseOutputSet(self._sid, self.traj_group,
                                                           2, step_number + 1, dtime)
        self.check_error(err, msg="MultipleAxesPVTPulseOutputSet", with_raise=False)

        err, ret = self._xps.MultipleAxesPVTVerification(self._sid, self.traj_group, traj_file)
        self.check_error(err, msg="MultipleAxesPVTVerification", with_raise=False)

        buffer = ('Always', self.traj_group + '.PVT.TrajectoryPulse')
        err, ret = self._xps.EventExtendedConfigurationTriggerSet(self._sid, buffer,
                                                                  ('0', '0'), ('0', '0'),
                                                                  ('0', '0'), ('0', '0'))
        self.check_error(err, msg="EventExtendedConfigurationTriggerSet", with_raise=False)

        err, ret = self._xps.EventExtendedConfigurationActionSet(self._sid, ('GatheringOneData',),
                                                                 ('',), ('',), ('',), ('',))
        self.check_error(err, msg="EventExtendedConfigurationActionSet", with_raise=False)

        eventID, m = self._xps.EventExtendedStart(self._sid)

        self._xps.MultipleAxesPVTExecution(self._sid, self.traj_group, traj_file, 1)
        self._xps.EventExtendedRemove(self._sid, eventID)
        self._xps.GatheringStop(self._sid)

        npulses = 0
        if save:
            npulses, outbuff = self.read_and_save(outfile)

        self._xps.GroupMoveRelative(self._sid, self.traj_group, ramps)
        return npulses



if __name__ == '__main__':
    import sys
    ipaddr = sys.argv[1]
    x = NewportXPS(ipaddr)
    x.read_systemini()
    print(x.status_report())
