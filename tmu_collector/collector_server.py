import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from submit_job import submit_job

class CollectorHandler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)

        self.send_header(
            "Access-Control-Allow-Origin",
            "https://recruitstudents.torontomu.ca"
        )

        self.send_header(
            "Access-Control-Allow-Methods",
            "POST, OPTIONS"
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type"
        )

        self.end_headers()
    def do_POST(self):
        content_length = int(
            self.headers.get("Content-Length", 0)
        )

        body = self.rfile.read(content_length)

        job = json.loads(
            body.decode("utf-8")
        )

        print("Received job:")
        print(job)

        aws_result = submit_job(job)

        print("AWS result:")
        print(aws_result)

        self.send_response(200)
        self.send_header(
            "Access-Control-Allow-Origin",
            "https://recruitstudents.torontomu.ca"
        )
        self.send_header(
            "Content-Type",
            "application/json"
        )
        self.end_headers()

        response = {
            "message": "Job received",
            "aws_result": aws_result
        }

        self.wfile.write(
            json.dumps(response).encode("utf-8")
        )


server = HTTPServer(
    ("127.0.0.1", 8765),
    CollectorHandler
)

print("TMU collector listening on http://127.0.0.1:8765")

server.serve_forever()