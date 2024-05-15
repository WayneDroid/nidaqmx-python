"""Example of counter input frequency acquisition.

This example demonstrates how to continuously measure frequency using one
counter on a Counter Input Channel. The Edge, Minimum Value and
Maximum Value are all configurable.
"""

import nidaqmx
from nidaqmx.constants import AcquisitionType, Edge, CounterFrequencyMethod, FrequencyUnits


with nidaqmx.Task() as task:
    chan = task.ci_channels.add_ci_freq_chan(
        "Dev1/ctr0",
        min_val=100.0,
        max_val=1000.0,
        units=FrequencyUnits.HZ,
        edge=Edge.RISING,
        meas_method=CounterFrequencyMethod.LOW_FREQUENCY_1_COUNTER,
    )
    chan.ci_freq_term = "/Dev1/PFI8"
    task.timing.cfg_implicit_timing(sample_mode=AcquisitionType.CONTINUOUS)

    print("Continuously polling. Press Ctrl+C to stop.")
    task.start()

    try:
        total_read = 0
        while True:
            count = task.read(number_of_samples_per_channel=1000)
            total_read += len(count)
            print(f"Acquired data: {len(count)} samples. Total {total_read}.", end="\r")
    except KeyboardInterrupt:
        pass
    finally:
        task.stop()
        print(f"\nAcquired {total_read} total samples.")