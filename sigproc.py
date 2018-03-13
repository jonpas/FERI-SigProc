#!/usr/bin/env python3

"""
Requirements:
- numpy, pydub, matplotlib, PyQt5 Python packages
- ffmpeg installed on system
"""

import sys
import numpy as np
import pyaudio
from pydub import AudioSegment, exceptions
from pydub.utils import make_chunks
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition
from PyQt5.QtWidgets import *

PyAudio = pyaudio.PyAudio


class MainWindow(QWidget):
    sig_sound_stop = pyqtSignal()
    sig_sound_pause = pyqtSignal()

    def __init__(self):
        super().__init__()

        self.sound = None
        self.signal = None

        self.subplots = []
        self.lines_click = []
        self.lines_over = []
        self.line_over = None

        self.sound_thread = None
        self.sound_paused = False

        self.initUI()

    def initUI(self):
        # File selector
        lbl_file = QLabel("File:")
        self.txt_file = QLineEdit()
        self.txt_file.setPlaceholderText("Select file ...")
        btn_file = QPushButton("Select")
        btn_file.clicked.connect(self.show_file_dialog)

        spacer = QSpacerItem(100, 0, QSizePolicy.Minimum)

        # Audio controls
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setDisabled(True)
        self.btn_pause.clicked.connect(self.sound_pause)
        self.sound_mutex = QMutex()
        self.sound_pause_cond = QWaitCondition()

        self.btn_play = QPushButton("Play")
        self.btn_play.setDisabled(True)
        self.btn_play.clicked.connect(self.sound_play)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setDisabled(True)
        self.btn_stop.clicked.connect(self.sound_stop)

        # Graph space
        self.figure = Figure()
        FigureCanvas(self.figure)
        # self.figure.canvas.mpl_connect("button_press_event", self.on_plot_click)
        # self.figure.canvas.mpl_connect("motion_notify_event", self.on_plot_over)

        # Layout
        hbox_file = QHBoxLayout()
        hbox_file.addWidget(lbl_file)
        hbox_file.addWidget(self.txt_file)
        hbox_file.addWidget(btn_file)
        hbox_file.addSpacerItem(spacer)
        hbox_file.addWidget(self.btn_pause)
        hbox_file.addWidget(self.btn_play)
        hbox_file.addWidget(self.btn_stop)

        vbox = QVBoxLayout()
        vbox.addLayout(hbox_file)
        vbox.addWidget(self.figure.canvas)

        # Window
        self.setLayout(vbox)
        self.setGeometry(300, 300, 1000, 500)
        self.setWindowTitle("Signal Processor")
        self.show()

    def update_ui(self, block):
        self.btn_pause.setDisabled(not block)
        self.btn_pause.setText("Resume" if self.sound_paused else "Pause")
        self.btn_play.setDisabled(block)
        self.btn_stop.setDisabled(not block)

    def show_file_dialog(self):
        fname = QFileDialog.getOpenFileName(self, "Select file")
        if fname[0]:
            self.txt_file.setText(fname[0])
            self.load_signal(fname[0])
            if self.is_signal_loaded():
                self.plot(self.signal, self.sound)
        else:
            self.txt_file.setText("")

    def load_signal(self, file):
        self.sound_stop()

        try:
            self.sound = AudioSegment.from_file(file)
            signal = self.sound.get_array_of_samples()
            self.signal = np.array(signal)
        except exceptions.CouldntDecodeError:
            print("Failed to load signal!")

        self.update_ui(self.signal is None)

    def is_signal_loaded(self):
        return self.sound is not None and self.signal is not None

    def plot(self, signal, sound):
        self.figure.clear()
        self.subplots = []
        self.lines_click = []
        self.lines_over = []

        # X axis as time in seconds
        time = np.linspace(0, sound.duration_seconds, num=len(signal))

        for i in range(0, sound.channels):
            ax = self.figure.add_subplot(sound.channels, 1, i + 1)
            samples = sound.get_array_of_samples()  # [samp1L, samp1R, samp2L, samp2R]
            # Plot current channel, slicing it away
            ax.plot(time[i::sound.channels], samples[i::sound.channels])
            ax.margins(x=0)

            # Hide X axis on all but last channel
            if i + 1 < sound.channels:
                ax.get_xaxis().set_visible(False)
            # Display Y label somewhere in the middle
            if i == int(sound.channels / 2) + 1:
                ax.set_ylabel("Amplitude")
            self.subplots.append(ax)

        self.figure.subplots_adjust(hspace=.0)
        ax.set_xlabel("Time (s)")
        self.figure.canvas.draw()

    def on_plot_click(self, event):
        # Remove previous lines
        for line in self.lines_click:
            line.remove()
        self.lines_click = []
        # self.figure.canvas.draw_idle()  # TODO Still too slow

        # Draw new lines
        if event.xdata is not None and event.ydata is not None:
            for ax in self.subplots:
                line = ax.axvline(event.xdata, linewidth=1, color="black")
                self.lines_click.append(line)
                self.plot_update(line, ax)

    def on_plot_over(self, event):
        # Remove previous lines
        for line in self.lines_over:
            line.remove()
        self.lines_over = []
        # self.figure.canvas.draw_idle()  # TODO Still too slow

        if event.xdata is not None and event.ydata is not None:
            # Draw new lines
            for ax in self.subplots:
                line = ax.axvline(event.xdata, linewidth=1, color="grey")
                self.lines_over.append(line)
                self.plot_update(line, ax)

    def plot_update(self, element, ax):
        ax.draw_artist(element)
        self.figure.canvas.blit(ax.bbox)

    def sound_play(self):
        if not self.sound_thread and self.is_signal_loaded():
            self.sound_thread = SoundThread(self.sound, self.sound_mutex, self.sound_pause_cond)
            self.sound_thread.finished.connect(self.on_sound_done)
            self.sig_sound_stop.connect(self.sound_thread.stop)
            self.sig_sound_pause.connect(self.sound_thread.pause)
            self.sound_thread.start()
            self.update_ui(True)

    def sound_stop(self):
        self.sig_sound_stop.emit()
        self.sound_mutex.lock()
        self.sound_pause_cond.wakeAll()
        self.sound_mutex.unlock()

    def sound_pause(self):  # Toggle
        if self.sound_paused:
            self.sig_sound_pause.emit()
            self.sound_mutex.lock()
            self.sound_pause_cond.wakeAll()
            self.sound_mutex.unlock()
        else:
            self.sig_sound_pause.emit()
        self.sound_paused = not self.sound_paused
        self.update_ui(True)

    def on_sound_done(self):
        self.sound_thread = None
        self.update_ui(False)


class SoundThread(QThread):
    def __init__(self, sound, mutex, pause_cond):
        QThread.__init__(self)

        self.sound = sound

        self.running = True
        self.paused = False
        self.mutex = mutex
        self.pause_cond = pause_cond

    def __del__(self):
        self.wait()

    def run(self):
        p = PyAudio()
        stream = p.open(
            format=p.get_format_from_width(self.sound.sample_width),
            channels=self.sound.channels,
            rate=self.sound.frame_rate,
            output=True)

        # Break into 0.1 second chunks
        for chunk in make_chunks(self.sound, 100):
            if not self.running:
                break

            stream.write(chunk._data)

            if self.paused:
                self.mutex.lock()
                self.pause_cond.wait(self.mutex)
                self.mutex.unlock()

        stream.close()
        p.terminate()

    def pause(self):  # Toggle
        self.paused = not self.paused

    def stop(self):
        self.running = False


if __name__ == "__main__":
    # Create Qt application with window
    app = QApplication(sys.argv)
    main_win = MainWindow()

    # Execute application (blocking)
    app.exec_()

    sys.exit(0)
