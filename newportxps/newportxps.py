#!/usr/bin/env python

from __future__ import print_function
import os
import posixpath
import sys
import time
import socket
from collections import OrderedDict
from .debugtime import debugtime
from six.moves import StringIO
from six.moves.configparser import  ConfigParser
import numpy as np

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

        socket.setdefaulttimeout(5.0)
        try:
            host = socket.gethostbyname(host)
        except:
            raise ValueError('Could not resolve XPS name %s' % host)
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

        self.stages = OrderedDict()
        self.groups = OrderedDict()
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

    @withConnectedXPS
    def status_report(self):
        """return printable status report"""
        err, uptime = self._xps.ElapsedTimeGet(self._sid)
        self.check_error(err, msg="Elapsed Time")
        boottime = time.time() - uptime
        out = ["# XPS host:         %s (%s)" % (self.host, socket.getfqdn(self.host)),
               "# Firmware:         %s" % self.firmware_version,
               "# Current Time:     %s" % time.ctime(),
               "# Last Reboot:      %s" % time.ctime(boottime),
               "# Trajectory Group: %s" % self.traj_group,
               ]

        out.append("# Groups and Stages")
        hstat = self.get_hardware_status()
        perrs = self.get_positioner_errors()

        for groupname, status in self.get_group_status().items():
            this = self.groups[groupname]
            out.append("%s (%s), Status: %s" %
                       (groupname, this['category'], status))
            for pos in this['positioners']:
                stagename = '%s.%s' % (groupname, pos)
                stage = self.stages[stagename]
                out.append("   %s (%s)"  % (stagename, stage['stagetype']))
                out.append("      Hardware Status: %s"  % (hstat[stagename]))
                out.append("      Positioner Errors: %s"  % (perrs[stagename]))
        return "\n".join(out)


    def connect(self):
        self._sid = self._xps.TCP_ConnectToServer(self.host,
                                                  self.port, self.timeout)
        try:
            self._xps.Login(self._sid, self.username, self.password)
        except:
            raise XPSException('Login failed for %s' % self.host)

        err, val = self._xps.FirmwareVersionGet(self._sid)
        self.firmware_version = val
        self.ftphome = ''

        if 'XPS-D' in self.firmware_version:
            err, val = self._xps.Send(self._sid, 'InstallerVersionGet(char *)')
            self.firmware_version = val
            self.ftpconn = SFTPWrapper(**self.ftpargs)
        else:
            self.ftpconn = FTPWrapper(**self.ftpargs)
            if 'XPS-C' in self.firmware_version:
                self.ftphome = '/Admin'
        try:
            self.read_systemini()
        except:
            print("Could not read system.ini!!!")


    def check_error(self, err, msg='', with_raise=True):
        if err != 0:
            err = "%d" % err
            desc = self._xps.errorcodes.get(err, 'unknown error')
            print("XPSError: message= %s, error=%s, description=%s" % (msg, err, desc))
            if with_raise:
                raise XPSException("%s %s [Error %s]" % (msg, desc, err))

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

        pvtgroups = []
        self.stages= OrderedDict()
        self.groups = OrderedDict()
        sconf = ConfigParser()
        sconf.readfp(StringIO('\n'.join(lines)))

        # read and populate lists of groups first
        for gtype, glist in sconf.items('GROUPS'): # ].items():
            if len(glist) > 0:
                for gname in glist.split(','):
                    gname = gname.strip()
                    self.groups[gname] = OrderedDict()
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
                print("could not set max velo/accel for %s" % sname)
            ret = self._xps.PositionerUserTravelLimitsGet(self._sid, sname)
            try:
                self.stages[sname]['low_limit']  = ret[1]
                self.stages[sname]['high_limit'] = ret[2]
            except:
                print("could not set limits for %s" % sname)

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
        self.ftpconn.put(text, filename)
        self.ftpconn.close()


    def upload_systemini(self, text):
        """upload text of system.ini

        Arguments:
        ----------
           text  (str):   full text of system.ini
        """
        self.ftpconn.connect(**self.ftpargs)
        self.ftpconn.cwd(posixpath.join(self.ftphome, 'Config'))
        self.ftpconn.put(text, 'system.ini')
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
        self.ftpconn.put(text, 'system.ini')
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
            print("Stage '%s' not found: " % stage)
            return
        params = self._xps.PositionerCorrectorPIDFFVelocityGet(self._sid, stage)
        if params[0] != 0 or len(params) != 13:
            print("error getting tuning parameters for %s" % stage)
            return

        params = params[1:]
        params[0] = closedloopstatus
        if kp is not None:      params[1] = kp
        if ki is not None:      params[2] = ki
        if kd is not None:      params[3] = kd
        if ks is not None:      params[4] = ks
        if inttime is not None: params[5] = inttime
        if dfilter is not None: params[6] = dfilter
        if gkp is not None:     params[7] = gkp
        if gki is not None:     params[8] = gki
        if gkd is not None:     params[9] = gkd
        if kform is not None:   params[10] = kform
        if ffgain is not None:  params[11] = ffgain
        ret = self._xps.PositionerCorrectorPIDFFVelocitySet(self._sid, stage, *params)

    @withConnectedXPS
    def get_tuning(self, stage):
        """get tuning parameters for a stage:
        closedloopstatus, kp, ki, kd, ks, inttime, dfilter,
        gkp, gki, gkd, kform, ffgain
        """
        if stage not in self.stages:
            print("Stage '%s' not found: " % stage)
            return
        params = self._xps.PositionerCorrectorPIDFFVelocityGet(self._sid, stage)
        if params[0] != 0 or len(params) != 13:
            print("error getting tuning parameters for %s" % stage)
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
            msg = "'%s' cannot be a trajectory group, must be one of %s"
            raise XPSException(msg % (group, pvtgroups))

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
                print("Warning: could not enable trajectory group '%s'"% self.traj_group)
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
                self.check_error(err, msg="%s group '%s'" % (action, group),
                                 with_raise=with_raise)
        elif group in self.groups:
            err, ret = method(self._sid, group)
            self.check_error(err, msg="%s group '%s'" % (action, group),
                             with_raise=with_raise)
        else:
            raise ValueError("Group '%s' not found" % group)

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
            self.initialize_group(group=g)

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
        out = OrderedDict()
        for group in self.groups:
            err, stat = self._xps.GroupStatusGet(self._sid, group)
            self.check_error(err, msg="GroupStatus '%s'" % (group))

            err, val = self._xps.GroupStatusStringGet(self._sid, stat)
            self.check_error(err, msg="GroupStatusString '%s'" % (stat))

            out[group] = val
        return out

    @withConnectedXPS
    def get_hardware_status(self):
        """
        get dictionary of hardware status for each stage
        """
        out = OrderedDict()
        for stage in self.stages:
            if stage in ('', None): continue
            err, stat = self._xps.PositionerHardwareStatusGet(self._sid, stage)
            self.check_error(err, msg="Pos HardwareStatus '%s'" % (stage))

            err, val = self._xps.PositionerHardwareStatusStringGet(self._sid, stat)
            self.check_error(err, msg="Pos HardwareStatusString '%s'" % (stat))
            out[stage] = val
        return out

    @withConnectedXPS
    def get_positioner_errors(self):
        """
        get dictionary of positioner errors for each stage
        """
        out = OrderedDict()
        for stage in self.stages:
            if stage in ('', None): continue
            err, stat = self._xps.PositionerErrorGet(self._sid, stage)
            self.check_error(err, msg="Pos Error '%s'" % (stage))

            err, val = self._xps.PositionerErrorStringGet(self._sid, stat)
            self.check_error(err, msg="Pos ErrorString '%s'" % (stat))

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
            print("Stage '%s' not found" % stage)
            return
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
    def move_stage(self, stage, value, relative=False):
        """
        move stage to position, optionally relative

        Parameters:
           stage (string): name of stage -- must be in self.stages
           value (float): target position
           relative (bool): whether move is relative [False]
        """
        if stage not in self.stages:
            print("Stage '%s' not found" % stage)
            return

        move = self._xps.GroupMoveAbsolute
        if relative:
            move = self._xps.GroupMoveRelative

        err, ret = move(self._sid, stage, [value])
        self.check_error(err, msg="Moving stage '%s'" % (stage))
        return ret

    @withConnectedXPS
    def get_stage_position(self, stage):
        """
        return current stage position

        Parameters:
           stage (string): name of stage -- must be in self.stages
        """
        if stage not in self.stages:
            print("Stage '%s' not found: " % stage)
            return

        err, val = self._xps.GroupPositionCurrentGet(self._sid, stage, 1)
        self.check_error(err, msg="Get Stage Position '%s'" % (stage))
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
    def define_line_trajectories(self, axis, group=None,
                                 start=0, stop=1, step=0.001, scantime=10.0,
                                 accel=None, upload=True, verbose=False):
        """defines 'forward' and 'backward' trajectories for a simple
        single element line scan in PVT Mode
        """
        if group is not None:
            self.set_trajectory_group(group)

        if self.traj_group is None:
            print("Must define a trajectory group first!")
            return

        for axname in (axis, axis.upper(), axis.lower(), axis.title()):
            stage = "%s.%s" % (self.traj_group, axname)
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
        scantime = float(abs(scantime))
        pixeltime= scantime / (npulses-1)
        scantime = pixeltime*npulses

        distance = (abs(stop - start) + abs(step))*1.0
        velocity = min(distance/scantime, max_velo)

        ramptime = max(2.e-5, abs(velocity/accel))
        rampdist = velocity*ramptime
        offset   = step/2.0 + scandir*rampdist

        trajbase = {'axes': [axis], 'pixeltime': pixeltime,
                    'npulses': npulses, 'nsegments': 3}

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
                fore["%s_%s" % (ax, attr)] = val

        back = fore.copy()
        back["%s_start" % axis] = fore["%s_stop" % axis]
        back["%s_stop" % axis]  = fore["%s_start" % axis]
        for attr in ('velo', 'ramp', 'dist'):
            back["%s_%s" % (axis, attr)] *= -1.0

        if verbose:
            print("TRAJ Text Fore, Back:")
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
                ret = True
            except:
                raise ValueError("error uploading trajectory")
        return ret

    @withConnectedXPS
    def arm_trajectory(self, name, verbose=False):
        """
        set up the trajectory from previously defined, uploaded trajectory
        """
        if self.traj_group is None:
            print("Must set group name!")

        traj = self.trajectories.get(name, None)
        if traj is None:
            raise XPSException("Cannot find trajectory named '%s'" %  name)

        self.traj_state = ARMING
        self.traj_file = '%s.trj'  % name

        # move_kws = {}
        outputs = []
        for out in self.gather_outputs:
            for i, ax in enumerate(traj['axes']):
                outputs.append('%s.%s.%s' % (self.traj_group, ax, out))
                # move_kws[ax] = float(traj['start'][i])


        end_segment = traj['nsegments'] - 1 + self.extra_triggers
        # self.move_group(self.traj_group, **move_kws)
        self.gather_titles = "%s\n#%s\n" % (self.gather_header, " ".join(outputs))

        err, ret = self._xps.GatheringReset(self._sid)
        self.check_error(err, msg="GatheringReset")
        if verbose:
            print(" GatheringReset returned ", ret)

        err, ret = self._xps.GatheringConfigurationSet(self._sid, outputs)
        self.check_error(err, msg="GatheringConfigSet")

        if verbose:
            print(" GatheringConfigurationSet outputs ", outputs)
            print(" GatheringConfigurationSet returned ", ret)
            print( end_segment, traj['pixeltime'])

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
    def run_trajectory(self, name=None, save=True,
                       output_file='Gather.dat', verbose=False):

        """run a trajectory in PVT mode

        The trajectory *must be in the ARMED state
        """

        if name in self.trajectories:
            self.arm_trajectory(name)

        if self.traj_state != ARMED:
            raise XPSException("Must arm trajectory before running!")

        buffer = ('Always', '%s.PVT.TrajectoryPulse' % self.traj_group,)
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
            self.read_and_save(output_file)
        self.traj_state = IDLE
        return npulses

    @withConnectedXPS
    def read_and_save(self, output_file):
        "read and save gathering file"
        self.ngathered = 0
        npulses, buff = self.read_gathering(set_idle_when_done=False)
        self.save_gathering_file(output_file, buff,
                                 verbose=False,
                                 set_idle_when_done=False)
        self.ngathered = npulses

    @withConnectedXPS
    def read_gathering(self, set_idle_when_done=True, debug_time=False):
        """
        read gathering data from XPS
        """
        dt = debugtime()
        self.traj_state = READING
        ret, npulses, nx = self._xps.GatheringCurrentNumberGet(self._sid)
        dt.add("gather num %d %d" % (ret, npulses))
        counter = 0
        while npulses < 1 and counter < 5:
            counter += 1
            time.sleep(0.25)
            ret, npulses, nx = self._xps.GatheringCurrentNumberGet(self._sid)
            print( 'Had to do repeat XPS Gathering: ', ret, npulses, nx)
        dt.add("gather before multilinesget")
        ret, buff = self._xps.GatheringDataMultipleLinesGet(self._sid, 0, npulses)
        dt.add("gather after multilinesget  %d" % ret)
        nchunks = -1
        if ret < 0:  # gathering too long: need to read in chunks
            nchunks = 3
            nx  = int((npulses-2) / nchunks)
            ret = 1
            while True:
                time.sleep(0.1)
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
        #dt.show()
        return npulses, obuff

    def save_gathering_file(self, fname, buffer, verbose=False, set_idle_when_done=True):
        """save gathering buffer read from read_gathering() to text file"""
        self.traj_state = WRITING
        f = open(fname, 'w')
        f.write(self.gather_titles)
        f.write(buffer)
        f.close()
        nlines = len(buffer.split('\n')) - 1
        if verbose:
            print('Wrote %i lines, %i bytes to %s' % (nlines, len(buff), fname))
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
                accel = self.stages["%s.%s"%(self.traj_group,  posname)]['max_accel']
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

        ret = False
        try:
            self.upload_trajectory(name + '.trj', trajectory_str)
            ret = True
            # print('Trajectory File uploaded.')
        except:
            print('Failed to upload trajectory file')

        return trajectory_str

    def run_line_trajectory_general(self, name='default', verbose=False, save=True,
                                    outfile='Gather.dat'):
        """run trajectory in PVT mode"""
        traj = self.trajectories.get(name, None)
        if traj is None:
            print('Cannot find trajectory named %s' % name)
            return

        traj_file = '%s.trj' % name
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

        # self.gather_outputs = []
        ##  gather_titles = []

        # for positioner in self.traj_positioners:
        #     for out in self.gather_outputs:
        #         self.gather_outputs.append('%s.%s.%s' % (self.traj_group, positioner, out))
        #        gather_titles.append('%s.%s' % (positioner, out))
        ## self.gather_titles = "%s\n#%s\n" % (xps_config['GATHER TITLES'],
        ##                                     "  ".join(gather_titles))

        outputs = []
        for out in self.gather_outputs:
            for i, ax in enumerate(traj['axes']):
                outputs.append('%s.%s.%s' % (self.traj_group, ax, out))
                # move_kws[ax] = float(traj['start'][i])


        end_segment = traj['nsegments'] - 1 + self.extra_triggers
        # self.move_group(self.traj_group, **move_kws)
        self.gather_titles = "%s\n#%s\n" % (self.gather_header, " ".join(outputs))


        self._xps.GatheringReset(self._sid)
        self._xps.GatheringConfigurationSet(self._sid, self.gather_outputs)

        print("step_number", step_number)
        ret = self._xps.MultipleAxesPVTPulseOutputSet(self._sid, self.traj_group,
                                                      2, step_number + 1, dtime)
        ret = self._xps.MultipleAxesPVTVerification(self._sid, self.traj_group, traj_file)

        buffer = ('Always', self.traj_group + '.PVT.TrajectoryPulse')
        o = self._xps.EventExtendedConfigurationTriggerSet(self._sid, buffer,
                                                          ('0', '0'), ('0', '0'),
                                                          ('0', '0'), ('0', '0'))

        o = self._xps.EventExtendedConfigurationActionSet(self._sid, ('GatheringOneData',),
                                                         ('',), ('',), ('',), ('',))

        eventID, m = self._xps.EventExtendedStart(self._sid)

        ret = self._xps.MultipleAxesPVTExecution(self._sid, self.traj_group, traj_file, 1)
        o = self._xps.EventExtendedRemove(self._sid, eventID)
        o = self._xps.GatheringStop(self._sid)

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
