# XPS Python class
#
#  for XPS-C8 Firmware V2.6.x
#
#  See Programmer's manual for more information on XPS function calls
#
# Modified by Matt Newville: 01-Apr-2010, 26-Oct-2010
#    -  replaced tabs with 4 spaces
#    -  replaced very frequent occurences of
#          if (XPS.__usedSockets[socketId] == 0):   return
#       with "withValidSocket" decorator, whch raises an exception
#       if there is not a valid socket.
# made many return values "consistent".

import sys
import socket
from collections import defaultdict
from typing import Callable, Dict, Union, List

from .utils import bytes2str, str2bytes

class XPSException(Exception):
    """XPS Controller Exception"""
    def __init__(self, msg,*args):
        self.msg = msg
    def __str__(self):
        return str(self.msg)


class XPSOutputs:
    _PARSERS: Dict[str, Callable[[str], Union[bool, str, float, int]]] = {
        'bool': bool,
        'char': lambda x: x,
        'double': float,
        'int': int,
        'short': int,
        'unsigned short': int,
    }

    def __init__(self, *output_parameter_types: str):
        self.output_parameter_types = output_parameter_types
        for p in output_parameter_types:
            assert p in self._PARSERS, f'Unknown output parameter type {p}'

    def __str__(self):
        return ','.join(f'{c_type} *' for c_type in self.output_parameter_types)

    def parse(self, error: int, response: str):
        if error != 0:
            return [error, response]

        response_parts = response.split(',', len(self.output_parameter_types))
        parsed_response: List[Union[bool, str, float, int]] = [error]
        for i, c_type in enumerate(self.output_parameter_types):
            parsed_response.append(self._PARSERS[c_type](response_parts[i]))
        return parsed_response


