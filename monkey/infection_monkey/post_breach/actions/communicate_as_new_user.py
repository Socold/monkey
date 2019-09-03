import os
import random
import string
import subprocess

import win32api
import win32con
import win32process
import win32security

from common.data.post_breach_consts import POST_BREACH_COMMUNICATE_AS_NEW_USER
from infection_monkey.post_breach.actions.add_user import BackdoorUser
from infection_monkey.post_breach.pba import PBA
from infection_monkey.telemetry.post_breach_telem import PostBreachTelem
from infection_monkey.utils import is_windows_os

USERNAME = "somenewuser"
PASSWORD = "N3WPa55W0rD!@12"


class CommunicateAsNewUser(PBA):
    """
    This PBA creates a new user, and then pings google as that user. This is used for a Zero Trust test of the People
    pillar. See the relevant telemetry processing to see what findings are created.
    """

    def __init__(self):
        super(CommunicateAsNewUser, self).__init__(name=POST_BREACH_COMMUNICATE_AS_NEW_USER)

    def run(self):
        username = USERNAME + ''.join(random.choice(string.ascii_lowercase) for _ in range(5))
        if is_windows_os():
            if not self.try_to_create_user_windows(username, PASSWORD):
                return  # no point to continue if failed creating the user.

            # Logon as new user: https://docs.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-logonusera
            new_user_logon_token_handle = win32security.LogonUser(
                username,
                ".",  # current domain
                PASSWORD,
                win32con.LOGON32_LOGON_BATCH,  # logon type
                win32con.LOGON32_PROVIDER_DEFAULT)  # logon provider

            if new_user_logon_token_handle == 0:
                PostBreachTelem(
                    self,
                    ("Can't logon as {} Last error: {}".format(username, win32api.GetLastError()), False)
                ).send()
                return  # no point to continue if can't log on.

            # Using os.path is OK, as this is on windows for sure
            ping_app_path = os.path.join(os.environ["WINDIR"], "system32", "PING.exe")
            if not os.path.exists(ping_app_path):
                PostBreachTelem(self, ("{} not found".format(ping_app_path), False)).send()
                return  # Can't continue without ping.

            # Open process as that user:
            # https://docs.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessasusera
            return_value_create_process = win32process.CreateProcessAsUser(
                new_user_logon_token_handle,  # A handle to the primary token that represents a user.
                # If both lpApplicationName and lpCommandLine are non-NULL, *lpApplicationName specifies the module
                # to execute, and *lpCommandLine specifies the command line.
                ping_app_path,  # The name of the module to be executed.
                "google.com",  # The command line to be executed.
                None,  # Process attributes
                None,  # Thread attributes
                True,  # Should inherit handles
                win32con.NORMAL_PRIORITY_CLASS,  # The priority class and the creation of the process.
                None,  # An environment block for the new process. If this parameter is NULL, the new process
                # uses the environment of the calling process.
                None,  # CWD. If this parameter is NULL, the new process will have the same current drive and
                # directory as the calling process.
                win32process.STARTUPINFO()  # STARTUPINFO structure.
                # https://docs.microsoft.com/en-us/windows/win32/api/processthreadsapi/ns-processthreadsapi-startupinfoa
            )

            if return_value_create_process == 0:
                PostBreachTelem(self, (
                    "Failed to open process as user. Last error: {}".format(win32api.GetLastError()), False)).send()
                return
        else:
            try:
                linux_cmds = BackdoorUser.get_linux_commands_to_add_user(username)
                linux_cmds.extend([";", "sudo", "-", username, "-c", "'ping -c 2 google.com'"])
                subprocess.check_output(linux_cmds, stderr=subprocess.STDOUT, shell=True)
            except subprocess.CalledProcessError as e:
                PostBreachTelem(self, (e.output, False)).send()
                return

    def try_to_create_user_windows(self, username, password):
        try:
            windows_cmds = BackdoorUser.get_windows_commands_to_add_user(username, password)
            subprocess.check_output(windows_cmds, stderr=subprocess.STDOUT, shell=True)
            return True
        except subprocess.CalledProcessError as e:
            PostBreachTelem(self, (
                "Couldn't create the user '{}'. Error output is: '{}'".format(username, e.output), False)).send()
            return False