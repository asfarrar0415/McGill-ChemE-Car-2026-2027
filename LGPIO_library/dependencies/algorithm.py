import csv
import time
from datetime import datetime


def algo(read, output="ir_data.csv", rate=10, duration=0,
           stop_value=None, stop_index=-1, header=("voltage_v",),
           should_stop=None, verbose=True):
    """
    Log readings from read() to a CSV file at a fixed rate.

    read        function that returns one reading: either a single number
                (e.g. voltage) or a tuple/list (e.g. (raw, voltage)).
                Use the ADC interface you already have.
    output      CSV file path (appended to if it exists)
    rate        samples per second
    duration    seconds to record (0 = until stopped)
    stop_value  stop logging when the reading exceeds this value
                (None = never stop on value)
    stop_index  which element of the reading to compare against stop_value
                (default -1 = last element)
    header      column names for the values returned by read()
    should_stop optional function; logging ends when it returns True
    verbose     print progress once per second

    Returns a dict: {"samples": int, "tripped": bool, "elapsed_s": float, "file": str}
    """
    if rate <= 0:
        raise ValueError("rate must be greater than 0")

    interval = 1.0 / rate
    count = 0
    tripped = False

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

                values = read()
                if not isinstance(values, (tuple, list)):
                    values = (values,)

                writer.writerow([datetime.now().isoformat(timespec="milliseconds"),
                                 round(elapsed, 4), *values])
                count += 1

                if stop_value is not None and values[stop_index] > stop_value:
                    tripped = True
                    if verbose:
                        print(f"\nStopped: value {values[stop_index]} exceeded {stop_value}")
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

    return {"samples": count, "tripped": tripped,
            "elapsed_s": round(total, 3), "file": output}
