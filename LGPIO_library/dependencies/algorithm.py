import csv
import time
from datetime import datetime
 
MAX_CONSECUTIVE_READ_ERRORS = 10
 
 
def algo(read, output="ir_data.csv", rate=10, duration=0,
         stop_value=None, stop_below=None, stop_index=-1, header=("voltage_v",),
         should_stop=None, verbose=True):
    """
    Log readings from read() to a CSV file at a fixed rate.
 
    read        function returning one reading: a number or a tuple/list
    output      CSV path (appended to if it exists)
    rate        samples per second
    duration    seconds to record (0 = until stopped)
    stop_value  stop when the reading rises ABOVE this (None = off)
    stop_below  stop when the reading falls BELOW this (None = off)
    stop_index  which element of the reading to compare (default: last)
    header      column names for the values returned by read()
    should_stop optional function; logging ends when it returns True
    verbose     print progress once per second
 
    Returns {"samples", "tripped", "error", "elapsed_s", "file"}.
    "error" is None, or a message if reads kept failing.
    """
    if rate <= 0:
        raise ValueError("rate must be greater than 0")
 
    interval = 1.0 / rate
    count = 0
    tripped = False
    error = None
    bad_reads = 0
 
    with open(output, "a", newline="") as f:
        writer = csv.writer(f)
        if f.tell() == 0:
            writer.writerow(["timestamp", "elapsed_s", *header])
 
        start = time.monotonic()
        next_t = start
        last_flush = start
 
        try:
            while not (should_stop and should_stop()):
                now = time.monotonic()
                elapsed = now - start
                if duration and elapsed >= duration:
                    break
 
                try:
                    values = read()
                    bad_reads = 0
                except Exception as e:          # a single bad I2C read shouldn't end the run
                    bad_reads += 1
                    if bad_reads >= MAX_CONSECUTIVE_READ_ERRORS:
                        error = f"{bad_reads} consecutive read errors, last: {e}"
                        break
                    time.sleep(interval)
                    continue
 
                if not isinstance(values, (tuple, list)):
                    values = (values,)
 
                writer.writerow([datetime.now().isoformat(timespec="milliseconds"),
                                 round(elapsed, 4), *values])
                count += 1
 
                v = values[stop_index]
                if ((stop_value is not None and v > stop_value) or
                        (stop_below is not None and v < stop_below)):
                    tripped = True
                    if verbose:
                        print(f"\nStopped: value {v} crossed the threshold")
                    break
 
                if now - last_flush >= 1.0:
                    f.flush()
                    last_flush = now
                    if verbose:
                        print(f"\r{count} samples | latest: {list(values)}",
                              end="", flush=True)
 
                # Fixed-rate timing: skip ahead if we fall behind
                next_t += interval
                delay = next_t - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_t = time.monotonic()
 
        except KeyboardInterrupt:
            pass
        finally:
            f.flush()
 
        total = time.monotonic() - start
 
    if verbose:
        print(f"\nDone. {count} samples saved to {output}")
 
    return {"samples": count, "tripped": tripped, "error": error,
            "elapsed_s": round(total, 3), "file": output}
 
