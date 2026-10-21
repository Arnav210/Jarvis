#!/usr/bin/env python3
"""One camera capture, shared locally as MJPEG. No tracking or video storage."""
import signal
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

condition = threading.Condition()
frame = None
sequence = 0
finished = False


class Viewer(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/stream.mjpg':
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        previous = -1
        try:
            while True:
                with condition:
                    condition.wait_for(lambda: sequence != previous or finished, timeout=5)
                    if finished:
                        return
                    if frame is None or previous == sequence:
                        continue
                    image, previous = frame, sequence
                self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' +
                                 str(len(image)).encode() + b'\r\n\r\n' + image + b'\r\n')
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass

    def log_message(self, *args):
        pass


def capture(process):
    global frame, sequence, finished
    buffer = bytearray()
    while chunk := process.stdout.read1(65536):
        buffer.extend(chunk)
        while True:
            start = buffer.find(b'\xff\xd8')
            end = buffer.find(b'\xff\xd9', max(0, start + 2))
            if start < 0 or end < 0:
                if len(buffer) > 4 * 1024 * 1024:
                    buffer.clear()
                break
            image = bytes(buffer[start:end + 2])
            del buffer[:end + 2]
            with condition:
                frame = image
                sequence += 1
                condition.notify_all()
    with condition:
        finished = True
        condition.notify_all()
    server.shutdown()


if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', 8766), Viewer)
    server.daemon_threads = True
    process = subprocess.Popen(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                                '-f', 'v4l2', '-framerate', '30', '-video_size', '640x480',
                                '-i', '/dev/video0', '-an', '-c:v', 'mjpeg', '-q:v', '5',
                                '-f', 'image2pipe', '-'], stdout=subprocess.PIPE)

    def stop(signum, handler_frame):
        process.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    threading.Thread(target=capture, args=(process,), daemon=True).start()
    try:
        server.serve_forever()
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        server.server_close()
    raise SystemExit(0 if process.returncode in (0, 255, -15) else 1)
