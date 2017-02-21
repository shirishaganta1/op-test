#!/usr/bin/python
# IBM_PROLOG_BEGIN_TAG
# This is an automatically generated prolog.
#
# $Source: op-test-framework/testcases/OpTestHMIHandling.py $
#
# OpenPOWER Automated Test Project
#
# Contributors Listed Below - COPYRIGHT 2015
# [+] International Business Machines Corp.
#
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied. See the License for the specific language governing
# permissions and limitations under the License.
#
# IBM_PROLOG_END_TAG

# @package OpTestHMIHandling
#  HMI Handling package for OpenPower testing.
#
#  This class will test the functionality of following.
#  1. HMI Non-recoverable errors - Core checkstop and Hypervisor resource error
#  2. HMI Recoverable errors- proc_recv_done, proc_recv_error_masked and proc_recv_again
#  3. TFMR error injections
#  4. chip TOD error injections

import time
import subprocess
import re
import sys
import os
import random

import unittest

import OpTestConfiguration
from common.OpTestUtil import OpTestUtil
from common.OpTestSystem import OpSystemState
from common.OpTestConstants import OpTestConstants as BMC_CONST

class OpTestHMIHandling(unittest.TestCase):
    def setUp(self):
        conf = OpTestConfiguration.conf
        self.cv_HOST = conf.host()
        self.cv_IPMI = conf.ipmi()
        self.cv_SYSTEM = conf.system()
        self.util = OpTestUtil()

    def init_test(self):
        self.cv_SYSTEM.goto_state(OpSystemState.OS)

        # Getting list of processor chip Id's(executing getscom -l to get chip id's)
        l_res = self.cv_HOST.host_run_command("PATH=/usr/local/sbin:$PATH getscom -l")
        l_res = l_res.splitlines()
        l_chips = []
        for line in l_res:
            matchObj = re.search("(\d{8}).*processor", line)
            if matchObj:
                l_chips.append(matchObj.group(1))
        if not l_chips:
            raise Exception("Getscom failed to list processor chip ids")
        l_chips.sort()
        print l_chips # ['00000000', '00000001', '00000010']

        # Currently getting the list of active core id's with respect to each chip is by using opal msg log
        # TODO: Need to identify best way to get list of cores(If Opal msg log is empty)
        l_cmd = "cat /sys/firmware/opal/msglog | grep -i CHIP"
        l_res = self.cv_HOST.host_run_command(l_cmd)
        l_cores = {}
        self.l_dic = []
        l_res = l_res.splitlines()
        for line in l_res:
            matchObj = re.search("Chip (\d{1,2}) Core ([a-z0-9])", line)
            if matchObj:
                if l_cores.has_key(int(matchObj.group(1))):
                    (l_cores[int(matchObj.group(1))]).append(matchObj.group(2))
                else:
                    l_cores[int(matchObj.group(1))] = list(matchObj.group(2))
        if not l_cores:
            raise Exception("Failed in getting core ids information from OPAL msg log")

        print l_cores # {0: ['4', '5', '6', 'c', 'd', 'e'], 1: ['4', '5', '6', 'c', 'd', 'e'], 10: ['4', '5', '6', 'c', 'd', 'e']}
        l_cores = sorted(l_cores.iteritems())
        print l_cores
        i=0
        for tup in l_cores:
            new_list = [l_chips[i], tup[1]]
            self.l_dic.append(new_list)
            i+=1
        print self.l_dic
        # self.l_dic is a list of chip id's, core id's . and is of below format 
        # [['00000000', ['4', '5', '6', 'c', 'd', 'e']], ['00000001', ['4', '5', '6', 'c', 'd', 'e']], ['00000010', ['4', '5', '6', 'c', 'd', 'e']]]

        # In-order to inject HMI errors on cpu's, cpu should be running, so disabling the sleep states 1 and 2 of all CPU's
        self.cv_HOST.host_run_command(BMC_CONST.GET_CPU_SLEEP_STATE2)
        self.cv_HOST.host_run_command(BMC_CONST.GET_CPU_SLEEP_STATE1)
        self.cv_HOST.host_run_command(BMC_CONST.GET_CPU_SLEEP_STATE0)
        self.cv_HOST.host_run_command(BMC_CONST.DISABLE_CPU_SLEEP_STATE1)
        self.cv_HOST.host_run_command(BMC_CONST.DISABLE_CPU_SLEEP_STATE2)
        self.cv_HOST.host_run_command(BMC_CONST.GET_CPU_SLEEP_STATE2)
        self.cv_HOST.host_run_command(BMC_CONST.GET_CPU_SLEEP_STATE1)
        self.cv_HOST.host_run_command(BMC_CONST.GET_CPU_SLEEP_STATE0)

        l_oslevel = self.cv_HOST.host_get_OS_Level()
        if "Ubuntu" in l_oslevel:
            self.cv_HOST.host_run_command("service kdump-tools stop")
            self.cv_HOST.host_run_command("service kdump-tools status")
        else:
            self.cv_HOST.host_run_command("service kdump stop")
            self.cv_HOST.host_run_command("service kdump status")

    def clearGardEntries(self):
        self.cv_SYSTEM.goto_state(OpSystemState.OS)
        g = self.cv_HOST.host_run_command("PATH=/usr/local/sbin:$PATH opal-gard list")
        if "No GARD entries to display" not in g:
            self.cv_HOST.host_run_command("PATH=/usr/local/sbin:$PATH opal-gard clear")
            cleared_gard = self.cv_HOST.host_run_command("PATH=/usr/local/sbin:$PATH opal-gard list")
            self.assertIn("No GARD entries to display", cleared_gard,
                          "Failed to clear GARD entries")
            self.cv_SYSTEM.goto_state(OpSystemState.OFF)
            self.cv_SYSTEM.goto_state(OpSystemState.OS)

    ##
    # @brief This function executes HMI test case based on the i_test value, Before test starts
    #        disabling kdump service to make sure system reboots, after injecting non-recoverable errors.
    #
    # @param i_test @type int: this is the type of test case want to execute
    #                          BMC_CONST.HMI_PROC_RECV_DONE: Processor recovery done
    #                          BMC_CONST.HMI_PROC_RECV_ERROR_MASKED: proc_recv_error_masked
    #                          BMC_CONST.HMI_MALFUNCTION_ALERT: malfunction_alert
    #                          BMC_CONST.HMI_HYPERVISOR_RESOURCE_ERROR: hypervisor resource error
    def _testHMIHandling(self, i_test):
        l_test = i_test
        self.init_test()
        self.cv_SYSTEM.goto_state(OpSystemState.OS)

        l_con = self.cv_SYSTEM.sys_get_ipmi_console()
        self.cv_IPMI.ipmi_host_login(l_con)
        self.cv_IPMI.ipmi_host_set_unique_prompt()
        self.cv_IPMI.run_host_cmd_on_ipmi_console("uname -a")
        self.cv_IPMI.run_host_cmd_on_ipmi_console("cat /etc/os-release")
        self.cv_IPMI.run_host_cmd_on_ipmi_console("lscpu")
        self.cv_IPMI.run_host_cmd_on_ipmi_console("dmesg -D")
        if l_test == BMC_CONST.HMI_PROC_RECV_DONE:
            self._test_proc_recv_done()
        elif l_test == BMC_CONST.HMI_PROC_RECV_ERROR_MASKED:
            self._test_proc_recv_error_masked()
        elif l_test == BMC_CONST.HMI_MALFUNCTION_ALERT:
            self._test_malfunction_allert()
        elif l_test == BMC_CONST.HMI_HYPERVISOR_RESOURCE_ERROR:
            self._test_hyp_resource_err()
        elif l_test == BMC_CONST.TOD_ERRORS:
            # TOD Error recovery works on systems having more than one chip TOD
            # Skip this test on single chip systems(as recovery fails on 1S systems)
            if len(self.l_dic) == 1:
                l_msg = "This is a single chip system, TOD Error recovery won't work"
                print l_msg
                return BMC_CONST.FW_SUCCESS
            elif len(self.l_dic) > 1:
                self._test_tod_errors(BMC_CONST.PSS_HAMMING_DISTANCE)
                self._test_tod_errors(BMC_CONST.INTERNAL_PATH_OR_PARITY_ERROR)
                self._test_tod_errors(BMC_CONST.TOD_DATA_PARITY_ERROR)
                self._test_tod_errors(BMC_CONST.TOD_SYNC_CHECK_ERROR)
                self._test_tod_errors(BMC_CONST.FSM_STATE_PARITY_ERROR)
                self._test_tod_errors(BMC_CONST.MASTER_PATH_CONTROL_REGISTER)
                self._test_tod_errors(BMC_CONST.PORT_0_PRIMARY_CONFIGURATION_REGISTER)
                self._test_tod_errors(BMC_CONST.PORT_1_PRIMARY_CONFIGURATION_REGISTER)
                self._test_tod_errors(BMC_CONST.PORT_0_SECONDARY_CONFIGURATION_REGISTER)
                self._test_tod_errors(BMC_CONST.PORT_1_SECONDARY_CONFIGURATION_REGISTER)
                self._test_tod_errors(BMC_CONST.SLAVE_PATH_CONTROL_REGISTER)
                self._test_tod_errors(BMC_CONST.INTERNAL_PATH_CONTROL_REGISTER)
                self._test_tod_errors(BMC_CONST.PR_SC_MS_SL_CONTROL_REGISTER)
            else:
                raise Exception("Getting Chip information failed")
        elif l_test == BMC_CONST.TFMR_ERRORS:
            self._testTFMR_Errors(BMC_CONST.TB_PARITY_ERROR)
            self._testTFMR_Errors(BMC_CONST.TFMR_PARITY_ERROR)
            self._testTFMR_Errors(BMC_CONST.TFMR_HDEC_PARITY_ERROR)
            self._testTFMR_Errors(BMC_CONST.TFMR_DEC_PARITY_ERROR)
            self._testTFMR_Errors(BMC_CONST.TFMR_PURR_PARITY_ERROR)
            self._testTFMR_Errors(BMC_CONST.TFMR_SPURR_PARITY_ERROR)
        else:
            raise Exception("Please provide valid test case")

        print "Gathering the OPAL msg logs"
        self.cv_HOST.host_gather_opal_msg_log()
        return BMC_CONST.FW_SUCCESS

    ##
    # @brief This function is used to test HMI: processor recovery done
    #        and also this function injecting error on all the cpus one by one and 
    #        verify whether cpu is recovered or not.
    def _test_proc_recv_done(self):
        for l_pair in self.l_dic:
            l_chip = l_pair[0]
            for l_core in l_pair[1]:
                l_reg = "1%s013100" % l_core
                l_cmd = "PATH=/usr/local/sbin:$PATH putscom -c %s %s 0000000000100000; echo $?" % (l_chip, l_reg)

                self.cv_IPMI.run_host_cmd_on_ipmi_console("dmesg -C")
                l_res = self.cv_IPMI.run_host_cmd_on_ipmi_console(l_cmd)
                if l_res[-1] == "0":
                    print "Injected thread hang recoverable error"
                elif l_res[-1] == "1":
                    # putscom returns -5 when it is trying to read from write only access register,
                    # In these cases we should not exit and we will contiue with other error injetions
                    continue
                else:
                    if any("Kernel panic - not syncing" in line for line in l_res):
                        raise Exception("Processor recovery failed: Kernel got panic")
                    elif any("Petitboot" in line for line in l_res):
                        raise Exception("System reached petitboot:Processor recovery failed")
                    elif any("ISTEP" in line for line in l_res):
                        raise Exception("System started booting: Processor recovery failed")
                    else:
                        raise Exception("Failed to inject thread hang recoverable error")

                l_res = self.cv_IPMI.run_host_cmd_on_ipmi_console("dmesg")
                if any("Processor Recovery done" in line for line in l_res) and \
                any("Harmless Hypervisor Maintenance interrupt [Recovered]" in line for line in l_res):
                    print "Processor recovery done"
                else:
                    raise Exception("HMI handling failed to log message: for proc_recv_done")
        return

    ##
    # @brief This function is used to test HMI: proc_recv_error_masked
    #        Processor went through recovery for an error which is actually masked for reporting
    #        this function also injecting the error on all the cpu's one-by-one.
    def _test_proc_recv_error_masked(self):
        for l_pair in self.l_dic:
            l_chip = l_pair[0]
            for l_core in l_pair[1]:
                l_reg = "1%s013100" % l_core
                l_cmd = "PATH=/usr/local/sbin:$PATH putscom -c %s %s 0000000000080000; echo $?" % (l_chip, l_reg)
                self.cv_IPMI.run_host_cmd_on_ipmi_console("dmesg -C")
                l_res = self.cv_IPMI.run_host_cmd_on_ipmi_console(l_cmd)
                if l_res[-1] == "0":
                    print "Injected thread hang recoverable error"
                elif l_res[-1] == "1":
                    continue
                else:
                    if any("Kernel panic - not syncing" in line for line in l_res):
                        raise Exception("Processor recovery failed: Kernel got panic")
                    elif any("Petitboot" in line for line in l_res):
                        raise Exception("System reached petitboot:Processor recovery failed")
                    elif any("ISTEP" in line for line in l_res):
                        raise Exception("System started booting: Processor recovery failed")
                    else:
                        raise Exception("Failed to inject thread hang recoverable error")

                l_res = self.cv_IPMI.run_host_cmd_on_ipmi_console("dmesg")
                if any("Processor Recovery done" in line for line in l_res) and \
                any("Harmless Hypervisor Maintenance interrupt [Recovered]" in line for line in l_res):
                    print "Processor recovery done"
                else:
                    raise Exception("HMI handling failed to log message")
        return

    ##
    # @brief This function is used to test hmi malfunction alert:Core checkstop
    #        A processor core in the system has to be checkstopped (failed recovery).
    #        Injecting core checkstop on random core of random chip
    def _test_malfunction_allert(self):
        # Get random pair of chip vs cores
        l_pair = random.choice(self.l_dic)
        # Get random chip id
        l_chip = l_pair[0]
        # Get random core number
        l_core = random.choice(l_pair[1])

        l_reg = "1%s013100" % l_core
        l_cmd = "PATH=/usr/local/sbin:$PATH putscom -c %s %s 1000000000000000" % (l_chip, l_reg)

        l_res = self.cv_IPMI.run_host_cmd_on_ipmi_console(l_cmd)
        if any("Kernel panic - not syncing" in line for line in l_res):
            print "Malfunction alert: kernel got panic"
        elif any("login:" in line for line in l_res):
            print "System booted to host OS without any kernel panic message"
        elif any("Petitboot" in line for line in l_res):
            print "System reached petitboot without any kernel panic message"
        elif any("ISTEP" in line for line in l_res):
            print "System started booting without any kernel panic message"
        else:
            raise Exception("HMI: Malfunction alert failed")

        return

    ##
    # @brief This function is used to test HMI: Hypervisor resource error
    #        Injecting Hypervisor resource error on random core of random chip
    def _test_hyp_resource_err(self):
        # Get random pair of chip vs cores
        l_pair = random.choice(self.l_dic)
        # Get random chip id
        l_chip = l_pair[0]
        # Get random core number
        l_core = random.choice(l_pair[1])

        l_reg = "1%s013100" % l_core
        l_cmd = "PATH=/usr/local/sbin:$PATH putscom -c %s %s 0000000000008000" % (l_chip, l_reg)

        l_res = self.cv_IPMI.run_host_cmd_on_ipmi_console(l_cmd)
        if any("Kernel panic - not syncing" in line for line in l_res) and \
        any("Hypervisor Resource error - core check stop" in line for line in l_res):
            print "Hypervisor resource error: kernel got panic"
        elif any("login:" in line for line in l_res):
            print "System booted to host OS without any kernel panic message"
        elif any("Petitboot" in line for line in l_res):
            print "System reached petitboot without any kernel panic message"
        elif any("ISTEP" in line for line in l_res):
            print "System started booting without any kernel panic message"
        else:
            raise Exception("HMI: Hypervisor resource error failed")
        return

    ##
    # @brief This function tests timer facility related error injections and check
    #        the corresponding error got recovered. And this process is repeated
    #        for all the active cores in all the chips.
    #
    # @param i_error @type string: this is the type of error want to inject
    #                          BMC_CONST.TB_PARITY_ERROR
    #                          BMC_CONST.TFMR_PARITY_ERROR
    #                          BMC_CONST.TFMR_HDEC_PARITY_ERROR
    #                          BMC_CONST.TFMR_DEC_PARITY_ERROR
    #                          BMC_CONST.TFMR_PURR_PARITY_ERROR
    #                          BMC_CONST.TFMR_SPURR_PARITY_ERROR
    def _testTFMR_Errors(self, i_error):
        l_error = i_error
        for l_pair in self.l_dic:
            l_chip = l_pair[0]
            for l_core in l_pair[1]:
                l_reg = "1%s013281" % l_core
                l_cmd = "PATH=/usr/local/sbin:$PATH putscom -c %s %s %s;echo $?" % (l_chip, l_reg, l_error)
                self.cv_IPMI.run_host_cmd_on_ipmi_console("dmesg -C")
                l_res = self.cv_IPMI.run_host_cmd_on_ipmi_console(l_cmd)
                if l_res[-1] == "0":
                    print "Injected TFMR error %s" % l_error
                elif l_res[-1] == "1":
                    continue
                else:
                    if any("Kernel panic - not syncing" in line for line in l_res):
                        l_msg = "TFMR error injection: Kernel got panic"
                    elif any("Petitboot" in line for line in l_res):
                        l_msg = "System reached petitboot:TFMR error injection recovery failed"
                    elif any("ISTEP" in line for line in l_res):
                        l_msg = "System started booting: TFMR error injection recovery failed"
                    else:
                        raise Exception("Failed to inject TFMR error %s " % l_error)

                l_res = self.cv_IPMI.run_host_cmd_on_ipmi_console("dmesg")
                if any("Timer facility experienced an error" in line for line in l_res) and \
                    any("Severe Hypervisor Maintenance interrupt [Recovered]" in line for line in l_res):
                    print "Timer facility experienced an error and got recovered"
                else:
                    raise Exception("HMI handling failed to log message")

        return

    ##
    # @brief This function tests chip TOD related error injections and check
    #        the corresponding error got recovered. And this error injection
    #        happening on a random chip. This tod errors should test on systems
    #        having more than one processor socket(chip). On single chip system
    #        TOD error recovery won't work.
    #
    # @param i_error @type string: this is the type of error want to inject
    #                       These errors represented in common/OpTestConstants.py file.
    def _test_tod_errors(self, i_error):
        l_error = i_error
        l_pair = random.choice(self.l_dic)
        # Get random chip id
        l_chip = l_pair[0]
        l_cmd = "PATH=/usr/local/sbin:$PATH putscom -c %s %s %s;echo $?" % (l_chip, BMC_CONST.TOD_ERROR_REG, l_error)
        self.cv_IPMI.run_host_cmd_on_ipmi_console("dmesg -C")
        l_res = self.cv_IPMI.run_host_cmd_on_ipmi_console(l_cmd)
        # As of now putscom command to TOD register will fail with return code -1.
        # putscom indirectly call getscom to read the value again.
        # But getscom to TOD error reg there is no access
        # TOD Error reg has only WO access and there is no read access
        if l_res[-1] == "1":
            print "Injected TOD error %s" % l_error
        else:
            if any("Kernel panic - not syncing" in line for line in l_res):
                print "TOD ERROR Injection-kernel got panic"
            elif any("login:" in line for line in l_res):
                print "System booted to host OS without any kernel panic message"
            elif any("Petitboot" in line for line in l_res):
                print "System reached petitboot without any kernel panic message"
            elif any("ISTEP" in line for line in l_res):
                print "System started booting without any kernel panic message"
            else:
                raise Exception("TOD: PSS Hamming distance error injection failed")

        l_res = self.cv_IPMI.run_host_cmd_on_ipmi_console("dmesg")
        if any("Timer facility experienced an error" in line for line in l_res) and \
            any("Severe Hypervisor Maintenance interrupt [Recovered]" in line for line in l_res):
            print "Timer facility experienced an error and got recovered"
        else:
            raise Exception("HMI handling failed to log message")

        return

    ##
    # @brief This function enables a single core
    def host_enable_single_core(self):
        self.cv_HOST.host_enable_single_core()