class XPS:
    # Defines
    MAX_NB_SOCKETS = 100

    # Global variables
    __sockets = {}
    __usedSockets = defaultdict(int)
    __nbSockets = 0

    # Initialization Function
    def __init__ (self):
        self.errorcodes = {}

    def withValidSocket(fcn):
        """ decorator to ensure that a valid socket is passed as the
        first argument of the decorated function"""
        def wrapper(*args, **kw):
            try:
                sid = args[1]
                if XPS.__usedSockets[sid] == 0:
                    raise XPSException('invalid socket at function %s' % fcn.__name__)
            except IndexError:
                raise XPSException('no socket specified for fucntion %s' % fcn.__name__)
            return fcn(*args, **kw)
        wrapper.__doc__ = fcn.__doc__
        wrapper.__name__ = fcn.__name__
        wrapper.__dict__.update(fcn.__dict__)
        return wrapper

    # Send command and get return
    @withValidSocket
    def __sendAndReceive (self, socketId, command):
        # print("SEND REC ", command, type(command))
        suffix = ',EndOfAPI'
        try:
            XPS.__sockets[socketId].send(str2bytes(command))
            ret = bytes2str(XPS.__sockets[socketId].recv(1024))
            while (ret.find(suffix) == -1):
                ret += bytes2str(XPS.__sockets[socketId].recv(1024))
        except socket.timeout:
            return -2, ''
        except socket.error as err: #  (errNb, errString):
            print( 'Socket error : ', err.errno, err)
            return -2, ''

        error, rest = ret[:-len(suffix)].split(',', 1)
        return int(error), rest

    def Send(self, socketId=None, cmd=None, check=False):
        """send and receive command cmd from socketId
        if socketId is not given, self.socketId will be used
        with check=True, an XPSException will be raised on error.
        """
        if socketId is None:
            socketId = self.socketId
        self.socketId = socketId
        err, msg = self.__sendAndReceive(socketId, cmd)
        if err != 0 and check:
            raise XPSException(msg)
        return err, msg

    # TCP_ConnectToServer
    def TCP_ConnectToServer (self, IP, port, timeOut):
        socketId = 0
        if (XPS.__nbSockets < self.MAX_NB_SOCKETS):
            while (XPS.__usedSockets[socketId] == 1 and socketId < self.MAX_NB_SOCKETS):
                socketId += 1
                self.socketId = socketId
            if (socketId == self.MAX_NB_SOCKETS):
                return -1
        else:
            return -1

        XPS.__usedSockets[socketId] = 1
        XPS.__nbSockets += 1
        try:
            XPS.__sockets[socketId] = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            XPS.__sockets[socketId].connect((IP, port))
            XPS.__sockets[socketId].settimeout(timeOut)
            XPS.__sockets[socketId].setblocking(1)
        except socket.error:
            return -1

        err, ret = self.ErrorListGet(socketId)
        self.errorcodes = {}
        for cline in ret.split(';'):
            if ':' in cline:
                ecode, message = cline.split(':', 1)
                ecode = ecode.replace('Error', '').strip()
                message = message.strip()
                self.errorcodes[ecode] = message

        return socketId

    # TCP_SetTimeout
    def TCP_SetTimeout (self, socketId, timeOut):
        if (XPS.__usedSockets[socketId] == 1):
            XPS.__sockets[socketId].settimeout(timeOut)

    # TCP_CloseSocket
    def TCP_CloseSocket (self, socketId):
        if (socketId >= 0 and socketId < self.MAX_NB_SOCKETS):
            try:
                XPS.__sockets[socketId].close()
                XPS.__usedSockets[socketId] = 0
                XPS.__nbSockets -= 1
            except socket.error:
                pass

    # GetLibraryVersion
    def GetLibraryVersion (self):
        return ['XPS-C8 Firmware V2.6.x Beta 19']

    # ControllerMotionKernelTimeLoadGet :  Get controller motion kernel time load
    def ControllerMotionKernelTimeLoadGet(self, socketId=None):
        outputs = XPSOutputs("double", 'double', 'double', 'double')
        command = f'ControllerMotionKernelTimeLoadGet({outputs})'
        error, returnedString = self.Send(socketId=socketId, cmd=command)
        return outputs.parse(error, returnedString)

    # ControllerStatusGet :  Read controller current status
    def ControllerStatusGet(self, socketId=None):
        outputs = XPSOutputs('int')
        error, returnedString = self.Send(socketId=socketId,
                                          cmd=f'ControllerStatusGet({outputs})', check=True)
        return outputs.parse(error, returnedString)

    # ControllerStatusStringGet :  Return the controller status string corresponding to the controller status code
    def ControllerStatusStringGet(self, socketId, ControllerStatusCode):
        command = 'ControllerStatusStringGet(%s, char *)' % str(ControllerStatusCode)
        return self.Send(socketId, command)

    # ElapsedTimeGet :  Return elapsed time from controller power on
    def ElapsedTimeGet(self, socketId=None):
        outputs = XPSOutputs('double')
        command = f'ElapsedTimeGet({outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # ErrorStringGet :  Return the error string corresponding to the error code
    def ErrorStringGet(self, socketId, ErrorCode):
        return self.Send(socketId, 'ErrorStringGet(%s, char *)' %  str(ErrorCode))

    # FirmwareVersionGet :  Return firmware version
    def FirmwareVersionGet(self, socketId=None):
        return self.Send(socketId, 'FirmwareVersionGet(char *)')

    # TCLScriptExecute :  Execute a TCL script from a TCL file
    def TCLScriptExecute (self, socketId, TCLFileName, TaskName, ParametersList):
        command = 'TCLScriptExecute(' + TCLFileName + ',' + TaskName + ',' + ParametersList + ')'
        return self.Send(socketId, command)

    # TCLScriptExecuteAndWait :  Execute a TCL script from a TCL file and wait the end of execution to return
    def TCLScriptExecuteAndWait (self, socketId, TCLFileName, TaskName, InputParametersList):
        command = 'TCLScriptExecuteAndWait(' + TCLFileName + ',' + TaskName + ',' + InputParametersList + ',char *)'
        return self.Send(socketId, command)

    # TCLScriptExecuteWithPriority :  Execute a TCL script with defined priority
    def TCLScriptExecuteWithPriority (self, socketId, TCLFileName, TaskName, TaskPriorityLevel, ParametersList):
        command = 'TCLScriptExecuteWithPriority(' + TCLFileName + ',' + TaskName + ',' + TaskPriorityLevel + ',' + ParametersList + ')'
        return self.Send(socketId, command)

    # TCLScriptKill :  Kill TCL Task
    def TCLScriptKill (self, socketId, TaskName):
        command = 'TCLScriptKill(' + TaskName + ')'
        return self.Send(socketId, command)

    # TimerGet :  Get a timer
    def TimerGet (self, socketId, TimerName):
        outputs = XPSOutputs('int')
        command = f'TimerGet({TimerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # TimerSet :  Set a timer
    def TimerSet (self, socketId, TimerName, FrequencyTicks):
        return self.Send(socketId, 'TimerSet(%s, %s)' % (TimerName, str(FrequencyTicks)))

    # Reboot :  Reboot the controller
    def Reboot (self, socketId):
        return self.Send(socketId, 'Reboot()')

    # Login :  Log in
    def Login (self, socketId, Name, Password):
        return self.Send(socketId, 'Login(%s,%s)' % ( Name,  Password) )

    # CloseAllOtherSockets :  Close all socket beside the one used to send this command
    def CloseAllOtherSockets (self, socketId):
        return self.Send(socketId, 'CloseAllOtherSockets()')

    # HardwareDateAndTimeGet :  Return hardware date and time
    def HardwareDateAndTimeGet (self, socketId):
        return self.Send(socketId, 'HardwareDateAndTimeGet(char *)')

    # HardwareDateAndTimeSet :  Set hardware date and time
    def HardwareDateAndTimeSet (self, socketId, DateAndTime):
        return self.Send(socketId, 'HardwareDateAndTimeSet(%s)'% DateAndTime )

    # EventAdd :  ** OBSOLETE ** Add an event
    def EventAdd (self, socketId, PositionerName, EventName, EventParameter, ActionName, ActionParameter1, ActionParameter2, ActionParameter3):
        command = 'EventAdd(' + PositionerName + ',' + EventName + ',' + EventParameter + ',' + ActionName + ',' + ActionParameter1 + ',' + ActionParameter2 + ',' + ActionParameter3 + ')'
        return self.Send(socketId, command)

    # EventGet :  ** OBSOLETE ** Read events and actions list
    def EventGet (self, socketId, PositionerName):
        command = 'EventGet(' + PositionerName + ',char *)'
        return self.Send(socketId, command)

    # EventRemove :  ** OBSOLETE ** Delete an event
    def EventRemove (self, socketId, PositionerName, EventName, EventParameter):
        command = 'EventRemove(' + PositionerName + ',' + EventName + ',' + EventParameter + ')'
        return self.Send(socketId, command)

    # EventWait :  ** OBSOLETE ** Wait an event
    def EventWait (self, socketId, PositionerName, EventName, EventParameter):
        command = 'EventWait(' + PositionerName + ',' + EventName + ',' + EventParameter + ')'
        return self.Send(socketId, command)

    # EventExtendedConfigurationTriggerSet :  Configure one or several events
    def EventExtendedConfigurationTriggerSet (self, socketId, ExtendedEventName, EventParameter1, EventParameter2, EventParameter3, EventParameter4):
        command = 'EventExtendedConfigurationTriggerSet('
        for i in range(len(ExtendedEventName)):
            if (i > 0):
                command += ','
            command += ExtendedEventName[i] + ',' + EventParameter1[i] + ',' + EventParameter2[i] + ',' + EventParameter3[i] + ',' + EventParameter4[i]
        command += ')'

        return self.Send(socketId, command)

    # EventExtendedConfigurationTriggerGet :  Read the event configuration
    def EventExtendedConfigurationTriggerGet (self, socketId):
        return self.Send(socketId, 'EventExtendedConfigurationTriggerGet(char *)')


    # EventExtendedConfigurationActionSet :  Configure one or several actions
    def EventExtendedConfigurationActionSet (self, socketId, ExtendedActionName, ActionParameter1, ActionParameter2, ActionParameter3, ActionParameter4):
        command = 'EventExtendedConfigurationActionSet('
        for i in range(len(ExtendedActionName)):
            if (i > 0):
                command += ','
            command += ExtendedActionName[i] + ',' + ActionParameter1[i] + ',' + ActionParameter2[i] + ',' + ActionParameter3[i] + ',' + ActionParameter4[i]
        command += ')'

        return self.Send(socketId, command)


    # EventExtendedConfigurationActionGet :  Read the action configuration
    def EventExtendedConfigurationActionGet (self, socketId):
        return self.Send(socketId, 'EventExtendedConfigurationActionGet(char *)')

    # EventExtendedStart :  Launch the last event and action configuration and return an ID
    def EventExtendedStart (self, socketId):
        outputs = XPSOutputs('int')
        command = f'EventExtendedStart({outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # EventExtendedAllGet :  Read all event and action configurations
    def EventExtendedAllGet (self, socketId):
        return self.Send(socketId,  'EventExtendedAllGet(char *)')

    # EventExtendedGet :  Read the event and action configuration defined by ID
    def EventExtendedGet (self, socketId, ID):
        return self.Send(socketId, 'EventExtendedGet(' + str(ID) + ',char *,char *)')

    # EventExtendedRemove :  Remove the event and action configuration defined by ID
    def EventExtendedRemove (self, socketId, ID):
        return self.Send(socketId, 'EventExtendedRemove(' + str(ID) + ')')

    # EventExtendedWait :  Wait events from the last event configuration
    def EventExtendedWait (self, socketId):
        return self.Send(socketId, 'EventExtendedWait()')

    # GatheringConfigurationGet : Read different mnemonique type
    def GatheringConfigurationGet (self, socketId):
        return self.Send(socketId, 'GatheringConfigurationGet(char *)')

    # GatheringConfigurationSet :  Configuration acquisition
    def GatheringConfigurationSet (self, socketId, Type):
        command = 'GatheringConfigurationSet('
        for i in range(len(Type)):
            if (i > 0):
                command += ','
            command += Type[i]
        command += ')'
        return self.Send(socketId, command)

    # GatheringCurrentNumberGet :  Maximum number of samples and current number during acquisition
    def GatheringCurrentNumberGet (self, socketId):
        outputs = XPSOutputs('int', 'int')
        command = f'GatheringCurrentNumberGet({outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GatheringStopAndSave :  Stop acquisition and save data
    def GatheringStopAndSave (self, socketId):
        return self.Send(socketId, 'GatheringStopAndSave()')


    # GatheringDataAcquire :  Acquire a configured data
    def GatheringDataAcquire (self, socketId):
        return self.Send(socketId, 'GatheringDataAcquire()')

    # GatheringDataGet :  Get a data line from gathering buffer
    def GatheringDataGet (self, socketId, IndexPoint):
        return self.Send(socketId, 'GatheringDataGet(%s, char *)' % str(IndexPoint))

    # GatheringDataMultipleLinesGet :  Get multiple data lines from gathering buffer
    def GatheringDataMultipleLinesGet (self, socketId, IndexPoint, NumberOfLines):
        command = 'GatheringDataMultipleLinesGet(' + str(IndexPoint) + ',' + str(NumberOfLines) + ',char *)'
        return self.Send(socketId, command)

    # GatheringReset :  Empty the gathered data in memory to start new gathering from scratch
    def GatheringReset(self, socketId):
        return self.Send(socketId, 'GatheringReset()')

    # GatheringRun :  Start a new gathering
    def GatheringRun (self, socketId, DataNumber, Divisor):
        command = 'GatheringRun(' + str(DataNumber) + ',' + str(Divisor) + ')'
        return self.Send(socketId, command)


    # GatheringRunAppend :  Re-start the stopped gathering to add new data
    def GatheringRunAppend (self, socketId):
        return self.Send(socketId, 'GatheringRunAppend()')

    # GatheringStop :  Stop the data gathering (without saving to file)
    def GatheringStop (self, socketId):
        return self.Send(socketId, 'GatheringStop()')

    # GatheringExternalConfigurationSet :  Configuration acquisition
    def GatheringExternalConfigurationSet (self, socketId, Type):
        command = 'GatheringExternalConfigurationSet('
        for i in range(len(Type)):
            if (i > 0):
                command += ','
            command += Type[i]
        command += ')'

        return self.Send(socketId, command)

    # GatheringExternalConfigurationGet :  Read different mnemonique type
    def GatheringExternalConfigurationGet (self, socketId):
        return self.Send(socketId, 'GatheringExternalConfigurationGet(char *)')

    # GatheringExternalCurrentNumberGet :  Maximum number of samples and current number during acquisition
    def GatheringExternalCurrentNumberGet (self, socketId):
        outputs = XPSOutputs('int', 'int')
        command = f'GatheringExternalCurrentNumberGet({outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GatheringExternalDataGet :  Get a data line from external gathering buffer
    def GatheringExternalDataGet (self, socketId, IndexPoint):
        return self.Send(socketId, 'GatheringExternalDataGet(%s, char *)' % str(IndexPoint))

    # GatheringExternalStopAndSave :  Stop acquisition and save data
    def GatheringExternalStopAndSave (self, socketId):
        return self.Send(socketId, 'GatheringExternalStopAndSave()')

    # GlobalArrayGet :  Get global array value
    def GlobalArrayGet (self, socketId, Number):
        return self.Send(socketId, 'GlobalArrayGet(%s, char *)' %  str(Number))

    # GlobalArraySet :  Set global array value
    def GlobalArraySet (self, socketId, Number, ValueString):
        command = 'GlobalArraySet(' + str(Number) + ',' + ValueString + ')'
        return self.Send(socketId, command)

    # DoubleGlobalArrayGet :  Get double global array value
    def DoubleGlobalArrayGet (self, socketId, Number):
        outputs = XPSOutputs('double')
        command = f'DoubleGlobalArrayGet({Number},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # DoubleGlobalArraySet :  Set double global array value
    def DoubleGlobalArraySet (self, socketId, Number, DoubleValue):
        command = 'DoubleGlobalArraySet(' + str(Number) + ',' + str(DoubleValue) + ')'
        return self.Send(socketId, command)

    # GPIOAnalogGet :  Read analog input or analog output for one or few input
    def GPIOAnalogGet (self, socketId, GPIOName):
        outputs = XPSOutputs(*(['double'] * len(GPIOName)))
        command = 'GPIOAnalogGet('
        for i in range(len(GPIOName)):
            if (i > 0):
                command += ','
            command += GPIOName[i] + ',' + 'double *'
        command += ')'

        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GPIOAnalogSet :  Set analog output for one or few output
    def GPIOAnalogSet (self, socketId, GPIOName, AnalogOutputValue):
        command = 'GPIOAnalogSet('
        for i in range(len(GPIOName)):
            if (i > 0):
                command += ','
            command += GPIOName[i] + ',' + str(AnalogOutputValue[i])
        command += ')'
        return self.Send(socketId, command)

    # GPIOAnalogGainGet :  Read analog input gain (1, 2, 4 or 8) for one or few input
    def GPIOAnalogGainGet (self, socketId, GPIOName):
        outputs = XPSOutputs(*(['int'] * len(GPIOName)))
        command = 'GPIOAnalogGainGet('
        for i in range(len(GPIOName)):
            if (i > 0):
                command += ','
            command += GPIOName[i] + ',' + 'int *'
        command += ')'

        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GPIOAnalogGainSet :  Set analog input gain (1, 2, 4 or 8) for one or few input
    def GPIOAnalogGainSet (self, socketId, GPIOName, AnalogInputGainValue):
        command = 'GPIOAnalogGainSet('
        for i in range(len(GPIOName)):
            if (i > 0):
                command += ','
            command += GPIOName[i] + ',' + str(AnalogInputGainValue[i])
        command += ')'

        return self.Send(socketId, command)

    # GPIODigitalGet :  Read digital output or digital input
    def GPIODigitalGet (self, socketId, GPIOName):
        outputs = XPSOutputs('unsigned short')
        command = f'GPIODigitalGet({GPIOName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)


    # GPIODigitalSet :  Set Digital Output for one or few output TTL
    def GPIODigitalSet (self, socketId, GPIOName, Mask, DigitalOutputValue):
        command = 'GPIODigitalSet(' + GPIOName + ',' + str(Mask) + ',' + str(DigitalOutputValue) + ')'
        return self.Send(socketId, command)

    # GroupAccelerationSetpointGet :  Return setpoint accelerations
    def GroupAccelerationSetpointGet (self, socketId, GroupName, nbElement):
        outputs = XPSOutputs(*(['double'] * nbElement))
        command = f'GroupAccelerationSetpointGet({GroupName},{outputs})'

        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GroupAnalogTrackingModeEnable :  Enable Analog Tracking mode on selected group
    def GroupAnalogTrackingModeEnable (self, socketId, GroupName, Type):
        command = 'GroupAnalogTrackingModeEnable(' + GroupName + ',' + Type + ')'
        return self.Send(socketId, command)

    # GroupAnalogTrackingModeDisable :  Disable Analog Tracking mode on selected group
    def GroupAnalogTrackingModeDisable (self, socketId, GroupName):
        command = 'GroupAnalogTrackingModeDisable(' + GroupName + ')'
        return self.Send(socketId, command)

    # GroupCorrectorOutputGet :  Return corrector outputs
    def GroupCorrectorOutputGet (self, socketId, GroupName, nbElement):
        outputs = XPSOutputs(*(['double'] * nbElement))
        command = f'GroupCorrectorOutputGet({GroupName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GroupCurrentFollowingErrorGet :  Return current following errors
    def GroupCurrentFollowingErrorGet (self, socketId, GroupName, nbElement):
        outputs = XPSOutputs(*(['double'] * nbElement))
        command = f'GroupCurrentFollowingErrorGet({GroupName},{outputs})'

        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GroupHomeSearch :  Start home search sequence
    def GroupHomeSearch (self, socketId, GroupName):
        return self.Send(socketId,  'GroupHomeSearch(%s)' % GroupName )

    # GroupHomeSearchAndRelativeMove :  Start home search sequence and execute a displacement
    def GroupHomeSearchAndRelativeMove (self, socketId, GroupName, TargetDisplacement):
        command = 'GroupHomeSearchAndRelativeMove(' + GroupName + ','
        for i in range(len(TargetDisplacement)):
            if (i > 0):
                command += ','
            command += str(TargetDisplacement[i])
        command += ')'
        return self.Send(socketId, command)

    # GroupInitialize :  Start the initialization
    def GroupInitialize (self, socketId, GroupName):
        return self.Send(socketId, 'GroupInitialize(%s)' % GroupName)

    # GroupInitializeWithEncoderCalibration :  Start the initialization with encoder calibration
    def GroupInitializeWithEncoderCalibration (self, socketId, GroupName):
        return self.Send(socketId, 'GroupInitializeWithEncoderCalibration(%s)' % GroupName )

    # GroupJogParametersSet :  Modify Jog parameters on selected group and activate the continuous move
    def GroupJogParametersSet (self, socketId, GroupName, Velocity, Acceleration):
        command = 'GroupJogParametersSet(' + GroupName + ','
        for i in range(len(Velocity)):
            if (i > 0):
                command += ','
            command += str(Velocity[i]) + ',' + str(Acceleration[i])
        command += ')'
        return self.Send(socketId, command)

    # GroupJogParametersGet :  Get Jog parameters on selected group
    def GroupJogParametersGet (self, socketId, GroupName, nbElement):
        outputs = XPSOutputs(*(['double'] * 2 * nbElement))
        command = f'GroupJogParametersGet({GroupName},{outputs})'

        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GroupJogCurrentGet :  Get Jog current on selected group
    def GroupJogCurrentGet (self, socketId, GroupName, nbElement):
        outputs = XPSOutputs(*(['double'] * 2 * nbElement))
        command = f'GroupJogCurrentGet({GroupName},{outputs})'

        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GroupJogModeEnable :  Enable Jog mode on selected group
    def GroupJogModeEnable (self, socketId, GroupName):
        return self.Send(socketId, 'GroupJogModeEnable(%s)' % GroupName)


    # GroupJogModeDisable :  Disable Jog mode on selected group
    def GroupJogModeDisable (self, socketId, GroupName):
        return self.Send(socketId, 'GroupJogModeDisable(%s)' % GroupName)

    # GroupKill :  Kill the group
    def GroupKill (self, socketId, GroupName):
        return self.Send(socketId, 'GroupKill(%s)' % GroupName )

    # GroupMoveAbort :  Abort a move
    def GroupMoveAbort (self, socketId, GroupName):
        return self.Send(socketId, 'GroupMoveAbort(%s)' % GroupName )

    # GroupMoveAbsolute :  Do an absolute move
    def GroupMoveAbsolute (self, socketId, GroupName, TargetPosition):
        command = 'GroupMoveAbsolute(' + GroupName + ','
        for i in range(len(TargetPosition)):
            if (i > 0):
                command += ','
            command += str(TargetPosition[i])
        command += ')'
        return self.Send(socketId, command)

    # GroupMoveRelative :  Do a relative move
    def GroupMoveRelative (self, socketId, GroupName, TargetDisplacement):
        command = 'GroupMoveRelative(' + GroupName + ','
        for i in range(len(TargetDisplacement)):
            if (i > 0):
                command += ','
            command += str(TargetDisplacement[i])
        command += ')'
        return self.Send(socketId, command)

    # GroupMotionDisable :  Set Motion disable on selected group
    def GroupMotionDisable (self, socketId, GroupName):
        return self.Send(socketId, 'GroupMotionDisable(%s)' % GroupName )

    # GroupMotionEnable :  Set Motion enable on selected group
    def GroupMotionEnable (self, socketId, GroupName):
        return self.Send(socketId, 'GroupMotionEnable(%s)' % GroupName)


    # GroupPositionCorrectedProfilerGet :  Return corrected profiler positions
    def GroupPositionCorrectedProfilerGet (self, socketId, GroupName, PositionX, PositionY):
        outputs = XPSOutputs('double', 'double')
        command = f'GroupPositionCorrectedProfilerGet({GroupName},{PositionX},{PositionY},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GroupPositionCurrentGet :  Return current positions
    def GroupPositionCurrentGet (self, socketId, GroupName, nbElement):
        outputs = XPSOutputs(*(['double'] * nbElement))
        command = f'GroupPositionCurrentGet({GroupName},{outputs})'

        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GroupPositionPCORawEncoderGet :  Return PCO raw encoder positions
    def GroupPositionPCORawEncoderGet (self, socketId, GroupName, PositionX, PositionY):
        outputs = XPSOutputs('double', 'double')
        command = f'GroupPositionPCORawEncoderGet({GroupName},{PositionX},{PositionY},{outputs})'

        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GroupPositionSetpointGet :  Return setpoint positions
    def GroupPositionSetpointGet (self, socketId, GroupName, nbElement):
        outputs = XPSOutputs(*(['double'] * nbElement))
        command = f'GroupPositionSetpointGet({GroupName},{outputs})'

        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GroupPositionTargetGet :  Return target positions
    def GroupPositionTargetGet (self, socketId, GroupName, nbElement):
        outputs = XPSOutputs(*(['double'] * nbElement))
        command = f'GroupPositionTargetGet({GroupName},{outputs})'

        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GroupReferencingActionExecute :  Execute an action in referencing mode
    def GroupReferencingActionExecute (self, socketId, PositionerName, ReferencingAction, ReferencingSensor, ReferencingParameter):
        command = 'GroupReferencingActionExecute(' + PositionerName + ',' + ReferencingAction + ',' + ReferencingSensor + ',' + str(ReferencingParameter) + ')'
        return self.Send(socketId, command)

    # GroupReferencingStart :  Enter referencing mode
    def GroupReferencingStart (self, socketId, GroupName):
        return self.Send(socketId, 'GroupReferencingStart(%s)' % GroupName)

    # GroupReferencingStop :  Exit referencing mode
    def GroupReferencingStop (self, socketId, GroupName):
        return self.Send(socketId, 'GroupReferencingStop(%s)' % GroupName)

    # GroupStatusGet :  Return group status
    def GroupStatusGet (self, socketId, GroupName):
        outputs = XPSOutputs('int')
        command = f'GroupStatusGet({GroupName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GroupStatusStringGet :  Return the group status string corresponding to the group status code
    def GroupStatusStringGet (self, socketId, GroupStatusCode):
        return self.Send(socketId, 'GroupStatusStringGet(%s, char*)'  % str(GroupStatusCode))

    # GroupVelocityCurrentGet :  Return current velocities
    def GroupVelocityCurrentGet (self, socketId, GroupName, nbElement):
        outputs = XPSOutputs(*(['double'] * nbElement))
        command = f'GroupVelocityCurrentGet({GroupName},{outputs})'

        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # KillAll :  Put all groups in 'Not initialized' state
    def KillAll (self, socketId):
        return self.Send(socketId, 'KillAll()')

    # PositionerAnalogTrackingPositionParametersGet :  Read dynamic parameters for one axe of a group for a future analog tracking position
    def PositionerAnalogTrackingPositionParametersGet (self, socketId, PositionerName):
        outputs = XPSOutputs('char', 'double', 'double', 'double', 'double')
        command = f'PositionerAnalogTrackingPositionParametersGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerAnalogTrackingPositionParametersSet :  Update dynamic parameters for one axe of a group for a future analog tracking position
    def PositionerAnalogTrackingPositionParametersSet (self, socketId, PositionerName, GPIOName, Offset, Scale, Velocity, Acceleration):
        command = 'PositionerAnalogTrackingPositionParametersSet(' + PositionerName + ',' + GPIOName + ',' + str(Offset) + ',' + str(Scale) + ',' + str(Velocity) + ',' + str(Acceleration) + ')'
        return self.Send(socketId, command)

    # PositionerAnalogTrackingVelocityParametersGet :  Read dynamic parameters for one axe of a group for a future analog tracking velocity
    def PositionerAnalogTrackingVelocityParametersGet (self, socketId, PositionerName):
        outputs = XPSOutputs('char', 'double', 'double', 'double', 'int', 'double', 'double')
        command = f'PositionerAnalogTrackingVelocityParametersGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerAnalogTrackingVelocityParametersSet :  Update dynamic parameters for one axe of a group for a future analog tracking velocity
    def PositionerAnalogTrackingVelocityParametersSet (self, socketId, PositionerName, GPIOName, Offset, Scale, DeadBandThreshold, Order, Velocity, Acceleration):
        command = 'PositionerAnalogTrackingVelocityParametersSet(' + PositionerName + ',' + GPIOName + ',' + str(Offset) + ',' + str(Scale) + ',' + str(DeadBandThreshold) + ',' + str(Order) + ',' + str(Velocity) + ',' + str(Acceleration) + ')'
        return self.Send(socketId, command)

    # PositionerBacklashGet :  Read backlash value and status
    def PositionerBacklashGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double', 'char')
        command = f'PositionerBacklashGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerBacklashSet :  Set backlash value
    def PositionerBacklashSet (self, socketId, PositionerName, BacklashValue):
        command = 'PositionerBacklashSet(' + PositionerName + ',' + str(BacklashValue) + ')'
        return self.Send(socketId, command)

    # PositionerBacklashEnable :  Enable the backlash
    def PositionerBacklashEnable (self, socketId, PositionerName):
        return self.Send(socketId, 'PositionerBacklashEnable(%s)' % PositionerName)

    # PositionerBacklashDisable :  Disable the backlash
    def PositionerBacklashDisable (self, socketId, PositionerName):
        return self.Send(socketId, 'PositionerBacklashDisable(%s)' % PositionerName)

    # PositionerCorrectorNotchFiltersSet :  Update filters parameters
    def PositionerCorrectorNotchFiltersSet (self, socketId, PositionerName, NotchFrequency1, NotchBandwith1, NotchGain1, NotchFrequency2, NotchBandwith2, NotchGain2):
        command = 'PositionerCorrectorNotchFiltersSet(' + PositionerName + ',' + str(NotchFrequency1) + ',' + str(NotchBandwith1) + ',' + str(NotchGain1) + ',' + str(NotchFrequency2) + ',' + str(NotchBandwith2) + ',' + str(NotchGain2) + ')'
        return self.Send(socketId, command)

    # PositionerCorrectorNotchFiltersGet :  Read filters parameters
    def PositionerCorrectorNotchFiltersGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double', 'double', 'double', 'double', 'double', 'double')
        command = f'PositionerCorrectorNotchFiltersGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerCorrectorPIDFFAccelerationSet :  Update corrector parameters
    def PositionerCorrectorPIDFFAccelerationSet (self, socketId, PositionerName, ClosedLoopStatus, KP, KI, KD, KS, IntegrationTime,
                                                 DerivativeFilterCutOffFrequency, GKP, GKI, GKD, KForm, FeedForwardGainAcceleration):
        command = 'PositionerCorrectorPIDFFAccelerationSet(' + PositionerName + ',' + str(ClosedLoopStatus) + ',' + \
                  str(KP) + ',' + str(KI) + ',' + str(KD) + ',' + str(KS) + ',' + str(IntegrationTime) + ',' +\
                  str(DerivativeFilterCutOffFrequency) + ',' + str(GKP) + ',' + str(GKI) + ',' + str(GKD) + ',' + \
                  str(KForm) + ',' + str(FeedForwardGainAcceleration) + ')'
        return self.Send(socketId, command)

    # PositionerCorrectorPIDFFAccelerationGet :  Read corrector parameters
    def PositionerCorrectorPIDFFAccelerationGet (self, socketId, PositionerName):
        outputs = XPSOutputs('bool', 'double', 'double', 'double', 'double', 'double', 'double', 'double', 'double', 'double', 'double', 'double')
        command = f'PositionerCorrectorPIDFFAccelerationGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerCorrectorPIDFFVelocitySet :  Update corrector parameters
    def PositionerCorrectorPIDFFVelocitySet (self, socketId, PositionerName, ClosedLoopStatus, KP, KI, KD, KS, IntegrationTime, DerivativeFilterCutOffFrequency, GKP, GKI, GKD, KForm, FeedForwardGainVelocity):

        command = 'PositionerCorrectorPIDFFVelocitySet(' + PositionerName + ',' + str(ClosedLoopStatus) + ',' + str(KP) + ',' + str(KI) + ',' + str(KD) + ',' + str(KS) + ',' + str(IntegrationTime) + ',' + str(DerivativeFilterCutOffFrequency) + ',' + str(GKP) + ',' + str(GKI) + ',' + str(GKD) + ',' + str(KForm) + ',' + str(FeedForwardGainVelocity) + ')'
        return self.Send(socketId, command)


    # PositionerCorrectorPIDFFVelocityGet :  Read corrector parameters
    def PositionerCorrectorPIDFFVelocityGet (self, socketId, PositionerName):
        outputs = XPSOutputs('bool', 'double', 'double', 'double', 'double', 'double', 'double', 'double', 'double', 'double', 'double', 'double')
        command = f'PositionerCorrectorPIDFFVelocityGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerCorrectorPIDDualFFVoltageSet :  Update corrector parameters
    def PositionerCorrectorPIDDualFFVoltageSet (self, socketId, PositionerName, ClosedLoopStatus, KP, KI, KD, KS, IntegrationTime, DerivativeFilterCutOffFrequency, GKP, GKI, GKD, KForm, FeedForwardGainVelocity, FeedForwardGainAcceleration, Friction):

        command = 'PositionerCorrectorPIDDualFFVoltageSet(' + PositionerName + ',' + str(ClosedLoopStatus) + ',' + str(KP) + ',' + str(KI) + ',' + str(KD) + ',' + str(KS) + ',' + str(IntegrationTime) + ',' + str(DerivativeFilterCutOffFrequency) + ',' + str(GKP) + ',' + str(GKI) + ',' + str(GKD) + ',' + str(KForm) + ',' + str(FeedForwardGainVelocity) + ',' + str(FeedForwardGainAcceleration) + ',' + str(Friction) + ')'
        return self.Send(socketId, command)


    # PositionerCorrectorPIDDualFFVoltageGet :  Read corrector parameters
    def PositionerCorrectorPIDDualFFVoltageGet (self, socketId, PositionerName):
        outputs = XPSOutputs('bool', 'double', 'double', 'double', 'double', 'double', 'double', 'double', 'double', 'double', 'double', 'double', 'double', 'double')
        command = f'PositionerCorrectorPIDDualFFVoltageGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerCorrectorPIPositionSet :  Update corrector parameters
    def PositionerCorrectorPIPositionSet (self, socketId, PositionerName, ClosedLoopStatus, KP, KI, IntegrationTime):
        command = 'PositionerCorrectorPIPositionSet(' + PositionerName + ',' + str(ClosedLoopStatus) + ',' + str(KP) + ',' + str(KI) + ',' + str(IntegrationTime) + ')'
        return self.Send(socketId, command)

    # PositionerCorrectorPIPositionGet :  Read corrector parameters
    def PositionerCorrectorPIPositionGet (self, socketId, PositionerName):
        outputs = XPSOutputs('bool', 'double', 'double', 'double')
        command = f'PositionerCorrectorPIPositionGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerCorrectorTypeGet :  Read corrector type
    def PositionerCorrectorTypeGet (self, socketId, PositionerName):
        return self.Send(socketId, 'PositionerCorrectorTypeGet(%s, char *)' % PositionerName)

    # PositionerCurrentVelocityAccelerationFiltersGet :  Get current velocity and acceleration cutoff frequencies
    def PositionerCurrentVelocityAccelerationFiltersGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double', 'double')
        command = f'PositionerCurrentVelocityAccelerationFiltersGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerCurrentVelocityAccelerationFiltersSet :  Set current velocity and acceleration cutoff frequencies
    def PositionerCurrentVelocityAccelerationFiltersSet (self, socketId, PositionerName, CurrentVelocityCutOffFrequency, CurrentAccelerationCutOffFrequency):
        command = 'PositionerCurrentVelocityAccelerationFiltersSet(' + PositionerName + ',' + str(CurrentVelocityCutOffFrequency) + ',' + str(CurrentAccelerationCutOffFrequency) + ')'
        return self.Send(socketId, command)

    # PositionerDriverFiltersGet :  Get driver filters parameters
    def PositionerDriverFiltersGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double', 'double', 'double', 'double', 'double')
        command = f'PositionerDriverFiltersGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerDriverFiltersSet :  Set driver filters parameters
    def PositionerDriverFiltersSet (self, socketId, PositionerName, KI, NotchFrequency, NotchBandwidth, NotchGain, LowpassFrequency):
        command = 'PositionerDriverFiltersSet(' + PositionerName + ',' + str(KI) + ',' + str(NotchFrequency) + ',' + str(NotchBandwidth) + ',' + str(NotchGain) + ',' + str(LowpassFrequency) + ')'
        return self.Send(socketId, command)

    # PositionerDriverPositionOffsetsGet :  Get driver stage and gage position offset
    def PositionerDriverPositionOffsetsGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double', 'double')
        command = f'PositionerDriverPositionOffsetsGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerDriverStatusGet :  Read positioner driver status
    def PositionerDriverStatusGet (self, socketId, PositionerName):
        outputs = XPSOutputs('int')
        command = f'PositionerDriverStatusGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerDriverStatusStringGet :  Return the positioner driver status string corresponding to the positioner error code
    def PositionerDriverStatusStringGet (self, socketId, PositionerDriverStatus):
        command = 'PositionerDriverStatusStringGet(' + str(PositionerDriverStatus) + ',char *)'
        return self.Send(socketId, command)

    # PositionerEncoderAmplitudeValuesGet :  Read analog interpolated encoder amplitude values
    def PositionerEncoderAmplitudeValuesGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double', 'double', 'double', 'double')
        command = f'PositionerEncoderAmplitudeValuesGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerEncoderCalibrationParametersGet :  Read analog interpolated encoder calibration parameters
    def PositionerEncoderCalibrationParametersGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double', 'double', 'double', 'double')
        command = f'PositionerEncoderCalibrationParametersGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerErrorGet :  Read and clear positioner error code
    def PositionerErrorGet (self, socketId, PositionerName):
        outputs = XPSOutputs('int')
        command = f'PositionerErrorGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerErrorRead :  Read only positioner error code without clear it
    def PositionerErrorRead (self, socketId, PositionerName):
        outputs = XPSOutputs('int')
        command = f'PositionerErrorRead({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerErrorStringGet :  Return the positioner status string corresponding to the positioner error code
    def PositionerErrorStringGet (self, socketId, PositionerErrorCode):
        return self.Send(socketId, 'PositionerErrorStringGet(%s, char *)' % str(PositionerErrorCode))

    # PositionerExcitationSignalGet :  Read disturbing signal parameters
    def PositionerExcitationSignalGet (self, socketId, PositionerName):
        outputs = XPSOutputs('int', 'double', 'double', 'double')
        command = f'PositionerExcitationSignalGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerExcitationSignalSet :  Update disturbing signal parameters
    def PositionerExcitationSignalSet (self, socketId, PositionerName, Mode, Frequency, Amplitude, Time):
        command = 'PositionerExcitationSignalSet(' + PositionerName + ',' + str(Mode) + ',' + str(Frequency) + ',' + str(Amplitude) + ',' + str(Time) + ')'
        return self.Send(socketId, command)

    # PositionerExternalLatchPositionGet :  Read external latch position
    def PositionerExternalLatchPositionGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double')
        command = f'PositionerExternalLatchPositionGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerHardwareStatusGet :  Read positioner hardware status
    def PositionerHardwareStatusGet (self, socketId, PositionerName):
        outputs = XPSOutputs('int')
        command = f'PositionerHardwareStatusGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerHardwareStatusStringGet :  Return the positioner hardware status string corresponding to the positioner error code
    def PositionerHardwareStatusStringGet (self, socketId, PositionerHardwareStatus):
        return self.Send(socketId, 'PositionerHardwareStatusStringGet(%s, char *)' % str(PositionerHardwareStatus))

    # PositionerHardInterpolatorFactorGet :  Get hard interpolator parameters
    def PositionerHardInterpolatorFactorGet (self, socketId, PositionerName):
        outputs = XPSOutputs('int')
        command = f'PositionerHardInterpolatorFactorGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerHardInterpolatorFactorSet :  Set hard interpolator parameters
    def PositionerHardInterpolatorFactorSet (self, socketId, PositionerName, InterpolationFactor):
        command = 'PositionerHardInterpolatorFactorSet(' + PositionerName + ',' + str(InterpolationFactor) + ')'
        return self.Send(socketId, command)

    # PositionerMaximumVelocityAndAccelerationGet :  Return maximum velocity and acceleration of the positioner
    def PositionerMaximumVelocityAndAccelerationGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double', 'double')
        command = f'PositionerMaximumVelocityAndAccelerationGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerMotionDoneGet :  Read motion done parameters
    def PositionerMotionDoneGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double', 'double', 'double', 'double', 'double')
        command = f'PositionerMotionDoneGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerMotionDoneSet :  Update motion done parameters
    def PositionerMotionDoneSet (self, socketId, PositionerName, PositionWindow, VelocityWindow, CheckingTime, MeanPeriod, TimeOut):
        command = 'PositionerMotionDoneSet(' + PositionerName + ',' + str(PositionWindow) + ',' + str(VelocityWindow) + ',' + str(CheckingTime) + ',' + str(MeanPeriod) + ',' + str(TimeOut) + ')'
        return self.Send(socketId, command)

    # PositionerPositionCompareAquadBAlwaysEnable :  Enable AquadB signal in always mode
    def PositionerPositionCompareAquadBAlwaysEnable (self, socketId, PositionerName):
        command = 'PositionerPositionCompareAquadBAlwaysEnable(' + PositionerName + ')'
        return self.Send(socketId, command)

    # PositionerPositionCompareAquadBWindowedGet :  Read position compare AquadB windowed parameters
    def PositionerPositionCompareAquadBWindowedGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double', 'double', 'bool')
        command = f'PositionerPositionCompareAquadBWindowedGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerPositionCompareAquadBWindowedSet :  Set position compare AquadB windowed parameters
    def PositionerPositionCompareAquadBWindowedSet (self, socketId, PositionerName, MinimumPosition, MaximumPosition):
        command = 'PositionerPositionCompareAquadBWindowedSet(' + PositionerName + ',' + str(MinimumPosition) + ',' + str(MaximumPosition) + ')'
        return self.Send(socketId, command)

    # PositionerPositionCompareAquadBPrescalerSet: Sets PCO AquadB interpolation factor.
    def PositionerPositionCompareAquadBPrescalerSet(self, socketId, PositionerName, PCOInterpolationFactor):
        command = 'PositionerPositionCompareAquadBPrescalerSet(' + PositionerName + ',' + str(
            PCOInterpolationFactor) + ')'
        return self.Send(socketId, command)

    # PositionerPositionCompareAquadBPrescalerGet : Gets PCO AquadB interpolation factor.
    def PositionerPositionCompareAquadBPrescalerGet(self, socketId, PositionerName):
        outputs = XPSOutputs('double')
        command = f'PositionerPositionCompareAquadBPrescalerGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerPositionCompareGet :  Read position compare parameters
    def PositionerPositionCompareGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double', 'double', 'double', 'bool')
        command = f'PositionerPositionCompareGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerPositionCompareSet :  Set position compare parameters
    def PositionerPositionCompareSet (self, socketId, PositionerName, MinimumPosition, MaximumPosition, PositionStep):
        command = 'PositionerPositionCompareSet(' + PositionerName + ',' + str(MinimumPosition) + ',' + str(MaximumPosition) + ',' + str(PositionStep) + ')'
        return self.Send(socketId, command)

    # PositionerPositionCompareEnable :  Enable position compare
    def PositionerPositionCompareEnable (self, socketId, PositionerName):
        command = 'PositionerPositionCompareEnable(' + PositionerName + ')'
        return self.Send(socketId, command)

    # PositionerPositionCompareDisable :  Disable position compare
    def PositionerPositionCompareDisable (self, socketId, PositionerName):
        command = 'PositionerPositionCompareDisable(' + PositionerName + ')'
        return self.Send(socketId, command)

    # PositionerPositionComparePulseParametersGet :  Get position compare PCO pulse parameters
    def PositionerPositionComparePulseParametersGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double', 'double')
        command = f'PositionerPositionComparePulseParametersGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerPositionComparePulseParametersSet :  Set position compare PCO pulse parameters
    def PositionerPositionComparePulseParametersSet (self, socketId, PositionerName, PCOPulseWidth, EncoderSettlingTime):
        command = 'PositionerPositionComparePulseParametersSet(' + PositionerName + ',' + str(PCOPulseWidth) + ',' + str(EncoderSettlingTime) + ')'
        return self.Send(socketId, command)

    # PositionerRawEncoderPositionGet :  Get the raw encoder position
    def PositionerRawEncoderPositionGet (self, socketId, PositionerName, UserEncoderPosition):
        outputs = XPSOutputs('double')
        command = f'PositionerRawEncoderPositionGet({PositionerName},{UserEncoderPosition},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionersEncoderIndexDifferenceGet :  Return the difference between index of primary axis and secondary axis (only after homesearch)
    def PositionersEncoderIndexDifferenceGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double')
        command = f'PositionersEncoderIndexDifferenceGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerSGammaExactVelocityAjustedDisplacementGet :  Return adjusted displacement to get exact velocity
    def PositionerSGammaExactVelocityAjustedDisplacementGet (self, socketId, PositionerName, DesiredDisplacement):
        outputs = XPSOutputs('double')
        command = f'PositionerSGammaExactVelocityAjustedDisplacementGet({PositionerName},{DesiredDisplacement},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerSGammaParametersGet :  Read dynamic parameters for one axe of a group for a future displacement
    def PositionerSGammaParametersGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double', 'double', 'double', 'double')
        command = f'PositionerSGammaParametersGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerSGammaParametersSet :  Update dynamic parameters for one axe of a group for a future displacement
    def PositionerSGammaParametersSet (self, socketId, PositionerName, Velocity, Acceleration, MinimumTjerkTime, MaximumTjerkTime):
        command = 'PositionerSGammaParametersSet(' + PositionerName + ',' + str(Velocity) + ',' + str(Acceleration) + ',' + str(MinimumTjerkTime) + ',' + str(MaximumTjerkTime) + ')'
        return self.Send(socketId, command)

    # PositionerSGammaPreviousMotionTimesGet :  Read SettingTime and SettlingTime
    def PositionerSGammaPreviousMotionTimesGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double', 'double')
        command = f'PositionerSGammaPreviousMotionTimesGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerStageParameterGet :  Return the stage parameter
    def PositionerStageParameterGet (self, socketId, PositionerName, ParameterName):
        command = 'PositionerStageParameterGet(' + PositionerName + ',' + ParameterName + ',char *)'
        return self.Send(socketId, command)

    # PositionerStageParameterSet :  Save the stage parameter
    def PositionerStageParameterSet (self, socketId, PositionerName, ParameterName, ParameterValue):
        command = 'PositionerStageParameterSet(' + PositionerName + ',' + ParameterName + ',' + ParameterValue + ')'
        return self.Send(socketId, command)

    # PositionerTimeFlasherGet :  Read time flasher parameters
    def PositionerTimeFlasherGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double', 'double', 'double', 'bool')
        command = f'PositionerTimeFlasherGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerTimeFlasherSet :  Set time flasher parameters
    def PositionerTimeFlasherSet (self, socketId, PositionerName, MinimumPosition, MaximumPosition, TimeInterval):
        command = 'PositionerTimeFlasherSet(' + PositionerName + ',' + str(MinimumPosition) + ',' + str(MaximumPosition) + ',' + str(TimeInterval) + ')'
        return self.Send(socketId, command)

    # PositionerTimeFlasherEnable :  Enable time flasher
    def PositionerTimeFlasherEnable (self, socketId, PositionerName):
        return self.Send(socketId,  'PositionerTimeFlasherEnable(%s)' % PositionerName )

    # PositionerTimeFlasherDisable :  Disable time flasher
    def PositionerTimeFlasherDisable (self, socketId, PositionerName):
        return self.Send(socketId, 'PositionerTimeFlasherDisable(%s)' % PositionerName)

    # PositionerUserTravelLimitsGet :  Read UserMinimumTarget and UserMaximumTarget
    def PositionerUserTravelLimitsGet (self, socketId, PositionerName):
        outputs = XPSOutputs('double', 'double')
        command = f'PositionerUserTravelLimitsGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerUserTravelLimitsSet :  Update UserMinimumTarget and UserMaximumTarget
    def PositionerUserTravelLimitsSet (self, socketId, PositionerName, UserMinimumTarget, UserMaximumTarget):
        command = 'PositionerUserTravelLimitsSet(' + PositionerName + ',' + str(UserMinimumTarget) + ',' + str(UserMaximumTarget) + ')'
        return self.Send(socketId, command)

    # PositionerDACOffsetGet :  Get DAC offsets
    def PositionerDACOffsetGet (self, socketId, PositionerName):
        outputs = XPSOutputs('short', 'short')
        command = f'PositionerDACOffsetGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerDACOffsetSet :  Set DAC offsets
    def PositionerDACOffsetSet (self, socketId, PositionerName, DACOffset1, DACOffset2):
        command = 'PositionerDACOffsetSet(' + PositionerName + ',' + str(DACOffset1) + ',' + str(DACOffset2) + ')'
        return self.Send(socketId, command)

    # PositionerDACOffsetDualGet :  Get dual DAC offsets
    def PositionerDACOffsetDualGet (self, socketId, PositionerName):
        outputs = XPSOutputs('short', 'short', 'short', 'short')
        command = f'PositionerDACOffsetDualGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerDACOffsetDualSet :  Set dual DAC offsets
    def PositionerDACOffsetDualSet (self, socketId, PositionerName, PrimaryDACOffset1, PrimaryDACOffset2, SecondaryDACOffset1, SecondaryDACOffset2):
        command = 'PositionerDACOffsetDualSet(' + PositionerName + ',' + str(PrimaryDACOffset1) + ',' + str(PrimaryDACOffset2) + ',' + str(SecondaryDACOffset1) + ',' + str(SecondaryDACOffset2) + ')'
        return self.Send(socketId, command)

    # PositionerCorrectorAutoTuning :  Astrom&Hagglund based auto-tuning
    def PositionerCorrectorAutoTuning (self, socketId, PositionerName, TuningMode):
        outputs = XPSOutputs('double', 'double', 'double')
        command = f'PositionerCorrectorAutoTuning({PositionerName},{TuningMode},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # PositionerAccelerationAutoScaling :  Astrom&Hagglund based auto-scaling
    def PositionerAccelerationAutoScaling (self, socketId, PositionerName):
        outputs = XPSOutputs('double')
        command = f'PositionerAccelerationAutoScaling({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # MultipleAxesPVTVerification :  Multiple axes PVT trajectory verification
    def MultipleAxesPVTVerification (self, socketId, GroupName, TrajectoryFileName):
        command = 'MultipleAxesPVTVerification(' + GroupName + ',' + TrajectoryFileName + ')'
        return self.Send(socketId, command)
    
    # MultipleAxesPTVerification :  Multiple axes PT trajectory verification
    def MultipleAxesPTVerification (self, socketId, GroupName, TrajectoryFileName):
        command = 'MultipleAxesPTVerification(' + GroupName + ',' + TrajectoryFileName + ')'
        return self.Send(socketId, command)

    # MultipleAxesPVTVerificationResultGet :  Multiple axes PVT trajectory verification result get
    def MultipleAxesPVTVerificationResultGet (self, socketId, PositionerName):
        outputs = XPSOutputs('char', 'double', 'double', 'double', 'double')
        command = f'MultipleAxesPVTVerificationResultGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # MultipleAxesPVTExecution :  Multiple axes PVT trajectory execution
    def MultipleAxesPVTExecution (self, socketId, GroupName, TrajectoryFileName, ExecutionNumber):
        command = 'MultipleAxesPVTExecution(' + GroupName + ',' + TrajectoryFileName + ',' + str(ExecutionNumber) + ')'
        return self.Send(socketId, command)
    
    # MultipleAxesPTExecution :  Multiple axes PT trajectory execution
    def MultipleAxesPTExecution (self, socketId, GroupName, TrajectoryFileName, ExecutionNumber):
        command = 'MultipleAxesPTExecution(' + GroupName + ',' + TrajectoryFileName + ',' + str(ExecutionNumber) + ')'
        return self.Send(socketId, command)

    # MultipleAxesPVTParametersGet :  Multiple axes PVT trajectory get parameters
    def MultipleAxesPVTParametersGet (self, socketId, GroupName):
        outputs = XPSOutputs('char', 'int')
        command = f'MultipleAxesPVTParametersGet({GroupName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # MultipleAxesPVTPulseOutputSet :  Configure pulse output on trajectory
    def MultipleAxesPVTPulseOutputSet (self, socketId, GroupName, StartElement, EndElement, TimeInterval):
        command = 'MultipleAxesPVTPulseOutputSet(' + GroupName + ',' + str(StartElement) + ',' + str(EndElement) + ',' + str(TimeInterval) + ')'
        return self.Send(socketId, command)

    # MultipleAxesPVTPulseOutputGet :  Get pulse output on trajectory configuration
    def MultipleAxesPVTPulseOutputGet (self, socketId, GroupName):
        outputs = XPSOutputs('int', 'int', 'double')
        command = f'MultipleAxesPVTPulseOutputGet({GroupName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # SingleAxisSlaveModeEnable :  Enable the slave mode
    def SingleAxisSlaveModeEnable (self, socketId, GroupName):
        return self.Send(socketId, 'SingleAxisSlaveModeEnable(%s)' % GroupName)

    # SingleAxisSlaveModeDisable :  Disable the slave mode
    def SingleAxisSlaveModeDisable (self, socketId, GroupName):
        return self.Send(socketId, 'SingleAxisSlaveModeDisable(%s)' % GroupName)

    # SingleAxisSlaveParametersSet :  Set slave parameters
    def SingleAxisSlaveParametersSet (self, socketId, GroupName, PositionerName, Ratio):
        command = 'SingleAxisSlaveParametersSet(' + GroupName + ',' + PositionerName + ',' + str(Ratio) + ')'
        return self.Send(socketId, command)

    # SingleAxisSlaveParametersGet :  Get slave parameters
    def SingleAxisSlaveParametersGet (self, socketId, GroupName):
        outputs = XPSOutputs('char', 'double')
        command = f'SingleAxisSlaveParametersGet({GroupName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # SpindleSlaveModeEnable :  Enable the slave mode
    def SpindleSlaveModeEnable (self, socketId, GroupName):
        return self.Send(socketId, 'SpindleSlaveModeEnable(%s)' % GroupName)

    # SpindleSlaveModeDisable :  Disable the slave mode
    def SpindleSlaveModeDisable (self, socketId, GroupName):
        return self.Send(socketId, 'SpindleSlaveModeDisable(%s)' % GroupName)

    # SpindleSlaveParametersSet :  Set slave parameters
    def SpindleSlaveParametersSet (self, socketId, GroupName, PositionerName, Ratio):
        command = 'SpindleSlaveParametersSet(' + GroupName + ',' + PositionerName + ',' + str(Ratio) + ')'
        return self.Send(socketId, command)

    # SpindleSlaveParametersGet :  Get slave parameters
    def SpindleSlaveParametersGet (self, socketId, GroupName):
        outputs = XPSOutputs('char', 'double')
        command = f'SpindleSlaveParametersGet({GroupName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GroupSpinParametersSet :  Modify Spin parameters on selected group and activate the continuous move
    def GroupSpinParametersSet (self, socketId, GroupName, Velocity, Acceleration):
        command = 'GroupSpinParametersSet(' + GroupName + ',' + str(Velocity) + ',' + str(Acceleration) + ')'
        return self.Send(socketId, command)

    # GroupSpinParametersGet :  Get Spin parameters on selected group
    def GroupSpinParametersGet (self, socketId, GroupName):
        outputs = XPSOutputs('double', 'double')
        command = f'GroupSpinParametersGet({GroupName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GroupSpinCurrentGet :  Get Spin current on selected group
    def GroupSpinCurrentGet (self, socketId, GroupName):
        outputs = XPSOutputs('double', 'double')
        command = f'GroupSpinCurrentGet({GroupName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # GroupSpinModeStop :  Stop Spin mode on selected group with specified acceleration
    def GroupSpinModeStop (self, socketId, GroupName, Acceleration):
        command = 'GroupSpinModeStop(' + GroupName + ',' + str(Acceleration) + ')'
        return self.Send(socketId, command)

    # XYLineArcVerification :  XY trajectory verification
    def XYLineArcVerification (self, socketId, GroupName, TrajectoryFileName):
        command = 'XYLineArcVerification(' + GroupName + ',' + TrajectoryFileName + ')'
        return self.Send(socketId, command)

    # XYLineArcVerificationResultGet :  XY trajectory verification result get
    def XYLineArcVerificationResultGet (self, socketId, PositionerName):
        outputs = XPSOutputs('char', 'double', 'double', 'double', 'double')
        command = f'XYLineArcVerificationResultGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # XYLineArcExecution :  XY trajectory execution
    def XYLineArcExecution (self, socketId, GroupName, TrajectoryFileName, Velocity, Acceleration, ExecutionNumber):
        command = 'XYLineArcExecution(' + GroupName + ',' + TrajectoryFileName + ',' + str(Velocity) + ',' + str(Acceleration) + ',' + str(ExecutionNumber) + ')'
        return self.Send(socketId, command)

    # XYLineArcParametersGet :  XY trajectory get parameters
    def XYLineArcParametersGet (self, socketId, GroupName):
        outputs = XPSOutputs('char', 'double', 'double', 'int')
        command = f'XYLineArcParametersGet({GroupName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # XYLineArcPulseOutputSet :  Configure pulse output on trajectory
    def XYLineArcPulseOutputSet (self, socketId, GroupName, StartLength, EndLength, PathLengthInterval):
        command = 'XYLineArcPulseOutputSet(' + GroupName + ',' + str(StartLength) + ',' + str(EndLength) + ',' + str(PathLengthInterval) + ')'
        return self.Send(socketId, command)

    # XYLineArcPulseOutputGet :  Get pulse output on trajectory configuration
    def XYLineArcPulseOutputGet (self, socketId, GroupName):
        outputs = XPSOutputs('double', 'double', 'double')
        command = f'XYLineArcPulseOutputGet({GroupName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # XYZGroupPositionCorrectedProfilerGet :  Return corrected profiler positions
    def XYZGroupPositionCorrectedProfilerGet (self, socketId, GroupName, PositionX, PositionY, PositionZ):
        outputs = XPSOutputs('double', 'double', 'double')
        command = f'XYZGroupPositionCorrectedProfilerGet({GroupName},{PositionX},{PositionY},{PositionZ},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # XYZSplineVerification :  XYZ trajectory verifivation
    def XYZSplineVerification (self, socketId, GroupName, TrajectoryFileName):
        command = 'XYZSplineVerification(' + GroupName + ',' + TrajectoryFileName + ')'
        return self.Send(socketId, command)

    # XYZSplineVerificationResultGet :  XYZ trajectory verification result get
    def XYZSplineVerificationResultGet (self, socketId, PositionerName):
        outputs = XPSOutputs('char', 'double', 'double', 'double', 'double')
        command = f'XYZSplineVerificationResultGet({PositionerName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # XYZSplineExecution :  XYZ trajectory execution
    def XYZSplineExecution (self, socketId, GroupName, TrajectoryFileName, Velocity, Acceleration):
        command = 'XYZSplineExecution(' + GroupName + ',' + TrajectoryFileName + ',' + str(Velocity) + ',' + str(Acceleration) + ')'
        return self.Send(socketId, command)

    # XYZSplineParametersGet :  XYZ trajectory get parameters
    def XYZSplineParametersGet (self, socketId, GroupName):
        outputs = XPSOutputs('char', 'double', 'double', 'int')
        command = f'XYZSplineParametersGet({GroupName},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # OptionalModuleExecute :  Execute an optional module
    def OptionalModuleExecute (self, socketId, ModuleFileName, TaskName):
        return self.Send(socketId, 'OptionalModuleExecute(%s, %s)' % (ModuleFileName, TaskName))

    # OptionalModuleKill :  Kill an optional module
    def OptionalModuleKill (self, socketId, TaskName):
        return self.Send(socketId, 'OptionalModuleKill(%s)' % TaskName )

    # EEPROMCIESet :  Set CIE EEPROM reference string
    def EEPROMCIESet (self, socketId, CardNumber, ReferenceString):
        return self.Send(socketId, 'EEPROMCIESet(%s, %s)' % (str(CardNumber), ReferenceString))

    # EEPROMDACOffsetCIESet :  Set CIE DAC offsets
    def EEPROMDACOffsetCIESet (self, socketId, PlugNumber, DAC1Offset, DAC2Offset):
        command = 'EEPROMDACOffsetCIESet(' + str(PlugNumber) + ',' + str(DAC1Offset) + ',' + str(DAC2Offset) + ')'
        return self.Send(socketId, command)

    # EEPROMDriverSet :  Set Driver EEPROM reference string
    def EEPROMDriverSet (self, socketId, PlugNumber, ReferenceString):
        return self.Send(socketId, 'EEPROMDriverSet(%s, %s)' % (str(PlugNumber), ReferenceString))

    # EEPROMINTSet :  Set INT EEPROM reference string
    def EEPROMINTSet (self, socketId, CardNumber, ReferenceString):
        return self.Send(socketId, 'EEPROMINTSet(%s, %s)' % (str(CardNumber), ReferenceString))

    # CPUCoreAndBoardSupplyVoltagesGet :  Get power informations
    def CPUCoreAndBoardSupplyVoltagesGet (self, socketId):
        outputs = XPSOutputs('double', 'double', 'double', 'double', 'double', 'double', 'double', 'double')
        command = f'CPUCoreAndBoardSupplyVoltagesGet({outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # CPUTemperatureAndFanSpeedGet :  Get CPU temperature and fan speed
    def CPUTemperatureAndFanSpeedGet (self, socketId):
        outputs = XPSOutputs('double', 'double')
        command = f'CPUTemperatureAndFanSpeedGet({outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # ActionListGet :  Action list
    def ActionListGet (self, socketId):
        return self.Send(socketId, 'ActionListGet(char *)')

    # ActionExtendedListGet :  Action extended list
    def ActionExtendedListGet (self, socketId):
        return self.Send(socketId, 'ActionExtendedListGet(char *)')

    # APIExtendedListGet :  API method list
    def APIExtendedListGet (self, socketId):
        return self.Send(socketId, 'APIExtendedListGet(char *)')

    # APIListGet :  API method list without extended API
    def APIListGet (self, socketId):
        return self.Send(socketId, 'APIListGet(char *)')

    # ControllerStatusListGet :  Controller status list
    def ControllerStatusListGet (self, socketId):
        return self.Send(socketId, 'ControllerStatusListGet(char *)')

    # ErrorListGet :  Error list
    def ErrorListGet (self, socketId):
        return self.Send(socketId, 'ErrorListGet(char *)')

    # EventListGet :  General event list
    def EventListGet (self, socketId):
        return self.Send(socketId, 'EventListGet(char *)')

    # GatheringListGet :  Gathering type list
    def GatheringListGet (self, socketId):
        return self.Send(socketId,'GatheringListGet(char *)')

    # GatheringExtendedListGet :  Gathering type extended list
    def GatheringExtendedListGet (self, socketId):
        return self.Send(socketId, 'GatheringExtendedListGet(char *)')

    # GatheringExternalListGet :  External Gathering type list
    def GatheringExternalListGet (self, socketId):
        return self.Send(socketId, 'GatheringExternalListGet(char *)')

    # GroupStatusListGet :  Group status list
    def GroupStatusListGet (self, socketId):
        return self.Send(socketId, 'GroupStatusListGet(char *)')

    # HardwareInternalListGet :  Internal hardware list
    def HardwareInternalListGet (self, socketId):
        return self.Send(socketId, 'HardwareInternalListGet(char *)')

    # HardwareDriverAndStageGet :  Smart hardware
    def HardwareDriverAndStageGet (self, socketId, PlugNumber):
        outputs = XPSOutputs('char', 'char')
        command = f'HardwareDriverAndStageGet({PlugNumber},{outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # ObjectsListGet :  Group name and positioner name
    def ObjectsListGet (self, socketId):
        return self.Send(socketId, 'ObjectsListGet(char *)')

    # PositionerErrorListGet :  Positioner error list
    def PositionerErrorListGet (self, socketId):
        return self.Send(socketId, 'PositionerErrorListGet(char *)')

    # PositionerHardwareStatusListGet :  Positioner hardware status list
    def PositionerHardwareStatusListGet (self, socketId):
        return self.Send(socketId, 'PositionerHardwareStatusListGet(char *)')

    # PositionerDriverStatusListGet :  Positioner driver status list
    def PositionerDriverStatusListGet (self, socketId):
        return self.Send(socketId, 'PositionerDriverStatusListGet(char *)')

    # ReferencingActionListGet :  Get referencing action list
    def ReferencingActionListGet (self, socketId):
        return self.Send(socketId, 'ReferencingActionListGet(char *)')

    # ReferencingSensorListGet :  Get referencing sensor list
    def ReferencingSensorListGet (self, socketId):
        return self.Send(socketId, 'ReferencingSensorListGet(char *)')

    # GatheringUserDatasGet :  Return user data values
    def GatheringUserDatasGet (self, socketId):
        outputs = XPSOutputs('double', 'double', 'double', 'double', 'double', 'double', 'double', 'double')
        command = f'GatheringUserDatasGet({outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # ControllerMotionKernelPeriodMinMaxGet :  Get controller motion kernel min/max periods
    def ControllerMotionKernelPeriodMinMaxGet (self, socketId):
        outputs = XPSOutputs('double', 'double', 'double', 'double', 'double', 'double')
        command = f'ControllerMotionKernelPeriodMinMaxGet({outputs})'
        error, returnedString = self.Send(socketId, command)
        return outputs.parse(error, returnedString)

    # ControllerMotionKernelPeriodMinMaxReset :  Reset controller motion kernel min/max periods
    def ControllerMotionKernelPeriodMinMaxReset (self, socketId):
        return self.Send(socketId, 'ControllerMotionKernelPeriodMinMaxReset()')

    # SocketsStatusGet :  Get sockets current status
    def SocketsStatusGet (self, socketId):
        return self.Send(socketId, 'SocketsStatusGet(char *)')

    # TestTCP :  Test TCP/IP transfert
    def TestTCP (self, socketId, InputString):
        return self.Send(socketId, 'TestTCP(%s, char *)' % InputString)

    # ========== Only for XPS-D ==========

    # CleanCoreDumpFolder :   Remove core file in /Admin/Public/CoreDump folder
    def CleanCoreDumpFolder (self, socketId):
        return self.Send(socketId, 'CleanCoreDumpFolder()')

    # CleanTmpFolder :   Clean the tmp folder
    def CleanTmpFolder(self, socketId):
        return self.Send(socketId, 'CleanTmpFolder()')
