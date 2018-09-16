# newportxps

This module provides support code for using Newport XPS motor controllers from Python.

While Newport Corp. has provided a basic socket and ftp interface to the XPS
controller for a long time, this interface is very low-level and feels a lot
like using Tcl and/or C.  In addition, there are some incompatibilities
between the different generations of XPS controllers (generations C, Q, D in
that chronological order), and a lack of support for Python 3 in the
Newport-provided interface.

The newportxps module here attempts to provide a simpler and more
user-friendly interface o the Newport XPS, and one that works uniformly for
Python2 and 3, and for all three generations of XPS.  As an example,
connecting and reading the XPS status will look like this:

```python
 >>> from newportxps import NewportXPS
 >>> xps = NewpportXPS('164.54.160.000', user='Administrator', password='Please.Let.Me.In')
 >>> print(xps.status_report)
 # XPS host:         164.54.160.000 (164.54.160.000)
 # Firmware:         XPS-D-N13006
 # Current Time:     Sun Sep 16 13:40:24 2018
 # Last Reboot:      Wed Sep 12 14:46:44 2018
 # Trajectory Group: None
 # Groups and Stages
 VortexZ (SingleAxisInUse), Status: Ready state from motion
    VortexZ.Pos (ILS@ILS150CC@XPS-DRV11)
       Hardware Status: First driver powered on - ZM low level
       Positioner Errors: OK
 EigerX (SingleAxisInUse), Status: Ready state from motion
    EigerX.Pos (UTS@UTS150PP@XPS-DRV11)
       Hardware Status: First driver powered on - ZM high level
       Positioner Errors: OK
 EigerY (SingleAxisInUse), Status: Ready state from motion
    EigerY.Pos (UTS@UTS150PP@XPS-DRV11)
       Hardware Status: First driver powered on - ZM high level
       Positioner Errors: OK
 EigerZ (SingleAxisInUse), Status: Ready state from motion
   EigerZ.Pos (UTS@UTS150PP@XPS-DRV11)
       Hardware Status: First driver powered on - ZM low level
       Positioner Errors: OK

```

the `NewportXPS` class has a number of methods to interact with the controller, including

   * reboot controller
   * get status, hardware errors, etc.
   * save and upload new system.ini and stages.ini files
   * initialize and home stages and Groups of stages
   * read Stage positions.
   * move Stages and Groups to new positions.
