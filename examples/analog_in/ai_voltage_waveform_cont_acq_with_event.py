﻿"""Example of analog input voltage acquisition.

This example demonstrates how to continuously acquire buffered voltage measurements using
a DAQmx device. It uses software events to ensure that the program does not become
unresponsive while waiting for samples to become available.
"""

import pprint

import nidaqmx
from nidaqmx.constants import AcquisitionType

pp = pprint.PrettyPrinter(indent=4, compact=True)

with nidaqmx.Task() as task:

    def callback(task_handle, every_n_samples_event_type, number_of_samples, callback_data):
        """Callback function for reading singals."""
        print("Every N Samples callback invoked.")
        pp.pprint(task.read(number_of_samples_per_channel=100))

        return 0

    task.ai_channels.add_ai_voltage_chan("Dev1/ai0")
    task.timing.cfg_samp_clk_timing(
        1000.0, sample_mode=AcquisitionType.CONTINUOUS, samps_per_chan=1000
    )
    task.register_every_n_samples_acquired_into_buffer_event(100, callback)
    task.start()

    input("Running task. Press Enter to stop.\n")

    task.stop()
