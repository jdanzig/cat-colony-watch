"""Small assert-based check for the iOS WhatsApp export parser."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parser import parse_chat


sample = """[10/25/26, 7:06:00 AM] Marta Ruiz: Fed the Laundromat colony.
<attached: mango-01.jpg>
[10/26/26, 7:18:00 AM] Diego Morales: Orange cat at the Laundromat, different day.
<attached: mango-02.jpg>
[11/2/26, 8:19:00 AM] Ana Torres: Found 4 kittens. https://maps.google.com/?q=25.7654,-80.2209
[11/2/26, 8:20:00 AM] Ana Torres: First line
segunda línea
[11/2/26, 9:03:00 AM] Camila Ortiz: <attached: chispa-03.jpg>
[11/2/26, 9:28:00 AM] Beatriz Cruz: I am finding a foster.
[11/2/26, 9:30:00 AM] Diego Morales: Todo listo."""

assert len(sample.splitlines()) == 10
reports = parse_chat(sample)
assert len(reports) == 7
assert reports[0] == {
    "sent_at": "2026-10-25T07:06:00",
    "sender": "Marta Ruiz",
    "kind": "message",
    "source": "import",
    "attachments": ["mango-01.jpg"],
    "text": "Fed the Laundromat colony.",
    "lat": None,
    "lng": None,
    "location_url": None,
    "raw": "[10/25/26, 7:06:00 AM] Marta Ruiz: Fed the Laundromat colony.\n"
    "<attached: mango-01.jpg>",
}
assert reports[1]["attachments"] == ["mango-02.jpg"]
assert reports[2]["lat"] == 25.7654
assert reports[2]["lng"] == -80.2209
assert reports[2]["location_url"] == "https://maps.google.com/?q=25.7654,-80.2209"
assert reports[3]["text"] == "First line\nsegunda línea"
assert reports[4]["text"] == ""
assert reports[4]["attachments"] == ["chispa-03.jpg"]

print("parser checks passed")