class HMI_TFMR_ERRORS(OpTestHMIHandling):
    def runTest(self):
        self._testHMIHandling(BMC_CONST.TFMR_ERRORS)

class TOD_ERRORS(OpTestHMIHandling):
    def runTest(self):
        self._testHMIHandling(BMC_CONST.TOD_ERRORS)

class SingleCoreTOD_ERRORS(OpTestHMIHandling):
    def runTest(self):
        self.host_enable_single_core()
        self._testHMIHandling(BMC_CONST.TOD_ERRORS)

class PROC_RECOV_DONE(OpTestHMIHandling):
    def runTest(self):
        self._testHMIHandling(BMC_CONST.HMI_PROC_RECV_DONE)

class PROC_RECV_ERROR_MASKED(OpTestHMIHandling):
    def runTest(self):
        self._testHMIHandling(BMC_CONST.HMI_PROC_RECV_ERROR_MASKED)

class MalfunctionAlert(OpTestHMIHandling):
    def runTest(self):
        self._testHMIHandling(BMC_CONST.HMI_MALFUNCTION_ALERT)

class HypervisorResourceError(OpTestHMIHandling):
    def runTest(self):
        self._testHMIHandling(BMC_CONST.HMI_HYPERVISOR_RESOURCE_ERROR)

class ClearGard(OpTestHMIHandling):
    def runTest(self):
        self.clearGardEntries()

def unrecoverable_suite():
    s = unittest.TestSuite()
    s.addTest(MalfunctionAlert())
    s.addTest(HypervisorResourceError())
    s.addTest(ClearGard())
    return s

def suite():
    s = unittest.TestSuite()
    s.addTest(HMI_TFMR_ERRORS())
    s.addTest(PROC_RECOV_DONE())
    s.addTest(PROC_RECV_ERROR_MASKED())
    return s

def experimental_suite():
    s = unittest.TestSuite()
    s.addTest(TOD_ERRORS())
    s.addTest(SingleCoreTOD_ERRORS())
    return s
