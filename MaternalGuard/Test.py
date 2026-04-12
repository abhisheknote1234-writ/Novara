import sys
import serial
import numpy as np
import scipy.signal
import pyqtgraph as pg
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer

# --- CONFIGURATION ---
COM_PORT = 'COM3'      # Match this to your ESP32 port
BAUD_RATE = 115200     # Must match the Serial.begin() in Arduino
WINDOW_SIZE = 1000     # 4 seconds of data at 250Hz
TEST_MODE = False      # Set to True to use simulated data instead of real serial

# --- HIGH-SPEED MATH DETECTORS ---
def detect_r_peaks_fast(ecg_buffer, fs=250):
    """Calculates exact R-peak indices on the fly using a fast moving window."""
    diff = np.diff(ecg_buffer)
    squared = diff ** 2
    window_size = int(0.12 * fs)
    kernel = np.ones(window_size) / window_size
    mwi = np.convolve(squared, kernel, mode='same')
    mwi[:window_size] = 0
    mwi[-window_size:] = 0
    threshold = np.mean(mwi) + (1.2 * np.std(mwi))
    min_dist = int(0.200 * fs)
    peaks, _ = scipy.signal.find_peaks(mwi, height=threshold, distance=min_dist)
    true_peaks = []
    for p in peaks:
        start = max(0, p - 12)
        end = min(len(ecg_buffer), p + 12)
        if start < end:
            true_peaks.append(start + np.argmax(ecg_buffer[start:end]))
    return true_peaks

def detect_ppg_peaks_fast(ppg_buffer, fs=250):
    """Finds systolic peaks in the optical PPG wave using Adaptive Prominence."""
    # 1. Smooth the optical signal (removes high-frequency LED noise)
    kernel_size = int(0.05 * fs)
    kernel = np.ones(kernel_size) / kernel_size
    smoothed = np.convolve(ppg_buffer, kernel, mode='same')
    
    # 2. Adaptive Prominence: The wave height changes as you breathe.
    ac_amplitude = np.max(smoothed) - np.min(smoothed)
    prominence_thresh = max(ac_amplitude * 0.15, 5) 
    
    # 3. Minimum distance: max HR is ~200 BPM -> ~300ms between beats
    min_dist = int(0.300 * fs)
    
    # Find the peaks
    peaks, _ = scipy.signal.find_peaks(smoothed, distance=min_dist, prominence=prominence_thresh)
    
    # Discard peaks right on the edge of the screen
    valid_peaks = [p for p in peaks if 15 < p < len(ppg_buffer)-15]
    return valid_peaks

class PhysioDashboard:
    def __init__(self):
        print(f"Connecting to {COM_PORT}...")
        if TEST_MODE:
            self.ser = None
            self.test_counter = 0
        else:
            try:
                self.ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0)
            except Exception as e:
                print(f"✗ Failed to connect: {e}")
                sys.exit(1)

        self.app = QApplication(sys.argv)
        self.win = pg.GraphicsLayoutWidget(show=True, title="Maternal Sentinel - Live Data")
        self.win.resize(1200, 800)
        pg.setConfigOptions(antialias=True)

        # ECG Plot
        self.plot_ecg = self.win.addPlot(title="ECG (AD8232) - Lead I")
        self.plot_ecg.setYRange(5000, 30000)
        self.plot_ecg.showGrid(x=True, y=True, alpha=0.3)
        self.curve_ecg = self.plot_ecg.plot(pen=pg.mkPen('g', width=2))
        self.scatter_ecg = pg.ScatterPlotItem(size=10, pen=None, brush=pg.mkBrush(255, 68, 102))
        self.scatter_ecg.setZValue(10)
        self.plot_ecg.addItem(self.scatter_ecg)

        self.win.nextRow()

        # PPG Plot
        self.plot_ppg = self.win.addPlot(title="PPG (MAX30102) - Optical")
        self.plot_ppg.showGrid(x=True, y=True, alpha=0.3)
        self.curve_ppg = self.plot_ppg.plot(pen=pg.mkPen('r', width=2))
        
        # ADDED: Blue dot scatter plot for PPG peaks
        self.scatter_ppg = pg.ScatterPlotItem(size=10, pen=None, brush=pg.mkBrush(102, 204, 255))
        self.scatter_ppg.setZValue(10)
        self.plot_ppg.addItem(self.scatter_ppg)

        self.data_ecg = np.zeros(WINDOW_SIZE)
        self.data_ppg = np.zeros(WINDOW_SIZE)
        self.raw_serial_buffer = b""

        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(16)

    def update(self):
        try:
            if TEST_MODE:
                self.test_counter += 1
                ecg_val = 2048 + 500 * np.sin(self.test_counter * 0.05)
                ppg_val = 50000 + 5000 * np.sin(self.test_counter * 0.03)
                new_ecg, new_ppg = [ecg_val], [ppg_val]
            else:
                new_ecg, new_ppg = [], []
                if self.ser.in_waiting > 0:
                    self.raw_serial_buffer += self.ser.read(self.ser.in_waiting)
                    if b'\n' in self.raw_serial_buffer:
                        lines = self.raw_serial_buffer.split(b'\n')
                        self.raw_serial_buffer = lines.pop()
                        for line in lines:
                            try:
                                decoded = line.decode('utf-8').strip()
                                if ',' in decoded:
                                    ecg_val, ppg_val = decoded.split(',')
                                    new_ecg.append(float(ecg_val))
                                    new_ppg.append(float(ppg_val))
                            except ValueError:
                                pass
            
            if new_ecg:
                n = len(new_ecg)
                self.data_ecg[:-n] = self.data_ecg[n:]
                self.data_ppg[:-n] = self.data_ppg[n:]
                self.data_ecg[-n:] = new_ecg
                self.data_ppg[-n:] = new_ppg
                
                self.curve_ecg.setData(self.data_ecg)
                self.curve_ppg.setData(self.data_ppg)

                # Draw ECG Red Dots
                ecg_peaks = detect_r_peaks_fast(self.data_ecg, fs=250)
                ecg_y = [self.data_ecg[i] for i in ecg_peaks]
                self.scatter_ecg.setData(x=ecg_peaks, y=ecg_y)

                # ADDED: Draw PPG Blue Dots
                ppg_peaks = detect_ppg_peaks_fast(self.data_ppg, fs=250)
                ppg_y = [self.data_ppg[i] for i in ppg_peaks]
                self.scatter_ppg.setData(x=ppg_peaks, y=ppg_y)

        except Exception as e:
            print(f"Serial/Update Error: {e}")

if __name__ == '__main__':
    try:
        dashboard = PhysioDashboard()
        sys.exit(dashboard.app.exec_())
    except Exception as e:
        sys.exit(1)