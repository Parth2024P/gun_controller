import time
import math
import serial
import pyautogui

PORT = "COM10"
BAUD_RATE = 115200

# Tuning parameters
SENSITIVITY = 200.0   # Pixels per degree of rotation
DEADZONE = 2.5       # Degrees per second
SMOOTHING = 0.6      # 0.0 = no smoothing (raw), 0.9 = heavy smoothing

# Flip to True if horizontal aiming feels like twisting your wrist instead of pointing
USE_GZ_FOR_HORIZONTAL = False

# CRITICAL: Remove pyautogui's default 100ms delay per call
pyautogui.PAUSE = 0
pyautogui.MINIMUM_DURATION = 0
pyautogui.MINIMUM_SLEEP = 0
pyautogui.FAILSAFE = True


def apply_deadzone(value, deadzone):
    """Smoothly ramps movement from 0 right after crossing the deadzone."""
    if abs(value) <= deadzone:
        return 0.0
    return math.copysign(abs(value) - deadzone, value)


def get_latest_line(ser):
    """Reads all waiting bytes and returns only the most recent complete line."""
    if ser.in_waiting == 0:
        return ser.readline().decode("utf-8", errors="ignore").strip()

    # Drain buffer so we never process delayed, queued-up movements
    data = ser.read(ser.in_waiting).decode("utf-8", errors="ignore")
    lines = data.split("\n")

    # Walk backwards to find the last complete line
    for line in reversed(lines[:-1]):
        line = line.strip()
        if line:
            return line
    return ""


def main():
    print("Connecting to Arduino...")

    with serial.Serial(PORT, BAUD_RATE, timeout=0.05) as arduino:
        time.sleep(2)
        arduino.reset_input_buffer()

        print("Keep the controller still for calibration...")

        samples = []
        start = time.time()

        while time.time() - start < 2.0:
            line = arduino.readline().decode("utf-8", errors="ignore").strip()
            values = line.split(",")

            if len(values) != 7:
                continue

            try:
                gx = int(values[3])
                gy = int(values[4])
                gz = int(values[5])
                samples.append((gx, gy, gz))
            except ValueError:
                continue

        if not samples:
            print("No sensor data received. Check the Arduino.")
            return

        bias_x = sum(s[0] for s in samples) / len(samples)
        bias_y = sum(s[1] for s in samples) / len(samples)
        bias_z = sum(s[2] for s in samples) / len(samples)

        print("Calibration complete!")
        print("Tilt and rotate the controller to aim.")
        print("Press the trigger to click.")
        print("Move mouse to top-left corner to stop.")

        previous_trigger = 0
        last_time = time.time()

        # Sub-pixel accumulators and smoothing states
        rem_x, rem_y = 0.0, 0.0
        smooth_rx, smooth_ry = 0.0, 0.0

        # Clear any backlog built up during print statements
        arduino.reset_input_buffer()

        while True:
            line = get_latest_line(arduino)
            if not line:
                continue

            values = line.split(",")
            if len(values) != 7:
                continue

            try:
                gx = int(values[3])
                gy = int(values[4])
                gz = int(values[5])
                trigger = int(values[6])
            except ValueError:
                continue

            now = time.time()
            dt = min(now - last_time, 0.05)
            last_time = now

            # Convert raw gyro units to degrees/second
            rate_pitch = (gx - bias_x) / 131.0
            if USE_GZ_FOR_HORIZONTAL:
                rate_horiz = -(gz - bias_z) / 131.0
            else:
                rate_horiz = (gy - bias_y) / 131.0

            # Soft deadzone prevents sudden jumps when starting a slow aim
            rate_pitch = apply_deadzone(rate_pitch, DEADZONE)
            rate_horiz = apply_deadzone(rate_horiz, DEADZONE)

            # Low-pass filter to reduce hand jitter
            smooth_rx = (SMOOTHING * smooth_rx) + ((1.0 - SMOOTHING) * rate_pitch)
            smooth_ry = (SMOOTHING * smooth_ry) + ((1.0 - SMOOTHING) * rate_horiz)

            # Accumulate sub-pixel movement so slow motions aren't rounded to 0
            move_x = (smooth_ry * SENSITIVITY * dt) + rem_x
            move_y = (-smooth_rx * SENSITIVITY * dt) + rem_y

            dx = int(move_x)
            dy = int(move_y)

            # Save the fractional remainder for the next loop iteration
            rem_x = move_x - dx
            rem_y = move_y - dy

            if dx != 0 or dy != 0:
                pyautogui.moveRel(dx, dy, _pause=False)

            # Click once per trigger press
            if trigger == 1 and previous_trigger == 0:
                pyautogui.click(_pause=False)
                print("Trigger pressed: mouse click")

            previous_trigger = trigger


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nController stopped.")
    except pyautogui.FailSafeException:
        print("\nFailsafe triggered from top-left corner. Controller stopped.")
    except serial.SerialException as error:
        print("Serial connection error:", error)