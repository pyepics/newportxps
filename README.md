# newportxps

This module provides code for using Newport XPS motor controllers from Python.

While Newport Corp. has provided a basic socket and ftp interface to the XPS
controller for a long time, this interface is very low-level. In addition,
there are some incompatibilities between the different generations of XPS
controllers (generations C, Q, D in that chronological order), and a lack of
support for Python 3 in the Newport-provided interface.  The `newportxps`
module here aims to provide a simple, user-friendly interface for the Newport
XPS that works uniformly for all three generations of XPS and for both Python
2 and 3.

As an example, connecting to and reading the status of an XPS controller may
look like this:

```python
 >>> from newportxps import NewportXPS
 >>> xps = NewportXPS('164.54.160.000', username='Administrator', password='Please.Let.Me.In')
 >>> print(xps.status_report())
 # XPS host:         164.54.160.000 (164.54.160.000)
 # Firmware:         XPS-D-N13006
 # Current Time:     Sun Sep 16 13:40:24 2018
 # Last Reboot:      Wed Sep 12 14:46:44 2018
 # Trajectory Group: None
 # Groups and Stages
 DetectorZ (SingleAxisInUse), Status: Ready state from motion
    DetectorZ.Pos (ILS@ILS150CC@XPS-DRV11)
       Hardware Status: First driver powered on - ZM low level
       Positioner Errors: OK
 SampleX (SingleAxisInUse), Status: Ready state from motion
    SampleX.Pos (UTS@UTS150PP@XPS-DRV11)
       Hardware Status: First driver powered on - ZM high level
       Positioner Errors: OK
 SampleY (SingleAxisInUse), Status: Ready state from motion
    SampleY.Pos (UTS@UTS150PP@XPS-DRV11)
       Hardware Status: First driver powered on - ZM high level
       Positioner Errors: OK
 SampleZ (SingleAxisInUse), Status: Ready state from motion
   SampleZ.Pos (UTS@UTS150PP@XPS-DRV11)
       Hardware Status: First driver powered on - ZM low level
       Positioner Errors: OK

 >>> for gname, info in xps.groups.items():
 ...     print(gname, info)
 ...
 DetectorX {'category': 'SingleAxisInUse', 'positioners': ['Pos']}
 SampleX {'category': 'SingleAxisInUse', 'positioners': ['Pos']}
 SampleY {'category': 'SingleAxisInUse', 'positioners': ['Pos']}
 SampleZ {'category': 'SingleAxisInUse', 'positioners': ['Pos']}
 >>>
 >>> for sname, info in xps.stages.items():
 ...     print(sname, xps.get_stage_position(sname), info)
 ...
 DetectorX.Pos 36.5 {'type': 'ILS@ILS150CC@XPS-DRV11', 'max_velo': 100, 'max_accel': 400, 'low_limit': -74, 'high_limit': 74}
 SampleX.Pos 1.05 {'type': 'UTS@UTS150PP@XPS-DRV11', 'max_velo': 20, 'max_accel': 80, 'low_limit': -74, 'high_limit': 74}
 SampleY.Pos 0.24 {'type': 'UTS@UTS150PP@XPS-DRV11', 'max_velo': 20, 'max_accel': 80, 'low_limit': -74, 'high_limit': 74}
 SampleZ.Pos 2.5 {'type': 'UTS@UTS150PP@XPS-DRV11', 'max_velo': 20, 'max_accel': 80, 'low_limit': -74, 'high_limit': 74}

 >>> xps.move_stage('SampleZ.Pos', 1.0)

 >>> xps.home_group('DetectorX')


```

On creation and initialization of the NewportXPS, the Groups and status of the
controller are read in and Stages defined so that they can be queried or
moved.


The `NewportXPS` class has a number of methods to interact with the controller including:

   * reboot controller
   * get status, hardware errors, etc.
   * save and upload new `system.ini` and `stages.ini` files.
   * enable and disable Groups.
   * initialize and home Stages and Groups of Stages.
   * read Stage positions.
   * move Stages and Groups to new positions.
   * set Stage velocity.
   * define simple linear trajectories (using PVT mode), both 'forward' and 'backward'.
   * upload any PVT trajectory.
   * arm PVT trajectory.
   * run PVT trajectory.
   * read and save Gathering file for a trajectory.
